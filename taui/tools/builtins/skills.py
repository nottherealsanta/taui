"""Skills tool — discover, load, and unload skill packages.

The agent uses this tool to browse available skills and load them
into the conversation. Loading a skill injects its SKILL.md content
as a system message, expanding the agent's capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from taui.skills import SkillRegistry
from taui.tools.base import ToolCategory, ToolResult


@dataclass
class SkillsTool:
    """Discover, load, and unload skill packages.

    Skills are reusable capability bundles found in .taui/skills/ (project)
    and ~/.taui/skills/ (global). Each skill has a SKILL.md with instructions
    that get injected into the conversation when loaded.
    """

    name: str = "skills"
    description: str = (
        "Manage skill packages. Operations: list (discover available skills), "
        "load (inject a skill's instructions into the conversation), "
        "unload (remove a loaded skill), status (show loaded skills)."
    )
    category: ToolCategory = ToolCategory.AGENT
    guidelines: str = (
        "Use `skills list` to discover available capabilities. "
        "Load a skill when you need specialized knowledge for a task. "
        "Unload skills when done to free context budget."
    )
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    # Injected by Session.create()
    _skill_registry: SkillRegistry | None = None
    _inject_message: Any = None  # async (content: str) -> None

    def __post_init__(self):
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "description": "Operation: list, load, unload, status.",
                    },
                    "skill": {
                        "type": "string",
                        "description": "Skill name (for load/unload).",
                    },
                },
                "required": ["operation"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        op = arguments.get("operation")
        if not isinstance(op, str):
            return ToolResult.fail(
                "'operation' is required (list, load, unload, status)."
            )

        if self._skill_registry is None:
            return ToolResult.fail("Skill system not configured.")

        match op:
            case "list":
                return self._list()
            case "load":
                return await self._load(arguments)
            case "unload":
                return self._unload(arguments)
            case "status":
                return self._status()
            case _:
                return ToolResult.fail(
                    f"Unknown operation '{op}'. Use: list, load, unload, status."
                )

    def _list(self) -> ToolResult:
        """List all discovered skills."""
        # Re-discover to pick up new skills
        self._skill_registry.discover()
        skills = self._skill_registry.list_all()

        if not skills:
            return ToolResult.ok(
                "No skills found.\n"
                "Skills are directories with a SKILL.md in:\n"
                "  - .taui/skills/<name>/SKILL.md (project)\n"
                "  - ~/.taui/skills/<name>/SKILL.md (global)"
            )

        lines = [f"Available skills ({len(skills)}):"]
        for s in skills:
            status = " [loaded]" if s.loaded else ""
            lines.append(f"  - {s.name} ({s.scope}){status}")
        return ToolResult.ok("\n".join(lines), count=len(skills))

    async def _load(self, arguments: dict[str, Any]) -> ToolResult:
        """Load a skill — inject its SKILL.md into the conversation."""
        skill_name = arguments.get("skill")
        if not isinstance(skill_name, str) or not skill_name.strip():
            return ToolResult.fail("'skill' name is required for load.")

        skill = self._skill_registry.get(skill_name)
        if skill is None:
            available = ", ".join(self._skill_registry.names)
            msg = f"Skill '{skill_name}' not found."
            if available:
                msg += f" Available: {available}"
            return ToolResult.fail(msg)

        if skill.loaded:
            return ToolResult.ok(
                f"Skill '{skill_name}' is already loaded.",
                skill=skill_name,
            )

        content = skill.load_content()
        skill.loaded = True

        # Inject the skill content as a system message
        if self._inject_message:
            await self._inject_message(
                f"[Skill: {skill_name}]\n\n{content}"
            )

        return ToolResult.ok(
            f"Loaded skill '{skill_name}' ({skill.estimated_tokens} tokens).\n\n"
            f"Skill instructions are now active in the conversation.",
            skill=skill_name,
            tokens=skill.estimated_tokens,
        )

    def _unload(self, arguments: dict[str, Any]) -> ToolResult:
        """Mark a skill as unloaded."""
        skill_name = arguments.get("skill")
        if not isinstance(skill_name, str) or not skill_name.strip():
            return ToolResult.fail("'skill' name is required for unload.")

        skill = self._skill_registry.get(skill_name)
        if skill is None:
            return ToolResult.fail(f"Skill '{skill_name}' not found.")

        if not skill.loaded:
            return ToolResult.ok(f"Skill '{skill_name}' is not loaded.")

        skill.loaded = False
        return ToolResult.ok(
            f"Unloaded skill '{skill_name}'. "
            f"Its instructions remain in conversation history but are no longer active.",
            skill=skill_name,
        )

    def _status(self) -> ToolResult:
        """Show currently loaded skills."""
        loaded = self._skill_registry.loaded_skills()
        if not loaded:
            return ToolResult.ok("No skills currently loaded.")

        lines = [f"Loaded skills ({len(loaded)}):"]
        total_tokens = 0
        for s in loaded:
            tokens = s.estimated_tokens
            total_tokens += tokens
            lines.append(f"  - {s.name} (~{tokens} tokens)")
        lines.append(f"Total skill token budget: ~{total_tokens}")
        return ToolResult.ok("\n".join(lines), count=len(loaded))
