"""Worktree tool — sandboxed git worktree management for the agent."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taui import worktree as wt
from taui.tools.base import ToolCategory, ToolResult

# Session-side callbacks injected at session wiring time. The tool itself is a
# thin wrapper; the session owns the worktree handle and the side effects
# (rebinding tool cwd, persisting events).
EnterCallback = Callable[[wt.WorktreeHandle], Awaitable[None]]
ExitCallback = Callable[[bool], Awaitable[None]]
HandleGetter = Callable[[], "wt.WorktreeHandle | None"]


@dataclass
class WorktreeTool:
    """Create or exit a sandboxed git worktree.

    The agent uses this to quarantine risky multi-file work or to give
    parallel sub-agents their own checkout. ``enter`` creates a worktree on
    a fresh branch and rebinds the session's working directory to it; ``exit``
    either keeps the worktree on disk or removes it along with its branch.
    """

    name: str = "worktree"
    description: str = (
        "Sandboxed git worktrees. Operations: enter(branch, base?) creates a "
        "worktree on a new branch and switches the session into it; exit(keep) "
        "leaves the sandbox, either keeping the worktree on disk (keep=true) "
        "or removing it and its branch (keep=false)."
    )
    category: ToolCategory = ToolCategory.GIT
    requires_approval: bool = True
    working_dir: Path = field(default_factory=Path.cwd)
    guidelines: str = (
        "Use a worktree before risky refactors or to isolate parallel work "
        "from the user's index. Always exit with keep=false when abandoning "
        "an approach, or commit/push first then exit with keep=true."
    )
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    # Session injects these at startup.
    _on_enter: EnterCallback | None = None
    _on_exit: ExitCallback | None = None
    _get_handle: HandleGetter | None = None
    _session_id: str = ""

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["enter", "exit", "status"],
                        "description": (
                            "enter: create a worktree and switch into it. "
                            "exit: leave the active worktree. "
                            "status: show the active worktree, if any."
                        ),
                    },
                    "branch": {
                        "type": "string",
                        "description": "Branch name (required for enter).",
                    },
                    "base": {
                        "type": "string",
                        "description": (
                            "Optional base ref for enter (defaults to HEAD)."
                        ),
                    },
                    "keep": {
                        "type": "boolean",
                        "description": (
                            "For exit: true keeps the worktree and branch on "
                            "disk; false removes both. Default false."
                        ),
                    },
                },
                "required": ["operation"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        operation = arguments.get("operation")
        if operation == "enter":
            return await self._enter(arguments)
        if operation == "exit":
            return await self._exit(arguments)
        if operation == "status":
            return self._status()
        return ToolResult.fail(
            f"Unknown operation {operation!r}. Use 'enter', 'exit', or 'status'."
        )

    async def _enter(self, arguments: dict[str, Any]) -> ToolResult:
        branch = arguments.get("branch")
        if not isinstance(branch, str) or not branch.strip():
            return ToolResult.fail("'branch' is required for worktree enter.")
        base = arguments.get("base")
        base_val = base if isinstance(base, str) and base else None

        if self._get_handle is not None and self._get_handle() is not None:
            return ToolResult.fail(
                "A worktree is already active for this session. Exit it first."
            )
        if not self._session_id:
            return ToolResult.fail("Worktree tool is not wired to a session.")

        try:
            handle = await wt.enter(
                session_id=self._session_id,
                origin=self.working_dir,
                branch=branch.strip(),
                base=base_val,
            )
        except wt.WorktreeError as exc:
            return ToolResult.fail(str(exc))

        if self._on_enter is not None:
            await self._on_enter(handle)

        return ToolResult.ok(
            f"Entered worktree on branch '{handle.branch}' at {handle.path}.",
            branch=handle.branch,
            path=str(handle.path),
            base=handle.base,
        )

    async def _exit(self, arguments: dict[str, Any]) -> ToolResult:
        keep = bool(arguments.get("keep", False))
        if self._get_handle is None:
            return ToolResult.fail("Worktree tool is not wired to a session.")
        handle = self._get_handle()
        if handle is None:
            return ToolResult.ok("No active worktree.")

        dirty = False
        try:
            dirty = await wt.is_dirty(handle)
        except Exception:
            pass

        if dirty and not keep:
            return ToolResult.fail(
                "Worktree has uncommitted changes. Commit them, or pass "
                "keep=true to preserve the worktree on disk."
            )

        try:
            message = await wt.exit_(handle, keep=keep)
        except wt.WorktreeError as exc:
            return ToolResult.fail(str(exc))

        if self._on_exit is not None:
            await self._on_exit(keep)

        return ToolResult.ok(message, kept=keep, branch=handle.branch)

    def _status(self) -> ToolResult:
        if self._get_handle is None:
            return ToolResult.ok("No active worktree.")
        handle = self._get_handle()
        if handle is None:
            return ToolResult.ok("No active worktree.")
        return ToolResult.ok(
            f"Active worktree: branch '{handle.branch}' at {handle.path}.",
            branch=handle.branch,
            path=str(handle.path),
            base=handle.base,
        )
