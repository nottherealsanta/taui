"""Skill picker modal screen with fuzzy search."""

from __future__ import annotations

from rich.text import Text

from taui.skills import Skill
from taui.tui.screens._picker_base import FuzzyPickerScreen


class SkillPickerScreen(FuzzyPickerScreen[Skill]):
    """Modal for selecting a skill."""

    SEARCH_PLACEHOLDER = "Search skills…"
    TITLE = "Skills"

    def __init__(self, skills: list[Skill]) -> None:
        super().__init__(skills)

    def render_row(self, item: Skill) -> Text:
        return _skill_prompt(item)

    def item_id(self, item: Skill) -> str:
        return item.name

    def match_text(self, item: Skill) -> list[str]:
        return [item.name]


def _skill_prompt(skill: Skill) -> Text:
    marker = " ◀" if skill.loaded else ""
    text = Text()
    text.append(f"{skill.name:<30s}", style="bold" if skill.loaded else "white")
    text.append(f"  {skill.scope}{marker}", style="dim")
    return text
