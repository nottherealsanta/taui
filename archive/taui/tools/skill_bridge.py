"""Skill bridge — wraps a SkillDefinition as a Tool.

When a skill has a ``schema``, it can be exposed directly as a tool
rather than requiring the user to go through ``skill invoke``.
This is the claw-code pattern of making skills first-class tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from taui.skills.loader import SkillDefinition
from taui.tools.base import ToolCategory, ToolContext, ToolResult


@dataclass(slots=True)
class SkillBridgeTool:
    """Wraps a SkillDefinition as a Tool.

    The tool's schema comes from the skill's ``schema.json``.
    Executing the tool returns the skill's instructions (the content
    of SKILL.md) — the agent then follows those instructions.
    """

    skill: SkillDefinition
    name: str = ""
    description: str = ""
    schema: dict[str, Any] = field(default_factory=dict)
    origin: str = ""
    category: ToolCategory = ToolCategory.SKILL

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"skill_{self.skill.name}"
        if not self.description:
            self.description = self.skill.description or f"Skill: {self.skill.name}"
        if not self.schema:
            self.schema = self.skill.schema or {
                "type": "object",
                "properties": {},
            }
        if not self.origin:
            self.origin = f"skill:{self.skill.name}"

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        """Return the skill's instructions for the agent to follow."""
        # The arguments are passed through as context but the primary
        # output is the instructions themselves.
        sections = [self.skill.instructions]

        if arguments:
            import json

            sections.append(
                f"\n## Provided arguments\n```json\n{json.dumps(arguments, indent=2)}\n```"
            )

        if self.skill.examples:
            sections.append("\n## Examples")
            for i, example in enumerate(self.skill.examples, 1):
                sections.append(f"### Example {i}\n{example}")

        return ToolResult.ok("\n".join(sections))
