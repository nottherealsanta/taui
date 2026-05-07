"""Diff view modal screen — shows file changes on click."""

from __future__ import annotations

import difflib

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


class DiffViewScreen(ModalScreen[None]):
    """Modal showing unified diff for file changes."""

    DEFAULT_CSS = """
    DiffViewScreen {
        align: center middle;
    }
    #diff-dialog {
        width: 90%;
        height: 80%;
        background: $surface;
        border: thick #586069;
        padding: 1 2;
    }
    #diff-dialog .dialog-title {
        width: 100%;
        content-align: center middle;
        padding: 0 0 1 0;
        color: cyan;
        text-style: bold;
    }
    #diff-dialog .diff-content {
        height: 1fr;
        padding: 0 1;
    }
    #diff-dialog .diff-line-add {
        color: green;
    }
    #diff-dialog .diff-line-del {
        color: red;
    }
    #diff-dialog .diff-line-hunk {
        color: cyan;
    }
    #diff-dialog .diff-line {
        color: $text-muted;
    }
    #diff-dialog .button-container {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
        dock: bottom;
    }
    """

    def __init__(
        self,
        file_path: str,
        before: str,
        after: str,
    ) -> None:
        super().__init__()
        self._file_path = file_path
        self._before = before
        self._after = after

    def compose(self) -> ComposeResult:
        diff_lines = list(
            difflib.unified_diff(
                self._before.splitlines(keepends=True),
                self._after.splitlines(keepends=True),
                fromfile=f"a/{self._file_path}",
                tofile=f"b/{self._file_path}",
                lineterm="",
            )
        )

        with Container(id="diff-dialog"):
            yield Label(
                f"[bold]Changes: {self._file_path}[/bold]",
                classes="dialog-title",
            )
            with VerticalScroll(classes="diff-content"):
                if not diff_lines:
                    yield Static("[dim]No changes[/dim]", markup=True)
                else:
                    for line in diff_lines:
                        if line.startswith("+"):
                            yield Static(
                                line, classes="diff-line-add"
                            )
                        elif line.startswith("-"):
                            yield Static(
                                line, classes="diff-line-del"
                            )
                        elif line.startswith("@@"):
                            yield Static(
                                line, classes="diff-line-hunk"
                            )
                        else:
                            yield Static(line, classes="diff-line")

            with Horizontal(classes="button-container"):
                yield Button("Close", variant="primary", id="close-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
