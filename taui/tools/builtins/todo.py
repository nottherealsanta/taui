"""TodoWrite tool — structured task tracking for agent sessions."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from taui.tools.base import ToolCategory, ToolContext, ToolResult
from taui.tools.builtins._common import normalize_tool_error

_VALID_STATUSES = {"not-started", "in-progress", "completed"}


@dataclass(slots=True)
class TodoWriteTool:
    """Manage a structured todo list scoped to the agent session."""

    name: str = "todowrite"
    description: str = (
        "Create or update a structured todo list to track progress. Provide "
        "the complete array of all todo items (both existing and new). Each item "
        "has id, title, and status (not-started, in-progress, completed). "
        "Mark only one item as in-progress at a time. Mark completed immediately "
        "after finishing — do not batch completions."
    )
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.PLAN

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "integer",
                                    "description": "Unique identifier (sequential from 1)",
                                },
                                "title": {
                                    "type": "string",
                                    "description": "Concise action-oriented label (3-7 words)",
                                },
                                "status": {
                                    "type": "string",
                                    "description": "not-started | in-progress | completed",
                                },
                            },
                            "required": ["id", "title", "status"],
                        },
                        "description": "Complete array of all todo items",
                    },
                },
                "required": ["todos"],
            }

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        todos = arguments.get("todos")
        if not isinstance(todos, list):
            return normalize_tool_error(
                "Invalid todowrite arguments: 'todos' must be an array."
            )

        # Validate todos
        validated: list[dict[str, Any]] = []
        in_progress_count = 0
        for i, item in enumerate(todos):
            if not isinstance(item, dict):
                return normalize_tool_error(f"Todo #{i} is not an object.")
            todo_id = item.get("id")
            title = item.get("title")
            status = item.get("status")
            if not isinstance(todo_id, int):
                return normalize_tool_error(f"Todo #{i}: 'id' must be an integer.")
            if not isinstance(title, str) or not title.strip():
                return normalize_tool_error(f"Todo #{i}: 'title' must be a non-empty string.")
            if status not in _VALID_STATUSES:
                return normalize_tool_error(
                    f"Todo #{i}: 'status' must be one of {_VALID_STATUSES}."
                )
            if status == "in-progress":
                in_progress_count += 1
            validated.append({
                "id": todo_id,
                "title": title.strip(),
                "status": status,
                "updated_at": time.time(),
            })

        # Store in session for persistence
        if hasattr(context.session, "set_todos"):
            context.session.set_todos(validated)

        # Emit via metadata callback if available
        if context.metadata_callback:
            context.metadata_callback({"todos": validated})

        # Build output
        lines: list[str] = []
        for t in validated:
            icon = {"not-started": "○", "in-progress": "◐", "completed": "●"}[t["status"]]
            lines.append(f"  {icon} [{t['id']}] {t['title']}")

        completed = sum(1 for t in validated if t["status"] == "completed")
        total = len(validated)
        output = f"Todo list ({completed}/{total} completed):\n" + "\n".join(lines)

        warnings: list[str] = []
        if in_progress_count > 1:
            warnings.append(
                f"Warning: {in_progress_count} items are in-progress. Limit to 1."
            )
        if warnings:
            output += "\n\n" + "\n".join(warnings)

        return ToolResult.ok(
            output,
            metadata={
                "todos": validated,
                "completed": completed,
                "total": total,
            },
        )
