"""Sub-agent widget: live activity while running, full modal on click."""

from __future__ import annotations

from rich.markup import escape
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from taui.tui.widgets.tool_status import ToolStatusWidget

_LATEST_COLOR = "#6e7681"
_FINISHED_COLOR = "#3fb950"


class SubAgentModal(ModalScreen[None]):
    """Modal showing the full sub-agent activity log.

    The widget passes a reference to itself; the modal pulls the latest
    log each time it refreshes so the display stays live while the
    sub-agent is still running.
    """

    DEFAULT_CSS = """
    SubAgentModal {
        align: center middle;
    }
    #sub-agent-dialog {
        width: 90%;
        height: 90%;
        background: $surface;
        border: thick $surface-lighten-1;
        padding: 1 2;
    }
    #sub-agent-dialog .dialog-title {
        width: 100%;
        content-align: center middle;
        padding: 0 0 1 0;
        color: cyan;
        text-style: bold;
    }
    #sub-agent-dialog #sub-agent-scroll {
        height: 1fr;
        border-top: solid $surface-lighten-1;
        padding: 1 0 0 0;
    }
    #sub-agent-dialog .button-container {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
    }
    """

    def __init__(self, widget: SubAgentWidget) -> None:
        super().__init__()
        self._widget = widget

    def compose(self) -> ComposeResult:
        with Container(id="sub-agent-dialog"):
            yield Static(
                f"[bold]Sub-agent: {escape(self._widget.task_summary)}[/bold]",
                classes="dialog-title",
                markup=True,
            )
            with VerticalScroll(id="sub-agent-scroll"):
                yield Static(
                    self._widget.full_log_text(),
                    markup=False,
                    id="sub-agent-body",
                )
            with Horizontal(classes="button-container"):
                yield Button("Close", variant="primary", id="close-button")

    def on_mount(self) -> None:
        # Refresh every 0.5s so a live sub-agent keeps the modal updated.
        self.set_interval(0.5, self._refresh)

    def _refresh(self) -> None:
        try:
            body = self.query_one("#sub-agent-body", Static)
        except Exception:
            return
        body.update(self._widget.full_log_text())

    def on_button_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


class SubAgentWidget(ToolStatusWidget):
    """A specialised tool widget for ``sub_agent`` calls.

    While the sub-agent runs, the body shows the most recent activity
    line (e.g., the latest tool the child called). When the call
    completes, the body collapses to ``✓ Finished`` and the widget
    becomes clickable to open a modal with the full activity log.
    """

    DEFAULT_CSS = """
    SubAgentWidget:hover {
        background: $surface-lighten-1 5%;
    }
    """

    def __init__(self, tool_name: str, args_str: str = "", arguments=None) -> None:
        super().__init__(tool_name, args_str, arguments=arguments)
        self._activity_log: list[str] = []
        self._finished: bool = False

    @property
    def task_summary(self) -> str:
        task = (self.arguments or {}).get("task") or self.args_str or "sub-agent"
        task = str(task).strip().splitlines()[0] if str(task).strip() else "sub-agent"
        if len(task) > 80:
            task = task[:80] + "…"
        return task

    def record_activity(self, line: str) -> None:
        """Append a live activity line and refresh the body."""
        line = line.strip()
        if not line:
            return
        self._activity_log.append(line)
        if not self._finished:
            self._refresh_live_body()

    def full_log_text(self) -> str:
        if not self._activity_log:
            return "(no activity yet)"
        return "\n".join(self._activity_log)

    def _refresh_live_body(self) -> None:
        if not self.is_mounted:
            return
        try:
            body = self.query_one("#body", Static)
        except Exception:
            return
        latest = self._activity_log[-1]
        if len(latest) > 200:
            latest = latest[:200] + "…"
        text = Text.from_markup(
            f"[{_LATEST_COLOR}]└ {escape(latest)}[/{_LATEST_COLOR}]"
        )
        body.update(text)
        body.styles.display = "block"

    async def complete(self, output: str = "") -> None:
        await super().complete(output)
        self._finished = True
        if output:
            preview = output.strip().splitlines()[0] if output.strip() else ""
            if len(preview) > 80:
                preview = preview[:80] + "…"
            self._activity_log.append(f"== Finished: {preview}")
        else:
            self._activity_log.append("== Finished")
        try:
            body = self.query_one("#body", Static)
            body.update(
                Text.from_markup(
                    f"[{_FINISHED_COLOR}]✓ Finished[/{_FINISHED_COLOR}]  "
                    f"[{_LATEST_COLOR}]click to view full log[/{_LATEST_COLOR}]"
                )
            )
            body.styles.display = "block"
        except Exception:
            pass

    async def fail(self, error: str = "") -> None:
        await super().fail(error)
        self._finished = True
        self._activity_log.append(f"== Failed: {error}" if error else "== Failed")

    async def on_click(self, event: events.Click) -> None:
        event.stop()
        await self.app.push_screen(SubAgentModal(self))
