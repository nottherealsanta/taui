"""Plan tool — manage plan files for multi-step workflows."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taui.tools.base import ToolCategory, ToolContext, ToolResult
from taui.tools.builtins._common import normalize_tool_error


@dataclass(slots=True)
class PlanTool:
    """Create and manage plan files for complex multi-step workflows."""

    name: str = "plan"
    description: str = (
        "Manage plan files for multi-step workflows. Operations: "
        "'create' a new plan, 'read' current plan, 'update' plan steps, "
        "'complete' a plan. Plans are saved as markdown in .taui/plans/."
    )
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.PLAN

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "description": "create, read, update, or complete",
                    },
                    "title": {
                        "type": "string",
                        "description": "Plan title (for create/update)",
                    },
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "step": {"type": "string"},
                                "done": {"type": "boolean"},
                            },
                            "required": ["step"],
                        },
                        "description": "Array of plan steps",
                    },
                    "plan_id": {
                        "type": "string",
                        "description": "Plan identifier (defaults to current session plan)",
                    },
                },
                "required": ["operation"],
            }

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        operation = arguments.get("operation")
        if operation not in ("create", "read", "update", "complete"):
            return normalize_tool_error(
                "Invalid plan operation. Must be: create, read, update, or complete."
            )

        plan_dir = context.working_dir / ".taui" / "plans"
        plan_id = arguments.get("plan_id")
        if not isinstance(plan_id, str) or not plan_id:
            plan_id = context.session_id or "default"
        plan_path = plan_dir / f"{plan_id}.md"

        if operation == "create":
            return await self._create(plan_path, arguments, plan_dir)
        elif operation == "read":
            return await self._read(plan_path)
        elif operation == "update":
            return await self._update(plan_path, arguments)
        else:  # complete
            return await self._complete(plan_path)

    async def _create(
        self, plan_path: Path, arguments: dict[str, Any], plan_dir: Path
    ) -> ToolResult:
        title = arguments.get("title", "Plan")
        steps = arguments.get("steps", [])

        plan_dir.mkdir(parents=True, exist_ok=True)
        content = _render_plan(title, steps)
        plan_path.write_text(content, encoding="utf-8")

        return ToolResult.ok(
            f"Plan created at {plan_path}\n\n{content}",
            metadata={"plan_path": str(plan_path), "steps": len(steps)},
        )

    async def _read(self, plan_path: Path) -> ToolResult:
        if not plan_path.exists():
            return normalize_tool_error(f"No plan found at {plan_path}.")
        content = plan_path.read_text(encoding="utf-8")
        return ToolResult.ok(content, metadata={"plan_path": str(plan_path)})

    async def _update(
        self, plan_path: Path, arguments: dict[str, Any]
    ) -> ToolResult:
        if not plan_path.exists():
            return normalize_tool_error(f"No plan found at {plan_path}. Create one first.")

        title = arguments.get("title")
        steps = arguments.get("steps")

        if title is None:
            # Read existing title
            existing = plan_path.read_text(encoding="utf-8")
            first_line = existing.split("\n")[0]
            title = first_line.lstrip("# ").strip() if first_line.startswith("#") else "Plan"

        if steps is None:
            return normalize_tool_error("'steps' required for update operation.")

        content = _render_plan(title, steps)
        plan_path.write_text(content, encoding="utf-8")

        return ToolResult.ok(
            f"Plan updated at {plan_path}\n\n{content}",
            metadata={"plan_path": str(plan_path), "steps": len(steps)},
        )

    async def _complete(self, plan_path: Path) -> ToolResult:
        if not plan_path.exists():
            return normalize_tool_error(f"No plan found at {plan_path}.")

        content = plan_path.read_text(encoding="utf-8")
        # Mark all steps as done
        updated = content.replace("- [ ]", "- [x]")
        updated += f"\n\n---\n_Completed at {time.strftime('%Y-%m-%d %H:%M:%S')}_\n"
        plan_path.write_text(updated, encoding="utf-8")

        return ToolResult.ok(
            f"Plan completed at {plan_path}",
            metadata={"plan_path": str(plan_path)},
        )


def _render_plan(title: str, steps: list[dict[str, Any]]) -> str:
    """Render a plan as markdown."""
    lines = [f"# {title}", ""]
    for i, step in enumerate(steps, 1):
        text = step.get("step", f"Step {i}")
        done = step.get("done", False)
        checkbox = "[x]" if done else "[ ]"
        lines.append(f"- {checkbox} {text}")
    lines.append("")
    return "\n".join(lines)
