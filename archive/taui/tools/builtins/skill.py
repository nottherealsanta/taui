"""SkillTool — list and invoke skills."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from taui.skills.registry import SkillRegistry
from taui.tools.base import ToolCategory, ToolContext, ToolResult


@dataclass(slots=True)
class SkillTool:
    name: str = "skill"
    description: str = (
        "List and invoke available skills — reusable prompt packs that provide "
        "specialized instructions for particular tasks.\n\n"
        "Operations:\n"
        "  list — show all available skills and their descriptions\n"
        "  invoke — load a skill's instructions for use in the current task\n\n"
        "Parameters:\n"
        "  operation (required): 'list' or 'invoke'\n"
        "  skill_name: name of the skill to invoke (required for invoke)"
    )
    schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["list", "invoke"],
                "description": "Operation to perform.",
            },
            "skill_name": {
                "type": "string",
                "description": "Name of the skill to invoke.",
            },
        },
        "required": ["operation"],
        "additionalProperties": False,
    })
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.SKILL
    _registry: SkillRegistry | None = None

    def set_registry(self, registry: SkillRegistry) -> None:
        self._registry = registry

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        registry = self._registry
        if registry is None:
            # Auto-create and scan
            registry = SkillRegistry()
            registry.scan_project(context.working_dir)
            self._registry = registry

        op = arguments.get("operation", "")

        if op == "list":
            skills = registry.list_skills()
            if not skills:
                return ToolResult.ok(
                    "No skills available. Skills can be added to .taui/skills/ or skills/ directories."
                )
            lines = []
            for s in skills:
                lines.append(f"  {s.name}: {s.description}")
            return ToolResult.ok("Available skills:\n" + "\n".join(lines))

        elif op == "invoke":
            name = arguments.get("skill_name", "")
            if not name:
                return ToolResult.fail("skill_name is required for invoke.")
            skill = registry.get(name)
            if skill is None:
                return ToolResult.fail(
                    f"Skill '{name}' not found. Available: {', '.join(registry.names())}"
                )
            return ToolResult.ok(skill.instructions)

        return ToolResult.fail(f"Unknown operation: {op}")
