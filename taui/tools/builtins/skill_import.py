"""SkillImportTool — install skills from external sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taui.skills.installer import install_from_directory, install_from_git
from taui.skills.loader import load_skill
from taui.skills.registry import SkillRegistry
from taui.tools.base import ToolCategory, ToolContext, ToolResult


@dataclass(slots=True)
class SkillImportTool:
    name: str = "skill_import"
    description: str = (
        "Import a skill from a local directory or a git repository.\n\n"
        "Parameters:\n"
        "  source: local directory path OR git repo URL\n"
        "  skill_path: path within the git repo to the skill directory "
        "(required when source is a git URL)"
    )
    schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "Local directory path or git repository URL.",
            },
            "skill_path": {
                "type": "string",
                "description": "Path within the git repo to the skill dir.",
            },
        },
        "required": ["source"],
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
        source = arguments.get("source", "")
        skill_path = arguments.get("skill_path", "")

        target_dir = context.working_dir / ".taui" / "skills"
        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            if source.startswith(("http://", "https://", "git@")):
                if not skill_path:
                    return ToolResult.fail(
                        "skill_path is required when importing from a git URL."
                    )
                dest = await install_from_git(source, skill_path, target_dir)
            else:
                local = Path(source)
                if not local.is_absolute():
                    local = context.working_dir / local
                local = local.resolve()
                if not local.is_dir():
                    return ToolResult.fail(f"Source directory not found: {local}")
                dest = await install_from_directory(local, target_dir)

            # Load and register
            skill = load_skill(dest)
            if self._registry:
                self._registry.register(skill)

            return ToolResult.ok(
                f"Skill '{skill.name}' installed to {dest}\n"
                f"Description: {skill.description}"
            )
        except Exception as exc:
            return ToolResult.fail(f"Import failed: {exc}")
