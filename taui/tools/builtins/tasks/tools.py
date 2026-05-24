"""
Background task tools.

These are non-blocking, fire-and-poll counterparts to `sub_agent`. The
agent fires a task with `task_create`, continues the conversation, and
later inspects status with `task_list` / `task_get` / `task_output`, or
cancels with `task_stop`.

Each tool holds a reference to the session's TaskManager. The manager is
injected by `Session.create()` after the tools are constructed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from taui.tasks.manager import TaskManager, TaskRecord, TaskState
from taui.tools.base import ToolCategory, ToolResult


def _format_record(record: TaskRecord, *, include_output: bool = False) -> str:
    lines = [
        f"[{record.id}] {record.title}",
        f"  state: {record.state.value}",
    ]
    if record.agent_id:
        lines.append(f"  agent: {record.agent_id}")
    if record.model:
        lines.append(f"  model: {record.model}")
    if record.turns is not None:
        lines.append(f"  turns: {record.turns}/{record.max_turns}")
    if record.last_output and include_output:
        lines.append(f"  last: {record.last_output[:200]}")
    if record.error:
        lines.append(f"  error: {record.error[:200]}")
    if record.result and include_output:
        # Truncate large results in summaries; task_output returns the full body.
        body = record.result.strip()
        if len(body) > 800:
            body = body[:800] + " …"
        lines.append("  result:")
        for line in body.splitlines():
            lines.append(f"    {line}")
    return "\n".join(lines)


@dataclass
class _TaskToolBase:
    """Common manager-injection plumbing shared by all six tools."""

    _manager: TaskManager | None = field(default=None, repr=False)

    def set_manager(self, manager: TaskManager) -> None:
        self._manager = manager

    def _require_manager(self) -> TaskManager | None:
        return self._manager


@dataclass
class TaskCreateTool(_TaskToolBase):
    """Schedule a background task and return its id immediately."""

    name: str = "task_create"
    description: str = (
        "Fire a long-running sub-agent task in the background and return "
        "immediately with a task id. The task continues running while the "
        "main conversation proceeds. Use task_list/task_get/task_output to "
        "check on it, and task_stop to cancel."
    )
    category: ToolCategory = ToolCategory.AGENT
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    guidelines: str = (
        "Use `task_create` to dispatch work that may take a while — running "
        "tests, broad searches, multi-step refactors, or any task you can "
        "describe completely up-front. Each call returns instantly with a "
        "task id; the work runs concurrently."
    )

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short label for the task (≤60 chars).",
                    },
                    "prompt": {
                        "type": "string",
                        "description": (
                            "Full instructions for the sub-agent. Be specific "
                            "about expected output, since you won't be able "
                            "to clarify mid-run."
                        ),
                    },
                    "agent_id": {
                        "type": "string",
                        "description": (
                            "Optional agent profile to spawn (3-letter id). "
                            "Overrides tools/model/system_prompt."
                        ),
                    },
                    "tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Tool names the background agent can use. "
                            "Defaults to read-only tools."
                        ),
                    },
                    "max_turns": {
                        "type": "integer",
                        "description": "Max turns for the background agent (default 10).",
                    },
                },
                "required": ["title", "prompt"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        mgr = self._require_manager()
        if mgr is None:
            return ToolResult.fail(
                "Background tasks are not available in this session."
            )

        title = arguments.get("title")
        prompt = arguments.get("prompt")
        if not isinstance(title, str) or not title.strip():
            return ToolResult.fail("'title' must be a non-empty string.")
        if not isinstance(prompt, str) or not prompt.strip():
            return ToolResult.fail("'prompt' must be a non-empty string.")

        tools = arguments.get("tools")
        if tools is not None and not isinstance(tools, list):
            return ToolResult.fail("'tools' must be an array of tool names.")

        record = await mgr.create(
            title=title.strip()[:60],
            prompt=prompt,
            tools=[t for t in tools] if isinstance(tools, list) else None,
            agent_id=(arguments.get("agent_id") or None),
            max_turns=int(arguments.get("max_turns") or 10),
        )
        return ToolResult.ok(
            f"Task {record.id} queued: {record.title}",
            task_id=record.id,
            state=record.state.value,
        )


@dataclass
class TaskListTool(_TaskToolBase):
    """List all background tasks in this session."""

    name: str = "task_list"
    description: str = (
        "List background tasks created in this session, with their current "
        "state (queued/running/done/failed/cancelled)."
    )
    category: ToolCategory = ToolCategory.AGENT
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "state": {
                        "type": "string",
                        "enum": [
                            "queued",
                            "running",
                            "done",
                            "failed",
                            "cancelled",
                        ],
                        "description": "Optional filter by state.",
                    },
                },
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        mgr = self._require_manager()
        if mgr is None:
            return ToolResult.fail(
                "Background tasks are not available in this session."
            )
        records = mgr.list()
        filt = arguments.get("state")
        if filt:
            records = [r for r in records if r.state.value == filt]
        if not records:
            return ToolResult.ok("No background tasks.")
        chunks = [_format_record(r) for r in records]
        return ToolResult.ok("\n\n".join(chunks))


@dataclass
class TaskGetTool(_TaskToolBase):
    """Inspect a single background task by id."""

    name: str = "task_get"
    description: str = (
        "Get the current state and metadata of a background task by id. "
        "Includes the last output line but not the full output — use "
        "task_output for that."
    )
    category: ToolCategory = ToolCategory.AGENT
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                },
                "required": ["task_id"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        mgr = self._require_manager()
        if mgr is None:
            return ToolResult.fail(
                "Background tasks are not available in this session."
            )
        task_id = arguments.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            return ToolResult.fail("'task_id' is required.")
        record = mgr.get(task_id)
        if record is None:
            return ToolResult.fail(f"Task not found: {task_id}")
        return ToolResult.ok(_format_record(record, include_output=True))


@dataclass
class TaskOutputTool(_TaskToolBase):
    """Return the full final output of a completed task."""

    name: str = "task_output"
    description: str = (
        "Read the full final response from a background task. For running "
        "tasks, returns the last output line so the agent can poll progress."
    )
    category: ToolCategory = ToolCategory.AGENT
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                },
                "required": ["task_id"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        mgr = self._require_manager()
        if mgr is None:
            return ToolResult.fail(
                "Background tasks are not available in this session."
            )
        task_id = arguments.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            return ToolResult.fail("'task_id' is required.")
        record = mgr.get(task_id)
        if record is None:
            return ToolResult.fail(f"Task not found: {task_id}")

        if record.state in (TaskState.DONE, TaskState.FAILED, TaskState.CANCELLED):
            body = record.result or record.error or "(no output)"
            return ToolResult.ok(
                body,
                state=record.state.value,
                turns=record.turns,
            )
        # Still running — return progress snapshot.
        snapshot = record.last_output or "(no output yet)"
        return ToolResult.ok(
            f"[{record.state.value}] {snapshot}",
            state=record.state.value,
        )


@dataclass
class TaskStopTool(_TaskToolBase):
    """Cancel a running or queued background task."""

    name: str = "task_stop"
    description: str = (
        "Cancel a queued or running background task. Completed tasks are "
        "left untouched."
    )
    category: ToolCategory = ToolCategory.AGENT
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                },
                "required": ["task_id"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        mgr = self._require_manager()
        if mgr is None:
            return ToolResult.fail(
                "Background tasks are not available in this session."
            )
        task_id = arguments.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            return ToolResult.fail("'task_id' is required.")
        ok = await mgr.stop(task_id)
        if not ok:
            return ToolResult.fail(
                f"Task {task_id} is not running or does not exist."
            )
        return ToolResult.ok(f"Cancellation requested for task {task_id}.")


@dataclass
class TaskUpdateTool(_TaskToolBase):
    """Update the title or prompt of a still-queued task."""

    name: str = "task_update"
    description: str = (
        "Update mutable fields on a still-queued background task. Once a "
        "task has started running, only its title remains visible to the "
        "operator but the prompt is frozen."
    )
    category: ToolCategory = ToolCategory.AGENT
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "title": {"type": "string"},
                    "prompt": {"type": "string"},
                },
                "required": ["task_id"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        mgr = self._require_manager()
        if mgr is None:
            return ToolResult.fail(
                "Background tasks are not available in this session."
            )
        task_id = arguments.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            return ToolResult.fail("'task_id' is required.")
        title = arguments.get("title")
        prompt = arguments.get("prompt")
        if title is None and prompt is None:
            return ToolResult.fail("Provide at least one of 'title' or 'prompt'.")
        ok = await mgr.update(task_id, title=title, prompt=prompt)
        if not ok:
            return ToolResult.fail(
                f"Task {task_id} not found or already started — cannot update."
            )
        return ToolResult.ok(f"Task {task_id} updated.")
