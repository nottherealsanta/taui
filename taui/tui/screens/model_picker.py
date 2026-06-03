"""Model picker modal screen with fuzzy search."""

from __future__ import annotations

from rich.text import Text

from taui.tui.screens._picker_base import FuzzyPickerScreen


class ModelPickerScreen(FuzzyPickerScreen[dict]):
    """Modal for selecting a model in the current provider."""

    SEARCH_PLACEHOLDER = "Search models…"

    def __init__(self, provider: str, models: list[dict], *, current: str) -> None:
        super().__init__(models)
        self._provider = provider
        self._current = current
        self.TITLE = f"Models · {provider}"

    def render_row(self, item: dict) -> Text:
        return _model_prompt(item, current=self._current)

    def item_id(self, item: dict) -> str:
        return str(item["id"])

    def match_text(self, item: dict) -> list[str]:
        return [str(item["id"])]


def _model_prompt(model: dict, *, current: str) -> Text:
    model_id = str(model.get("id", ""))
    context = int(model.get("context", 0) or 0)
    ctx = f"{context // 1000}k" if context else "?"
    reasoning = " reasoning" if model.get("reasoning") else ""
    marker = " ◀" if model_id == current else ""

    text = Text()
    text.append(f"{model_id:<45s}", style="bold" if marker else "default")
    text.append(f"  {ctx:>6s} ctx{reasoning}{marker}", style="dim")
    return text
