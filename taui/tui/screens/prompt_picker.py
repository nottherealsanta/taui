"""Prompt picker modal screen with fuzzy search."""

from __future__ import annotations

from rich.text import Text

from taui.tui.screens._picker_base import FuzzyPickerScreen

_SUMMARY_MAX = 40


class PromptPickerScreen(FuzzyPickerScreen[object]):
    """Modal for selecting a prompt."""

    DIALOG_WIDTH = 100
    SEARCH_PLACEHOLDER = "Search prompts…"
    TITLE = "Prompts"

    def __init__(self, prompts: list) -> None:
        super().__init__(prompts)

    def render_row(self, item: object) -> Text:
        return _prompt_row(item)

    def item_id(self, item: object) -> str:
        return _get(item, "identifier")

    def match_text(self, item: object) -> list[str]:
        return [_get(item, "label"), _get(item, "summary")]


def _get(obj: object, attr: str) -> str:
    """Get an attribute from a dataclass instance or dict, returning '' if missing."""
    if isinstance(obj, dict):
        return str(obj.get(attr, ""))
    return str(getattr(obj, attr, ""))


def _prompt_row(p: object) -> Text:
    label = _get(p, "label")
    summary = _get(p, "summary")
    scope = _get(p, "scope")
    if len(summary) > _SUMMARY_MAX:
        summary = summary[:_SUMMARY_MAX - 1] + "…"
    text = Text()
    text.append(f"{label:<28s}", style="white")
    text.append(f"  {summary:<{_SUMMARY_MAX}s}", style="dim")
    text.append(f"  {scope}", style="dim")
    return text
