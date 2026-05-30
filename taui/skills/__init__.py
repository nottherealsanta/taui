"""
taui.skills — skill discovery, loading, and management.

Skills are reusable capability bundles that extend what the agent can do.
Each skill is a directory containing a SKILL.md with instructions.

Skills follow the Agent Skills open standard (agentskills.io).

Discovery order (later entries override earlier for same-named skills):

  Global:
    ~/.config/agents/skills/<name>/SKILL.md  — Agent Skills standard (XDG)
    ~/.taui/skills/<name>/SKILL.md           — taui-native

  Project:
    .agents/skills/<name>/SKILL.md           — Agent Skills standard
    .taui/skills/<name>/SKILL.md             — taui-native

Loading a skill injects its instructions into the agent's conversation
as a system message, expanding the agent's capabilities mid-session.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from taui.skills.installer import (
    InstallResult,
    SkillInstallError,
    SkillSource,
    install,
    looks_like_skill_source,
    parse_source,
    parse_sources,
)

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_SKILL_CHARS",
    "InstallResult",
    "Skill",
    "SkillInstallError",
    "SkillRegistry",
    "SkillSource",
    "install",
    "looks_like_skill_source",
    "parse_source",
    "parse_sources",
]

MAX_SKILL_CHARS = 8_000


@dataclass(slots=True)
class Skill:
    """A discovered skill package."""

    name: str
    path: Path            # Directory containing SKILL.md
    scope: str            # "global" or "project"
    content: str = ""     # SKILL.md content (loaded lazily)
    loaded: bool = False  # Whether injected into conversation

    @property
    def skill_file(self) -> Path:
        return self.path / "SKILL.md"

    @property
    def estimated_tokens(self) -> int:
        return max(1, len(self.content) // 4)

    def load_content(self) -> str:
        """Read SKILL.md content from disk."""
        if not self.content:
            try:
                raw = self.skill_file.read_text(encoding="utf-8")
                if len(raw) > MAX_SKILL_CHARS:
                    raw = raw[:MAX_SKILL_CHARS] + "\n\n[skill content truncated]"
                self.content = raw
            except OSError as e:
                logger.warning("Failed to read skill %s: %s", self.name, e)
                self.content = f"(Error reading skill: {e})"
        return self.content


class SkillRegistry:
    """Discovers and manages available skills.

    Scans global and project skill directories for skill packages.
    Supports both the Agent Skills standard (.agents/skills/) and
    taui-native (.taui/skills/) paths. Later directories override
    earlier ones for same-named skills.
    """

    # Global skill directories, scanned in order (later overrides earlier).
    GLOBAL_DIRS = (
        Path.home() / ".config" / "agents" / "skills",  # Agent Skills / XDG
        Path.home() / ".taui" / "skills",                # taui-native
    )

    # Project skill directory names, relative to working_dir.
    PROJECT_DIRS = (
        ".agents/skills",   # Agent Skills standard
        ".taui/skills",     # taui-native
    )

    def __init__(self, working_dir: Path) -> None:
        self._working_dir = working_dir
        self._skills: dict[str, Skill] = {}

    def discover(self) -> None:
        """Scan skill directories and populate the registry."""
        self._skills.clear()

        # Global skills
        for global_dir in self.GLOBAL_DIRS:
            self._scan_dir(global_dir, scope="global")

        # Project skills (override global)
        for rel in self.PROJECT_DIRS:
            project_dir = self._working_dir / rel
            self._scan_dir(project_dir, scope="project")

    def _scan_dir(self, base: Path, scope: str) -> None:
        """Scan a directory for skill packages."""
        if not base.is_dir():
            return
        for entry in sorted(base.iterdir()):
            if not entry.is_dir():
                continue
            skill_file = entry / "SKILL.md"
            if not skill_file.is_file():
                continue
            name = entry.name
            self._skills[name] = Skill(
                name=name,
                path=entry,
                scope=scope,
            )

    @property
    def names(self) -> list[str]:
        return sorted(self._skills)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list_all(self) -> list[Skill]:
        return [self._skills[n] for n in self.names]

    def loaded_skills(self) -> list[Skill]:
        return [s for s in self._skills.values() if s.loaded]

    def add_from_path(self, path: Path, *, scope: str = "extension") -> None:
        """Add a skill from an explicit path.

        Accepts either a plain ``.md`` file or a directory containing
        ``SKILL.md``.  Used by extensions that bundle prompt assets.
        """
        path = path.resolve()
        if path.is_file() and path.suffix == ".md":
            name = path.stem
            try:
                raw = path.read_text(encoding="utf-8")
                if len(raw) > MAX_SKILL_CHARS:
                    raw = raw[:MAX_SKILL_CHARS] + "\n\n[skill content truncated]"
                content = raw
            except OSError as e:
                logger.warning("Failed to read skill %s: %s", name, e)
                content = f"(Error reading skill: {e})"
            self._skills[name] = Skill(
                name=name, path=path.parent, scope=scope, content=content
            )
        elif path.is_dir() and (path / "SKILL.md").is_file():
            self._skills[path.name] = Skill(name=path.name, path=path, scope=scope)
        else:
            logger.warning("Cannot load skill from %s: not a .md file or SKILL.md directory", path)
