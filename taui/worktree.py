"""
Worktree management — sandboxed copies of the repo on fresh branches.

A WorktreeHandle represents an active git worktree owned by a session.
The handle stores the on-disk path and the branch name so the session
can route tool calls through the sandboxed checkout. Worktrees live
under ``~/.taui/worktrees/<session_id>/<branch>/`` so that concurrent
sessions don't collide and a session can host multiple sandboxes over
its lifetime.

Two scenarios this enables:

1. Risky multi-file refactors — bail out by deleting the worktree, no
   ``git stash`` dance.
2. Parallel sub-agents — each background task gets its own worktree so
   they don't fight over the index or scratch files.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

# Loose but safe — anything outside this set would need shell-quoting.
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


class WorktreeError(Exception):
    """Raised when a worktree operation fails."""


@dataclass(slots=True)
class WorktreeHandle:
    """An active git worktree owned by a session."""

    path: Path
    branch: str
    base: str
    origin: Path  # the repo cwd the session started from

    @property
    def cwd(self) -> Path:
        return self.path


def _validate_branch(name: str) -> None:
    if not name or not _BRANCH_RE.match(name):
        raise WorktreeError(
            f"Invalid branch name {name!r}. Use letters, digits, '.', '_', "
            "'-', or '/'."
        )


def worktree_root(session_id: str) -> Path:
    """Return the directory under ``~/.taui/worktrees/<session_id>/``."""
    return Path.home() / ".taui" / "worktrees" / session_id


async def _run_git(
    args: list[str], *, cwd: Path, timeout: float = 30.0
) -> tuple[str, int]:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return stdout.decode("utf-8", errors="replace"), proc.returncode or 0


async def is_git_repo(path: Path) -> bool:
    out, rc = await _run_git(["rev-parse", "--is-inside-work-tree"], cwd=path)
    return rc == 0 and out.strip() == "true"


async def enter(
    *,
    session_id: str,
    origin: Path,
    branch: str,
    base: str | None = None,
) -> WorktreeHandle:
    """Create a worktree on a new branch.

    Args:
        session_id: Used to scope the worktree directory.
        origin: The repo path the session is running in.
        branch: New branch name. Created if it doesn't exist; reused if it does.
        base: Optional base ref. Defaults to the current HEAD of ``origin``.
    """
    _validate_branch(branch)
    if not await is_git_repo(origin):
        raise WorktreeError(f"{origin} is not a git repository.")

    target = worktree_root(session_id) / branch
    if target.exists():
        raise WorktreeError(f"Worktree path already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)

    # Check whether branch already exists. ``git rev-parse --verify`` exits 0
    # iff the ref resolves.
    _, rc = await _run_git(
        ["rev-parse", "--verify", f"refs/heads/{branch}"], cwd=origin
    )
    branch_exists = rc == 0

    cmd = ["worktree", "add"]
    if branch_exists:
        cmd += [str(target), branch]
        resolved_base = branch
    else:
        cmd += ["-b", branch]
        if base:
            cmd += [str(target), base]
            resolved_base = base
        else:
            cmd += [str(target)]
            resolved_base = "HEAD"

    out, rc = await _run_git(cmd, cwd=origin)
    if rc != 0:
        raise WorktreeError(f"git worktree add failed: {out.strip()}")

    return WorktreeHandle(
        path=target.resolve(),
        branch=branch,
        base=resolved_base,
        origin=origin.resolve(),
    )


async def is_dirty(handle: WorktreeHandle) -> bool:
    """Return True if the worktree has uncommitted changes."""
    out, rc = await _run_git(["status", "--porcelain"], cwd=handle.path)
    if rc != 0:
        return False
    return bool(out.strip())


async def exit_(handle: WorktreeHandle, *, keep: bool) -> str:
    """Remove the worktree (and its branch if ``keep`` is False).

    Returns a short status string.
    """
    if keep:
        # Leave the worktree and branch on disk; just detach from the session.
        return f"Kept worktree at {handle.path} (branch {handle.branch})."

    out, rc = await _run_git(
        ["worktree", "remove", "--force", str(handle.path)],
        cwd=handle.origin,
    )
    if rc != 0:
        raise WorktreeError(f"git worktree remove failed: {out.strip()}")
    # Best-effort branch deletion — ignore failure (e.g. branch checked out
    # elsewhere or has unmerged commits).
    await _run_git(["branch", "-D", handle.branch], cwd=handle.origin)
    return f"Removed worktree at {handle.path} (branch {handle.branch})."
