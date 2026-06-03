"""Modal screen for viewing/editing a pasted-text attachment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, Label, TextArea

PasteResultAction = Literal["save", "insert"]


@dataclass(frozen=True, slots=True)
class PasteResult:
    """What the modal returned to the host app.

    `action="save"` updates the attachment text in place.
    `action="insert"` removes the attachment and inlines the text into the
    chat input at the cursor.
    `None` (no result) is dismiss/cancel.
    """

    action: PasteResultAction
    text: str


class PastedContentScreen(ModalScreen[PasteResult | None]):
    """View and edit pasted content, then save or insert into the input."""

    DEFAULT_CSS = """
    PastedContentScreen {
        align: center middle;
        background: $taui-scrim;
    }
    #pasted-dialog {
        width: 80%;
        height: 80%;
        background: $surface;
        border: thick $taui-border-subtle;
        padding: 1;
    }
    #pasted-dialog .dialog-title {
        width: 1fr;
        color: $primary;
        text-style: bold;
    }
    #pasted-dialog .header-row {
        width: 100%;
        height: 1;
        padding: 0 0 1 0;
    }
    #pasted-dialog .footer-row {
        width: 100%;
        height: 1;
        margin: 1 0 0 0;
        align-horizontal: right;
    }
    #pasted-dialog .footer-row Button {
        margin: 0 0 0 1;
        height: 1;
        min-width: 0;
        border: none;
        padding: 0 1;
    }
    #pasted-content-area {
        height: 1fr;
        width: 100%;
        border: solid $taui-border-subtle;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
    ]

    def __init__(self, text: str, *, index: int) -> None:
        super().__init__()
        self._initial_text = text
        self._index = index

    def compose(self) -> ComposeResult:
        line_count = self._initial_text.count("\n") + 1
        title = f"Pasted content ({line_count} lines)"
        with Container(id="pasted-dialog"):
            with Horizontal(classes="header-row"):
                yield Label(title, classes="dialog-title")
            yield TextArea(self._initial_text, id="pasted-content-area")
            with Horizontal(classes="footer-row"):
                yield Button("Cancel", id="paste-cancel")
                yield Button(
                    "Insert as text", id="paste-insert", variant="default"
                )
                yield Button("Save", id="paste-save", variant="primary")

    def on_mount(self) -> None:
        try:
            area = self.query_one("#pasted-content-area", TextArea)
            area.focus()
        except Exception:
            pass

    def _current_text(self) -> str:
        try:
            return self.query_one("#pasted-content-area", TextArea).text
        except Exception:
            return self._initial_text

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self.dismiss(PasteResult(action="save", text=self._current_text()))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "paste-save":
            self.dismiss(PasteResult(action="save", text=self._current_text()))
        elif event.button.id == "paste-insert":
            self.dismiss(
                PasteResult(action="insert", text=self._current_text())
            )
        else:
            self.dismiss(None)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)
