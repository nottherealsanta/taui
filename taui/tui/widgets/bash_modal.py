"""Live modal for inspecting a bash tool execution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

if TYPE_CHECKING:
    from taui.tui.widgets.tool_status import BashToolStatusWidget


_MUTED = "#8b949e"
_VALUE = "#c9d1d9"
_ERROR = "#f85149"


class BashModal(ModalScreen[None]):
    """Modal showing a bash command's full live output stream."""

    DEFAULT_CSS = """
    BashModal {
        align: center middle;
    }
    #bash-dialog {
        width: 90%;
        height: 90%;
        background: $surface;
        border: thick $surface-lighten-1;
        padding: 1 2;
    }
    #bash-dialog .dialog-title {
        width: 100%;
        content-align: center middle;
        padding: 0 0 1 0;
        color: cyan;
        text-style: bold;
    }
    #bash-dialog .section-header {
        padding: 1 0 0 0;
        text-style: bold;
        color: #58a6ff;
    }
    #bash-dialog .section-body {
        padding: 0 0 0 2;
    }
    #bash-dialog #bash-scroll {
        height: 1fr;
        border-top: solid $surface-lighten-1;
        padding: 1 0 0 0;
    }
    #bash-dialog .button-container {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
    }
    """

    def __init__(self, widget: BashToolStatusWidget) -> None:
        super().__init__()
        self._widget = widget

    def compose(self) -> ComposeResult:
        command = (self._widget.arguments or {}).get("command", "") or "bash"
        with Container(id="bash-dialog"):
            yield Static(
                "[bold]bash[/bold]",
                classes="dialog-title",
                markup=True,
            )
            with VerticalScroll(id="bash-scroll"):
                yield Static("Command", classes="section-header", markup=False)
                yield Static(
                    str(command),
                    classes="section-body",
                    markup=False,
                )

                yield Static("Status", classes="section-header", markup=False)
                yield Static(
                    self._status_markup(),
                    classes="section-body",
                    markup=True,
                    id="bash-status",
                )

                yield Static("Output", classes="section-header", markup=False)
                yield Static(
                    self._output_text(),
                    classes="section-body",
                    markup=False,
                    id="bash-output",
                )
            with Horizontal(classes="button-container"):
                yield Button("Close", variant="primary", id="close-button")

    def on_mount(self) -> None:
        self.set_interval(0.25, self._refresh)
        # Open scrolled to the tail so the latest output is visible.
        self.call_after_refresh(self._scroll_to_tail)

    def _scroll_to_tail(self) -> None:
        try:
            scroll = self.query_one("#bash-scroll", VerticalScroll)
        except Exception:
            return
        scroll.scroll_end(animate=False)

    def _status_markup(self) -> str:
        w = self._widget
        if w.is_running:
            return f"[{_MUTED}]running…[/{_MUTED}]"
        if w.is_failed:
            return f"[{_ERROR}]failed[/{_ERROR}]"
        return f"[{_VALUE}]done[/{_VALUE}]"

    def _output_text(self) -> str:
        lines = self._widget.expanded_lines(max_lines=2000)
        return "\n".join(lines) if lines else "(no output)"

    def _refresh(self) -> None:
        try:
            status = self.query_one("#bash-status", Static)
            output = self.query_one("#bash-output", Static)
            scroll = self.query_one("#bash-scroll", VerticalScroll)
        except Exception:
            return
        status.update(self._status_markup())
        output.update(self._output_text())
        # Auto-scroll to tail while the command is still running.
        if self._widget.is_running:
            scroll.scroll_end(animate=False)

    def on_button_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
