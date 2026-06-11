"""Task/TodoWrite tool — in-memory task list for the current session."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from taui.tools.base import ToolCategory, ToolResult


@dataclass
class TaskTool:
    """In-memory task list for tracking multi-step work.

    The agent can create, update, list, and complete tasks.
    Tasks live in memory and last for the duration of the session.
    """

    name: str = "task"
    description: str = (
        "Manage a persistent task list for the current session. "
        "Use to track multi-step work: create tasks, mark them complete, "
        "update status, or list all tasks."
    )
    category: ToolCategory = ToolCategory.AGENT
    schema: dict[str, Any] = field(default=None)
    _tasks: list[dict[str, Any]] = field(default_factory=list, repr=False)

    guidelines: str = (
        "Use the task tool to break down complex work into steps. "
        "Update task status as you complete each step."
    )

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["list", "add", "update", "complete", "remove", "clear"],
                        "description": (
                            "Operation: list, add (create a task), "
                            "update (change status/priority/notes/title), "
                            "complete (mark done), remove (delete one), clear (remove all)."
                        ),
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Task ID (for update/complete/remove).",
                    },
                    "title": {
                        "type": "string",
                        "description": "Task title (for add).",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "cancelled"],
                        "description": "Task status (for update).",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "Task priority (for add/update).",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Additional notes (for add/update).",
                    },
                },
                "required": ["operation"],
            }

    def _next_id(self) -> str:
        if not self._tasks:
            return "1"
        max_id = max(int(t.get("id", 0)) for t in self._tasks)
        return str(max_id + 1)

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        op = arguments.get("operation", "list")

        if op == "list":
            return self._list_tasks()
        elif op == "add":
            return self._add_task(arguments)
        elif op == "update":
            return self._update_task(arguments)
        elif op == "complete":
            return self._complete_task(arguments)
        elif op == "remove":
            return self._remove_task(arguments)
        elif op == "clear":
            return self._clear_tasks()
        else:
            return ToolResult.fail(
                f"Unknown operation '{op}'. "
                "Use: list, add, update, complete, remove, clear."
            )

    def _list_tasks(self) -> ToolResult:
        if not self._tasks:
            return ToolResult.ok("No tasks. Use operation='add' to create one.")

        lines = ["# Tasks\n"]
        for t in self._tasks:
            status_icon = {
                "pending": "⬜",
                "in_progress": "🔄",
                "completed": "✅",
                "cancelled": "❌",
            }.get(t.get("status", "pending"), "⬜")
            priority = t.get("priority", "medium")
            line = f"{status_icon} [{t['id']}] {t['title']} ({priority})"
            if t.get("notes"):
                line += f"\n   {t['notes']}"
            lines.append(line)

        return ToolResult.ok("\n".join(lines))

    def _add_task(self, args: dict[str, Any]) -> ToolResult:
        title = args.get("title")
        if not title:
            return ToolResult.fail("'title' is required for add.")

        task = {
            "id": self._next_id(),
            "title": title,
            "status": "pending",
            "priority": args.get("priority", "medium"),
            "notes": args.get("notes", ""),
        }
        self._tasks.append(task)
        return ToolResult.ok(f"Task #{task['id']} added: {title}")

    def _update_task(self, args: dict[str, Any]) -> ToolResult:
        task_id = args.get("task_id")
        if not task_id:
            return ToolResult.fail("'task_id' is required for update.")

        for t in self._tasks:
            if t["id"] == task_id:
                if "status" in args:
                    t["status"] = args["status"]
                if "priority" in args:
                    t["priority"] = args["priority"]
                if "notes" in args:
                    t["notes"] = args["notes"]
                if "title" in args:
                    t["title"] = args["title"]
                return ToolResult.ok(f"Task #{task_id} updated.")

        return ToolResult.fail(f"Task #{task_id} not found.")

    def _complete_task(self, args: dict[str, Any]) -> ToolResult:
        task_id = args.get("task_id")
        if not task_id:
            return ToolResult.fail("'task_id' is required for complete.")

        for t in self._tasks:
            if t["id"] == task_id:
                t["status"] = "completed"
                return ToolResult.ok(f"Task #{task_id} completed: {t['title']}")

        return ToolResult.fail(f"Task #{task_id} not found.")

    def _remove_task(self, args: dict[str, Any]) -> ToolResult:
        task_id = args.get("task_id")
        if not task_id:
            return ToolResult.fail("'task_id' is required for remove.")

        original_count = len(self._tasks)
        self._tasks = [t for t in self._tasks if t["id"] != task_id]
        if len(self._tasks) == original_count:
            return ToolResult.fail(f"Task #{task_id} not found.")

        return ToolResult.ok(f"Task #{task_id} removed.")

    def _clear_tasks(self) -> ToolResult:
        self._tasks.clear()
        return ToolResult.ok("All tasks cleared.")
