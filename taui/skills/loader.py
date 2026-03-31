"""Load a skill from a directory."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass(slots=True)
class SkillDefinition:
    """A loaded skill."""

    name: str
    instructions: str
    description: str = ""
    schema: dict[str, Any] | None = None
    examples: list[str] = field(default_factory=list)
    source_dir: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description or self.name,
            "has_schema": self.schema is not None,
            "num_examples": len(self.examples),
        }
        return d


def load_skill(skill_dir: Path) -> SkillDefinition:
    """Load a skill from *skill_dir*.

    Expects at minimum a SKILL.md file.
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"Missing SKILL.md in {skill_dir}")

    instructions = skill_md.read_text(encoding="utf-8")

    # Extract description from the first non-empty, non-heading line
    description = ""
    for line in instructions.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            description = stripped[:200]
            break

    # Optional schema
    schema: dict[str, Any] | None = None
    schema_path = skill_dir / "schema.json"
    if schema_path.is_file():
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception:
            log.warning("Failed to parse schema.json in %s", skill_dir)

    # Optional examples
    examples: list[str] = []
    examples_dir = skill_dir / "examples"
    if examples_dir.is_dir():
        for ex_file in sorted(examples_dir.glob("*.md")):
            examples.append(ex_file.read_text(encoding="utf-8"))

    return SkillDefinition(
        name=skill_dir.name,
        instructions=instructions,
        description=description,
        schema=schema,
        examples=examples,
        source_dir=skill_dir,
    )
