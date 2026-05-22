"""Model variant picker — reasoning effort / thinking level.

The list of variants offered is per-model (see
``taui.llm_provider.models.compute_variants``). The screen always prepends an
empty "(default)" entry that clears the variant.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

_LABELS: dict[str, str] = {
    "none": "None",
    "minimal": "Minimal",
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "xhigh": "Extra-high",
    "max": "Max",
}


class VariantPickerScreen(ModalScreen[str | None]):
    """Modal for selecting a model variant."""

    DEFAULT_CSS = """
    VariantPickerScreen {
        align: center middle;
        background: $background 70%;
    }
    #variant-picker-dialog {
        width: 60;
        max-width: 90%;
        height: auto;
        background: #0d0d0d;
        border: round #2a2a2a;
        padding: 1 2;
    }
    #variant-picker-dialog .dialog-title {
        width: 100%;
        content-align: center middle;
        padding: 0 0 1 0;
        color: #c8c8c8;
        text-style: bold;
    }
    #variant-picker-dialog OptionList {
        height: auto;
        max-height: 12;
        background: #121212;
        border: solid #2a2a2a;
        color: #c8c8c8;
    }
    #variant-picker-dialog OptionList:focus {
        border: solid #5a5a5a;
    }
    #variant-picker-dialog .option-list--option-highlighted {
        background: #2a2a2a;
        color: #e8e8e8;
        text-style: bold;
    }
    #variant-picker-dialog .hint {
        padding: 1 0 0 0;
        color: #707070;
    }
    """

    # Sentinel option id for the empty-string ("") variant — OptionList
    # treats "" as missing.
    _CLEAR_ID = "__clear__"

    def __init__(
        self,
        variants: list[str],
        *,
        current: str,
        model: str = "",
    ) -> None:
        super().__init__()
        self._variants = list(variants)
        self._current = current
        self._model = model

    def _entries(self) -> list[tuple[str, str]]:
        # Always lead with the clear / default option.
        entries: list[tuple[str, str]] = [("", "(default — no variant)")]
        for v in self._variants:
            entries.append((v, _LABELS.get(v, v.title())))
        return entries

    def compose(self) -> ComposeResult:
        with Container(id="variant-picker-dialog"):
            title = "Model variant"
            if self._model:
                title = f"Model variant — {self._model}"
            yield Label(title, classes="dialog-title")
            yield OptionList(
                *[
                    Option(
                        _render(key, label, current=self._current),
                        id=key or self._CLEAR_ID,
                    )
                    for key, label in self._entries()
                ],
                id="variant-options",
            )
            yield Label("Enter to select, Esc to cancel", classes="hint")

    def on_mount(self) -> None:
        options = self.query_one("#variant-options", OptionList)
        for i, (key, _) in enumerate(self._entries()):
            if key == self._current:
                options.highlighted = i
                break
        options.focus()

    @on(OptionList.OptionSelected)
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        entries = self._entries()
        option_id = event.option_id or (
            entries[event.option_index][0] or self._CLEAR_ID
        )
        self.dismiss("" if option_id == self._CLEAR_ID else str(option_id))

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)


def _render(key: str, label: str, *, current: str) -> str:
    marker = "  ◀" if key == current else ""
    return f"{label}{marker}"
