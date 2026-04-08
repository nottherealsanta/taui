"""Git tool — git operations accessible to the agent."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from taui.tools.base import ToolCategory, ToolContext, ToolResult
from taui.tools.builtins._common import normalize_tool_error


_READ_OPS = frozenset({
    "status", "diff", "log", "show", "blame",
    "branch_list", "branch_current", "stash_list",
})
_WRITE_OPS = frozenset({
    "commit", "add", "checkout", "stash_push", "stash_pop",
})


@dataclass(slots=True)
class GitTool:
    """Execute git operations within the workspace."""

    name: str = "git"
    description: str = (
        "Run git operations. Read operations: status, diff, log, show, blame, "
        "branch_list, branch_current, stash_list. Write operations (require approval): "
        "commit, add, checkout, stash_push, stash_pop."
    )
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.GIT

    def __post_init__(self) -> None:
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
                        "description": "Operation-specific arguments",
                    },
                },
                "required": ["operation"],
            }

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        operation = arguments.get("operation")
        if not isinstance(operation, str):
            return normalize_tool_error(
                "Invalid git arguments: 'operation' must be a string."
            )

        args = arguments.get("args", {})
        if not isinstance(args, dict):
            args = {}

        all_ops = _READ_OPS | _WRITE_OPS
        if operation not in all_ops:
            return normalize_tool_error(
                f"Unknown git operation '{operation}'. "
                f"Valid operations: {', '.join(sorted(all_ops))}"
            )

        handler = _HANDLERS.get(operation)
        if handler is None:
            return normalize_tool_error(f"No handler for operation '{operation}'.")

        return await handler(args, context)


# ---------------------------------------------------------------------------
# Operation handlers
# ---------------------------------------------------------------------------

async def _run_git(
    cmd: list[str], cwd: str, max_output: int = 50_000
) -> tuple[str, int]:
    """Run a git command and return (output, exit_code)."""
    process = await asyncio.create_subprocess_exec(
        "git", *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
    output = stdout.decode("utf-8", errors="replace")
    if len(output) > max_output:
        output = output[:max_output] + "\n\n[output truncated]"
    return output, process.returncode or 0


async def _status(args: dict, context: ToolContext) -> ToolResult:
    output, rc = await _run_git(["status", "--porcelain=v1"], str(context.working_dir))
    if not output.strip():
        return ToolResult.ok("Working tree clean.", metadata={"clean": True})
    return ToolResult.ok(output, metadata={"clean": False})


async def _diff(args: dict, context: ToolContext) -> ToolResult:
    cmd = ["diff"]
    if args.get("staged"):
        cmd.append("--staged")
    file_path = args.get("file")
    if isinstance(file_path, str):
        cmd.append("--")
        cmd.append(file_path)
    output, rc = await _run_git(cmd, str(context.working_dir))
    if not output.strip():
        return ToolResult.ok("No changes.", metadata={"empty": True})
    return ToolResult.ok(output)


async def _log(args: dict, context: ToolContext) -> ToolResult:
    count = args.get("count", 10)
    if not isinstance(count, int) or count < 1:
        count = 10
    cmd = ["log", f"-{min(count, 100)}"]
    if args.get("oneline"):
        cmd.append("--oneline")
    file_path = args.get("file")
    if isinstance(file_path, str):
        cmd.append("--")
        cmd.append(file_path)
    output, rc = await _run_git(cmd, str(context.working_dir))
    return ToolResult.ok(output)


async def _show(args: dict, context: ToolContext) -> ToolResult:
    ref = args.get("ref", "HEAD")
    if not isinstance(ref, str):
        ref = "HEAD"
    output, rc = await _run_git(["show", "--stat", ref], str(context.working_dir))
    if rc != 0:
        return normalize_tool_error(f"git show failed: {output}")
    return ToolResult.ok(output)


async def _blame(args: dict, context: ToolContext) -> ToolResult:
    file_path = args.get("file")
    if not isinstance(file_path, str):
        return normalize_tool_error("blame requires 'file' argument.")
    cmd = ["blame", file_path]
    line_start = args.get("line_start")
    line_end = args.get("line_end")
    if isinstance(line_start, int) and isinstance(line_end, int):
        cmd.extend([f"-L{line_start},{line_end}"])
    elif isinstance(line_start, int):
        cmd.extend([f"-L{line_start},+10"])
    output, rc = await _run_git(cmd, str(context.working_dir))
    if rc != 0:
        return normalize_tool_error(f"git blame failed: {output}")
    return ToolResult.ok(output)


async def _branch_list(args: dict, context: ToolContext) -> ToolResult:
    output, rc = await _run_git(
        ["branch", "--list", "--no-color", "-v"], str(context.working_dir)
    )
    return ToolResult.ok(output)


async def _branch_current(args: dict, context: ToolContext) -> ToolResult:
    output, rc = await _run_git(
        ["branch", "--show-current"], str(context.working_dir)
    )
    return ToolResult.ok(output.strip(), metadata={"branch": output.strip()})


async def _stash_list(args: dict, context: ToolContext) -> ToolResult:
    output, rc = await _run_git(["stash", "list"], str(context.working_dir))
    if not output.strip():
        return ToolResult.ok("No stashes.", metadata={"count": 0})
    return ToolResult.ok(output)


async def _commit(args: dict, context: ToolContext) -> ToolResult:
    message = args.get("message")
    if not isinstance(message, str) or not message.strip():
        return normalize_tool_error("commit requires a non-empty 'message'.")
    output, rc = await _run_git(
        ["commit", "-m", message], str(context.working_dir)
    )
    if rc != 0:
        return normalize_tool_error(f"git commit failed: {output}")
    return ToolResult.ok(output)


async def _add(args: dict, context: ToolContext) -> ToolResult:
    files = args.get("files")
    if isinstance(files, list):
        cmd = ["add"] + [f for f in files if isinstance(f, str)]
    elif isinstance(files, str):
        cmd = ["add", files]
    else:
        cmd = ["add", "-A"]
    output, rc = await _run_git(cmd, str(context.working_dir))
    if rc != 0:
        return normalize_tool_error(f"git add failed: {output}")
    return ToolResult.ok(output or "Files staged.", metadata={"operation": "add"})


async def _checkout(args: dict, context: ToolContext) -> ToolResult:
    ref = args.get("ref")
    if not isinstance(ref, str):
        return normalize_tool_error("checkout requires 'ref' argument.")
    output, rc = await _run_git(["checkout", ref], str(context.working_dir))
    if rc != 0:
        return normalize_tool_error(f"git checkout failed: {output}")
    return ToolResult.ok(output or f"Checked out '{ref}'.")


async def _stash_push(args: dict, context: ToolContext) -> ToolResult:
    cmd = ["stash", "push"]
    message = args.get("message")
    if isinstance(message, str):
        cmd.extend(["-m", message])
    output, rc = await _run_git(cmd, str(context.working_dir))
    if rc != 0:
        return normalize_tool_error(f"git stash push failed: {output}")
    return ToolResult.ok(output)


async def _stash_pop(args: dict, context: ToolContext) -> ToolResult:
    cmd = ["stash", "pop"]
    index = args.get("index")
    if isinstance(index, int):
        cmd.append(f"stash@{{{index}}}")
    output, rc = await _run_git(cmd, str(context.working_dir))
    if rc != 0:
        return normalize_tool_error(f"git stash pop failed: {output}")
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
