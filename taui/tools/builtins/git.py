"""Git tool — git operations accessible to the agent."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taui.tools.base import ToolCategory, ToolResult

_READ_OPS = frozenset({
    "status", "diff", "log", "show", "blame",
    "branch_list", "branch_current", "stash_list",
})
_WRITE_OPS = frozenset({
    "commit", "add", "checkout", "stash_push", "stash_pop",
})
_ALL_OPS = _READ_OPS | _WRITE_OPS


@dataclass
class GitTool:
    """Execute git operations within the workspace."""

    name: str = "git"
    description: str = (
        "Run git operations. Read: status, diff, log, show, blame, "
        "branch_list, branch_current, stash_list. "
        "Write (require approval): commit, add, checkout, stash_push, stash_pop."
    )
    category: ToolCategory = ToolCategory.GIT
    working_dir: Path = field(default_factory=Path.cwd)
    guidelines: str = (
        "Use `git` for version control operations. Always check `status` "
        "before committing. Write a clear commit message. "
        "Prefer small, focused commits."
    )
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    def __post_init__(self):
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "description": (
                            "Git operation: status, diff, log, show, blame, "
                            "branch_list, branch_current, stash_list, commit, "
                            "add, checkout, stash_push, stash_pop"
                        ),
                    },
                    "args": {
                        "type": "object",
                        "description": "Operation-specific arguments.",
                    },
                },
                "required": ["operation"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        operation = arguments.get("operation")
        if not isinstance(operation, str):
            return ToolResult.fail("'operation' must be a string.")

        if operation not in _ALL_OPS:
            return ToolResult.fail(
                f"Unknown operation '{operation}'. "
                f"Valid: {', '.join(sorted(_ALL_OPS))}"
            )

        args = arguments.get("args", {})
        if not isinstance(args, dict):
            args = {}

        handler = _HANDLERS.get(operation)
        if handler is None:
            return ToolResult.fail(f"No handler for '{operation}'.")

        return await handler(args, self.working_dir)


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _run_git(
    cmd: list[str], cwd: Path, max_output: int = 50_000
) -> tuple[str, int]:
    """Run a git command and return (output, exit_code)."""
    proc = await asyncio.create_subprocess_exec(
        "git", *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    output = stdout.decode("utf-8", errors="replace")
    if len(output) > max_output:
        output = output[:max_output] + "\n\n[output truncated]"
    return output, proc.returncode or 0


# ── Operation handlers ─────────────────────────────────────────────────────────


async def _status(args: dict, cwd: Path) -> ToolResult:
    output, _ = await _run_git(["status", "--porcelain=v1"], cwd)
    if not output.strip():
        return ToolResult.ok(
            "Working tree clean.",
            clean=True, files=[], counts={},
        )
    # Parse porcelain output into file list
    files = []
    counts: dict[str, int] = {}
    for line in output.strip().split("\n"):
        if len(line) < 4:
            continue
        status_code = line[:2].strip()
        filepath = line[3:]
        files.append({"status": status_code, "path": filepath})
        counts[status_code] = counts.get(status_code, 0) + 1
    return ToolResult.ok(
        output, clean=False, files=files, counts=counts,
    )


async def _diff(args: dict, cwd: Path) -> ToolResult:
    cmd = ["diff", "--stat"]
    if args.get("staged"):
        cmd.append("--staged")
    path = args.get("file")
    if isinstance(path, str):
        cmd += ["--", path]
    stat_output, _ = await _run_git(cmd, cwd)

    # Also get the full diff for content
    full_cmd = ["diff"]
    if args.get("staged"):
        full_cmd.append("--staged")
    if isinstance(path, str):
        full_cmd += ["--", path]
    full_output, _ = await _run_git(full_cmd, cwd)

    if not full_output.strip():
        return ToolResult.ok("No changes.", empty=True)

    # Count hunks
    hunks = len(re.findall(r"^@@", full_output, re.MULTILINE))
    files_changed = len(re.findall(
        r"^diff --git", full_output, re.MULTILINE
    ))

    return ToolResult.ok(
        full_output,
        stat=stat_output.strip(),
        hunks=hunks,
        files_changed=files_changed,
    )


async def _log(args: dict, cwd: Path) -> ToolResult:
    count = args.get("count", 10)
    if not isinstance(count, int) or count < 1:
        count = 10
    cmd = ["log", f"-{min(count, 100)}", "--oneline"]
    path = args.get("file")
    if isinstance(path, str):
        cmd += ["--", path]
    output, _ = await _run_git(cmd, cwd)
    return ToolResult.ok(output)


async def _show(args: dict, cwd: Path) -> ToolResult:
    ref = args.get("ref", "HEAD")
    if not isinstance(ref, str):
        ref = "HEAD"
    output, rc = await _run_git(["show", "--stat", ref], cwd)
    if rc != 0:
        return ToolResult.fail(f"git show failed: {output}")
    return ToolResult.ok(output)


async def _blame(args: dict, cwd: Path) -> ToolResult:
    path = args.get("file")
    if not isinstance(path, str):
        return ToolResult.fail("blame requires 'file' argument.")
    cmd = ["blame", path]
    start = args.get("line_start")
    end = args.get("line_end")
    if isinstance(start, int) and isinstance(end, int):
        cmd.append(f"-L{start},{end}")
    elif isinstance(start, int):
        cmd.append(f"-L{start},+10")
    output, rc = await _run_git(cmd, cwd)
    if rc != 0:
        return ToolResult.fail(f"git blame failed: {output}")
    return ToolResult.ok(output)


async def _branch_list(args: dict, cwd: Path) -> ToolResult:
    output, _ = await _run_git(["branch", "--list", "--no-color", "-v"], cwd)
    return ToolResult.ok(output)


async def _branch_current(args: dict, cwd: Path) -> ToolResult:
    output, _ = await _run_git(["branch", "--show-current"], cwd)
    return ToolResult.ok(output.strip(), branch=output.strip())


async def _stash_list(args: dict, cwd: Path) -> ToolResult:
    output, _ = await _run_git(["stash", "list"], cwd)
    if not output.strip():
        return ToolResult.ok("No stashes.", count=0)
    return ToolResult.ok(output)


async def _commit(args: dict, cwd: Path) -> ToolResult:
    message = args.get("message")
    if not isinstance(message, str) or not message.strip():
        return ToolResult.fail("commit requires a non-empty 'message'.")
    output, rc = await _run_git(["commit", "-m", message], cwd)
    if rc != 0:
        return ToolResult.fail(f"git commit failed: {output}")
    return ToolResult.ok(output)


async def _add(args: dict, cwd: Path) -> ToolResult:
    files = args.get("files")
    if isinstance(files, list):
        cmd = ["add"] + [f for f in files if isinstance(f, str)]
    elif isinstance(files, str):
        cmd = ["add", files]
    else:
        cmd = ["add", "-A"]
    output, rc = await _run_git(cmd, cwd)
    if rc != 0:
        return ToolResult.fail(f"git add failed: {output}")
    return ToolResult.ok(output or "Files staged.")


async def _checkout(args: dict, cwd: Path) -> ToolResult:
    ref = args.get("ref")
    if not isinstance(ref, str):
        return ToolResult.fail("checkout requires 'ref' argument.")
    output, rc = await _run_git(["checkout", ref], cwd)
    if rc != 0:
        return ToolResult.fail(f"git checkout failed: {output}")
    return ToolResult.ok(output or f"Checked out '{ref}'.")


async def _stash_push(args: dict, cwd: Path) -> ToolResult:
    cmd = ["stash", "push"]
    message = args.get("message")
    if isinstance(message, str):
        cmd += ["-m", message]
    output, rc = await _run_git(cmd, cwd)
    if rc != 0:
        return ToolResult.fail(f"git stash push failed: {output}")
    return ToolResult.ok(output)


async def _stash_pop(args: dict, cwd: Path) -> ToolResult:
    cmd = ["stash", "pop"]
    index = args.get("index")
    if isinstance(index, int):
        cmd.append(f"stash@{{{index}}}")
    output, rc = await _run_git(cmd, cwd)
    if rc != 0:
        return ToolResult.fail(f"git stash pop failed: {output}")
    return ToolResult.ok(output)


_HANDLERS = {
    "status": _status,
    "diff": _diff,
    "log": _log,
    "show": _show,
    "blame": _blame,
    "branch_list": _branch_list,
    "branch_current": _branch_current,
    "stash_list": _stash_list,
    "commit": _commit,
    "add": _add,
    "checkout": _checkout,
    "stash_push": _stash_push,
    "stash_pop": _stash_pop,
}
