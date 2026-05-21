"""Theme picker modal screen.

Only the curated taui themes are exposed — switching to other Textual
themes currently breaks the app's styling.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option


THEMES: list[tuple[str, str]] = [
    ("taui-dark", "Taui Dark"),
    ("taui-light", "Taui Light"),
]


class ThemePickerScreen(ModalScreen[str | None]):
    """Modal for selecting one of the taui themes."""

    DEFAULT_CSS = """
    ThemePickerScreen {
        align: center middle;
        background: $background 70%;
    }
    #theme-picker-dialog {
        width: 60;
        max-width: 90%;
        height: auto;
        background: #0d0d0d;
        border: round #2a2a2a;
        padding: 1 2;
    }
    #theme-picker-dialog .dialog-title {
        width: 100%;
        content-align: center middle;
        padding: 0 0 1 0;
        color: #c8c8c8;
        text-style: bold;
    }
    #theme-picker-dialog OptionList {
        height: auto;
        max-height: 12;
        background: #121212;
        border: solid #2a2a2a;
        color: #c8c8c8;
    }
    #theme-picker-dialog OptionList:focus {
        border: solid #5a5a5a;
    }
    #theme-picker-dialog .option-list--option-highlighted {
        background: #2a2a2a;
        color: #e8e8e8;
        text-style: bold;
    }
    #theme-picker-dialog .hint {
        padding: 1 0 0 0;
        color: #707070;
    }
    """

    def __init__(self, current: str) -> None:
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        with Container(id="theme-picker-dialog"):
            yield Label("Theme", classes="dialog-title")
            yield OptionList(
                *[
                    Option(_render(key, label, current=self._current), id=key)
                    for key, label in THEMES
                ],
                id="theme-options",
            )
            yield Label("Enter to select, Esc to cancel", classes="hint")

    def on_mount(self) -> None:
        options = self.query_one("#theme-options", OptionList)
        for i, (key, _) in enumerate(THEMES):
            if key == self._current:
                options.highlighted = i
                break
        options.focus()

    @on(OptionList.OptionSelected)
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id or THEMES[event.option_index][0]
        self.dismiss(str(option_id))

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)


def _render(key: str, label: str, *, current: str) -> str:
    marker = "  ◀" if key == current else ""
    return f"{label}{marker}"
