"""Skill registry — discovers and stores skills from multiple directories."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from taui.skills.loader import SkillDefinition, load_skill

log = logging.getLogger(__name__)


@dataclass(slots=True)
class SkillRegistry:
    """Maintains a set of loaded skills by name."""

    _skills: dict[str, SkillDefinition] = field(default_factory=dict)

    def register(self, skill: SkillDefinition) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> SkillDefinition | None:
        return self._skills.get(name)

    def list_skills(self) -> list[SkillDefinition]:
        return list(self._skills.values())

    def names(self) -> list[str]:
        return sorted(self._skills.keys())

    def scan_directory(self, base_dir: Path) -> int:
        """Discover skills in *base_dir*.

        Each immediate subdirectory containing SKILL.md is treated as a skill.
        Returns the number of skills loaded.
        """
        if not base_dir.is_dir():
            return 0
        count = 0
        for child in sorted(base_dir.iterdir()):
            if child.is_dir() and (child / "SKILL.md").is_file():
                try:
                    skill = load_skill(child)
                    self.register(skill)
                    count += 1
                except Exception:
                    log.warning("Failed to load skill from %s", child, exc_info=True)
        return count

    def scan_project(self, project_root: Path) -> int:
        """Scan all standard skill locations in a project.

        Looks in:
          .taui/skills/
          skills/
        """
        total = 0
        for subdir in [".taui/skills", "skills"]:
            total += self.scan_directory(project_root / subdir)
        return total
