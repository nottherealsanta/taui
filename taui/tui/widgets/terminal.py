"""Embedded terminal widget for displaying bash/shell tool output."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


class TerminalOutput(Widget):
    """Displays command output in a terminal-like pane."""

    DEFAULT_CSS = """
    TerminalOutput {
        height: auto;
        max-height: 20;
        padding: 0 1;
        margin: 0 0 0 3;
        border: solid $surface-lighten-1;
        background: $surface;
    }
    TerminalOutput .term-cmd {
        color: $success;
        padding: 0;
    }
    TerminalOutput .term-output {
        color: $text-muted;
        padding: 0;
    }
    TerminalOutput .term-error {
        color: $error;
        padding: 0;
    }
    """

    def __init__(self, command: str) -> None:
        super().__init__()
        self._command = command
        self._output_widget: Static | None = None
        self._buffer = ""

    def compose(self) -> ComposeResult:
        yield Static(
            Text.from_markup(f"[#7ee787]$ {self._command}[/#7ee787]"),
            classes="term-cmd",
        )
        yield Static("", classes="term-output", id="term-out")

    def append_output(self, text: str) -> None:
        """Append text to the terminal output."""
        self._buffer += text
        try:
            out = self.query_one("#term-out", Static)
            # Limit display to last 50 lines
            lines = self._buffer.split("\n")
            if len(lines) > 50:
                display = "\n".join(lines[-50:])
            else:
                display = self._buffer
            out.update(Text(display))
        except Exception:
            pass

    def set_complete(self, exit_code: int = 0) -> None:
        """Mark the command as completed."""
        try:
            out = self.query_one("#term-out", Static)
            lines = self._buffer.split("\n")
            if len(lines) > 50:
                display = "\n".join(lines[-50:])
            else:
                display = self._buffer
            if exit_code != 0:
                out.update(
                    Text.from_markup(
                        f"{display}\n[#f97583]exit code: {exit_code}[/#f97583]"
                    )
                )
            else:
                out.update(Text(display))
        except Exception:
            pass

    def set_error(self, error: str) -> None:
        """Show an error message."""
        try:
            out = self.query_one("#term-out", Static)
            out.update(Text.from_markup(f"[#f97583]{error}[/#f97583]"))
            out.add_class("term-error")
        except Exception:
            pass
