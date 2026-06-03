"""Git workflow slash commands."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taui.commands.registry import CommandContext, CommandResult


@dataclass(slots=True)
class GitDiffCommand:
    """Show local git changes and open the diff viewer."""

    name: str = "diff"
    description: str = "Show git diff (/diff [--staged|--ref REV])"
    accepts_args: bool = True
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if self._get_session is None:
            return CommandResult.fail("Session not available.")
        session = self._get_session()
        if session is None:
            return CommandResult.fail("Session not available.")

        options = _parse_diff_args(ctx.args)
        if isinstance(options, str):
            return CommandResult.fail(options)

        cwd = session.working_dir
        diff = _git_diff(cwd, staged=options.staged, ref=options.ref)
        if diff.error:
            return CommandResult.fail(diff.output)
        if not diff.output.strip():
            label = _diff_scope_label(staged=options.staged, ref=options.ref)
            return CommandResult.ok(f"No {label} changes.")

        stat = _git_diff_stat(cwd, staged=options.staged, ref=options.ref)
        files = _build_diff_files(cwd, staged=options.staged, ref=options.ref)
        title = _diff_title(staged=options.staged, ref=options.ref)
        summary = _format_diff_summary(title, stat.output, diff.output, files)
        return CommandResult.ok(
            summary,
            action="open_diff_view",
            title=title,
            diff=diff.output,
            files=files,
        )


@dataclass(slots=True)
class GitReviewCommand:
    """Start a read-only code review prompt for git changes."""

    name: str = "review"
    description: str = "Review git changes (/review [--staged|--ref REV|--security])"
    accepts_args: bool = True

    async def execute(self, ctx: CommandContext) -> CommandResult:
        options = _parse_review_args(ctx.args)
        if isinstance(options, str):
            return CommandResult.fail(options)

        scope = _diff_scope_label(staged=options.staged, ref=options.ref)
        focus = "security review" if options.security else "code review"
        prompt = (
            f"Perform a {focus} of the {scope} git changes.\n\n"
            "Use only read-only inspection. Check git status and the relevant diff first. "
            "Do not modify files, stage files, commit, or run mutating commands.\n\n"
            "Report findings first, ordered by severity, with file and line references "
            "where possible. Then list any test gaps or residual risk. If there are no "
            "issues, say that clearly."
        )
        if options.staged:
            prompt += "\n\nReview scope: staged changes (`git diff --staged`)."
        elif options.ref:
            prompt += f"\n\nReview scope: changes relative to `{options.ref}`."
        else:
            prompt += "\n\nReview scope: unstaged working tree changes."
        if options.security:
            prompt += (
                "\n\nSecurity focus: authentication, authorization, injection, secret "
                "exposure, unsafe filesystem or shell behavior, and dependency risk."
            )
        return CommandResult.ok(
            prompt,
            action="send_prompt",
            prompt=prompt,
            tool_names=["read", "grep", "glob", "git", "peek"],
        )


@dataclass(slots=True)
class GitCommitCommand:
    """Ask the agent to prepare a commit from current changes."""

    name: str = "commit"
    description: str = "Prepare a git commit with review and confirmation"
    accepts_args: bool = True

    async def execute(self, ctx: CommandContext) -> CommandResult:
        message_hint = " ".join(ctx.args).strip()
        prompt = (
            "Prepare a git commit for the current workspace changes.\n\n"
            "First inspect git status and the relevant diff. Summarize what will be "
            "committed, propose a concise commit message, and ask me to confirm before "
            "running any mutating git operation. Do not commit until I explicitly approve."
        )
        if message_hint:
            prompt += f"\n\nCommit message hint: {message_hint}"
        return CommandResult.ok(
            prompt,
            action="send_prompt",
            prompt=prompt,
            tool_names=["read", "grep", "glob", "git", "peek"],
        )


@dataclass(slots=True)
class WorktreeCommand:
    """List git worktrees, or create a new one.

    A session stays anchored to the directory it launched in, so this command
    doesn't switch the running session — `add` creates the worktree on disk and
    tells you how to open it (`taui -d <path>`), which starts a fresh session
    there.
    """

    name: str = "worktree"
    description: str = "List git worktrees, or add one (/worktree [add <branch> [base]])"
    accepts_args: bool = True
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if self._get_session is None:
            return CommandResult.fail("Session not available.")
        session = self._get_session()
        if session is None:
            return CommandResult.fail("Session not available.")
        cwd = Path(session.working_dir)

        sub = ctx.args[0].lower() if ctx.args else "list"
        if sub in ("list", "ls"):
            return _worktree_list(cwd)
        if sub == "add":
            if len(ctx.args) < 2:
                return CommandResult.fail("Usage: /worktree add <branch> [base]")
            base = ctx.args[2] if len(ctx.args) > 2 else None
            return _worktree_add(cwd, ctx.args[1], base)
        return CommandResult.fail(
            f"Unknown /worktree subcommand: {sub}. Use 'list' or 'add'."
        )


def _parse_worktree_porcelain(text: str) -> list[dict[str, str | None]]:
    """Parse `git worktree list --porcelain` into one dict per worktree."""
    entries: list[dict[str, str | None]] = []
    cur: dict[str, str | None] = {}
    for line in text.splitlines():
        if not line.strip():
            if cur:
                entries.append(cur)
                cur = {}
            continue
        if line.startswith("worktree "):
            cur = {"path": line[len("worktree ") :]}
        elif line.startswith("HEAD "):
            cur["head"] = line[len("HEAD ") :]
        elif line.startswith("branch "):
            ref = line[len("branch ") :]
            if ref.startswith("refs/heads/"):
                ref = ref[len("refs/heads/") :]
            cur["branch"] = ref
        elif line.strip() == "detached":
            cur["branch"] = None
    if cur:
        entries.append(cur)
    return entries


def _worktree_list(cwd: Path) -> CommandResult:
    out = _run_git(cwd, ["worktree", "list", "--porcelain"])
    if out.error:
        return CommandResult.fail(out.output.strip() or "git worktree list failed.")
    entries = _parse_worktree_porcelain(out.output)
    if not entries:
        return CommandResult.ok("No worktrees.", worktrees=[])
    try:
        here = str(cwd.resolve())
    except OSError:
        here = str(cwd)
    lines = ["Worktrees:"]
    for e in entries:
        marker = "*" if e.get("path") == here else " "
        branch = e.get("branch") or "(detached)"
        lines.append(f" {marker} {e.get('path')}  [{branch}]")
    return CommandResult.ok("\n".join(lines), worktrees=entries)


def _worktree_add(cwd: Path, branch: str, base: str | None) -> CommandResult:
    branch = branch.strip()
    if not branch:
        return CommandResult.fail("Usage: /worktree add <branch> [base]")
    safe = branch.replace("/", "-").replace(" ", "-")
    target = cwd / ".worktrees" / safe
    if target.exists():
        return CommandResult.fail(f"Path already exists: {target}")

    branch_exists = not _run_git(
        cwd, ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"]
    ).error
    if branch_exists:
        cmd = ["worktree", "add", str(target), branch]
    else:
        cmd = ["worktree", "add", "-b", branch, str(target)]
        if base:
            cmd.append(base)

    out = _run_git(cwd, cmd)
    if out.error:
        return CommandResult.fail(out.output.strip() or "git worktree add failed.")
    return CommandResult.ok(
        f"Created worktree for '{branch}' at {target}\n"
        f"Open it in a new session with:  taui -d {target}",
        action="worktree_added",
        worktree_path=str(target),
        branch=branch,
    )


@dataclass(frozen=True, slots=True)
class _DiffOptions:
    staged: bool = False
    ref: str | None = None


@dataclass(frozen=True, slots=True)
class _ReviewOptions:
    staged: bool = False
    ref: str | None = None
    security: bool = False


@dataclass(frozen=True, slots=True)
class _GitOutput:
    output: str
    returncode: int

    @property
    def error(self) -> bool:
        return self.returncode != 0


def _parse_diff_args(args: list[str]) -> _DiffOptions | str:
    staged = False
    ref: str | None = None
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--staged":
            staged = True
            index += 1
            continue
        if arg == "--ref":
            if index + 1 >= len(args):
                return "Usage: /diff [--staged|--ref REV]"
            ref = args[index + 1]
            index += 2
            continue
        return f"Unknown /diff option: {arg}"
    if staged and ref:
        return "Use either --staged or --ref REV, not both."
    return _DiffOptions(staged=staged, ref=ref)


def _parse_review_args(args: list[str]) -> _ReviewOptions | str:
    staged = False
    ref: str | None = None
    security = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--staged":
            staged = True
            index += 1
            continue
        if arg == "--security":
            security = True
            index += 1
            continue
        if arg == "--ref":
            if index + 1 >= len(args):
                return "Usage: /review [--staged|--ref REV|--security]"
            ref = args[index + 1]
            index += 2
            continue
        return f"Unknown /review option: {arg}"
    if staged and ref:
        return "Use either --staged or --ref REV, not both."
    return _ReviewOptions(staged=staged, ref=ref, security=security)


def _git_diff(cwd: Path, *, staged: bool, ref: str | None) -> _GitOutput:
    cmd = ["diff", "--no-ext-diff"]
    if staged:
        cmd.append("--staged")
    elif ref:
        cmd.append(ref)
    return _run_git(cwd, cmd)


def _git_diff_stat(cwd: Path, *, staged: bool, ref: str | None) -> _GitOutput:
    cmd = ["diff", "--no-ext-diff", "--stat"]
    if staged:
        cmd.append("--staged")
    elif ref:
        cmd.append(ref)
    return _run_git(cwd, cmd)


def _git_diff_name_status(cwd: Path, *, staged: bool, ref: str | None) -> _GitOutput:
    cmd = ["diff", "--no-ext-diff", "--name-status"]
    if staged:
        cmd.append("--staged")
    elif ref:
        cmd.append(ref)
    return _run_git(cwd, cmd)


def _run_git(cwd: Path, args: list[str], *, input_text: str | None = None) -> _GitOutput:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except FileNotFoundError:
        return _GitOutput("git executable not found.", 127)
    except subprocess.TimeoutExpired:
        return _GitOutput("git command timed out.", 124)
    return _GitOutput(proc.stdout + proc.stderr, proc.returncode)


def _build_diff_files(cwd: Path, *, staged: bool, ref: str | None) -> list[dict[str, str]]:
    name_status = _git_diff_name_status(cwd, staged=staged, ref=ref)
    if name_status.error:
        return []

    files: list[dict[str, str]] = []
    for line in name_status.output.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        old_path = parts[1]
        new_path = parts[-1]
        path = new_path
        old_text = _read_old_text(cwd, old_path, staged=staged, ref=ref)
        new_text = _read_new_text(cwd, new_path, staged=staged)
        files.append(
            {
                "path": path,
                "old_path": old_path,
                "new_path": new_path,
                "status": status,
                "old_text": old_text,
                "new_text": new_text,
            }
        )
    return files


def _read_old_text(cwd: Path, path: str, *, staged: bool, ref: str | None) -> str:
    if staged:
        return _git_blob(cwd, f"HEAD:{path}")
    if ref:
        return _git_blob(cwd, f"{ref}:{path}")
    return _git_blob(cwd, f":{path}")


def _read_new_text(cwd: Path, path: str, *, staged: bool) -> str:
    if staged:
        return _git_blob(cwd, f":{path}")
    try:
        return (cwd / path).read_text()
    except (OSError, UnicodeDecodeError):
        return ""


def _git_blob(cwd: Path, spec: str) -> str:
    output = _run_git(cwd, ["show", spec])
    if output.error:
        return ""
    return output.output


def _format_diff_summary(
    title: str,
    stat: str,
    diff: str,
    files: list[dict[str, str]],
) -> str:
    changed = len(files) if files else diff.count("\ndiff --git ")
    if changed == 0 and diff.startswith("diff --git "):
        changed = 1
    lines = [title]
    if stat.strip():
        lines.extend(["", stat.strip()])
    lines.extend(["", f"{changed} file(s) changed. Opening diff view."])
    return "\n".join(lines)


def _diff_title(*, staged: bool, ref: str | None) -> str:
    if staged:
        return "Staged Diff"
    if ref:
        return f"Diff Against {ref}"
    return "Working Tree Diff"


def _diff_scope_label(*, staged: bool, ref: str | None) -> str:
    if staged:
        return "staged"
    if ref:
        return f"changes against {ref}"
    return "working tree"
