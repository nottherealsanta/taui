"""Skills system — discoverable, reusable prompt packs.

A skill is a directory with:
  SKILL.md   — instructions (required)
  schema.json — optional JSON Schema for input parameters
  examples/  — optional example prompts
"""

from taui.skills.loader import SkillDefinition, load_skill
from taui.skills.registry import SkillRegistry

__all__ = ["SkillDefinition", "SkillRegistry", "load_skill"]
