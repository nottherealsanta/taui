"""Reasoning widget: live scrollable while streaming, collapsed line when done."""

from __future__ import annotations

from rich.markup import escape
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

PREVIEW_HEIGHT = 5


class ReasoningModal(ModalScreen[None]):
    """Modal showing the full reasoning content with scrolling."""

    DEFAULT_CSS = """
    ReasoningModal {
        align: center middle;
    }
    #reasoning-dialog {
        width: 90%;
        height: 90%;
        background: $surface;
        border: thick $surface-lighten-1;
        padding: 1 2;
    }
    #reasoning-dialog .dialog-title {
        width: 100%;
        content-align: center middle;
        padding: 0 0 1 0;
        color: cyan;
        text-style: bold;
    }
    #reasoning-dialog #reasoning-scroll {
        height: 1fr;
        border-top: solid $surface-lighten-1;
        padding: 1 0 0 0;
    }
    #reasoning-dialog #reasoning-body {
        color: $text-muted;
    }
    #reasoning-dialog .button-container {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
    }
    """

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text

    def compose(self) -> ComposeResult:
        with Container(id="reasoning-dialog"):
            yield Static("[bold]Reasoning[/bold]", classes="dialog-title")
            with VerticalScroll(id="reasoning-scroll"):
                yield Static(self._text, markup=False, id="reasoning-body")
            with Horizontal(classes="button-container"):
                yield Button("Close", variant="primary", id="close-button")

    def on_button_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


class ReasoningWidget(Container):
    """Streaming reasoning display.

    - While streaming: shows a fixed-height scrollable region with the
      latest reasoning text, dimmed-italic.
    - When ``finalize()`` is called: replaces itself with a single-line
      collapsed summary that can be clicked to view the full reasoning
      in a modal.
    """

    DEFAULT_CSS = """
    ReasoningWidget {
        height: auto;
        margin: 0 1 0 0;
        padding: 0;
    }
    ReasoningWidget .reasoning-scroll {
        height: auto;
        min-height: 1;
        max-height: 5;
        padding: 0 1 0 0;
        color: $text-muted;
        scrollbar-size-vertical: 1;
    }
    ReasoningWidget .reasoning-body {
        color: $text-muted;
        text-style: italic;
    }
    ReasoningWidget.collapsed .reasoning-scroll {
        display: none;
    }
    ReasoningWidget .reasoning-summary {
        display: none;
        height: 1;
        padding: 0 1 0 0;
        color: $text-muted;
        text-style: italic;
    }
    ReasoningWidget.collapsed .reasoning-summary {
        display: block;
    }
    ReasoningWidget.collapsed .reasoning-summary:hover {
        color: $text;
        background: $surface-lighten-1 10%;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._buffer = ""
        self._finalized = False

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="reasoning-scroll"):
            yield Static("", markup=False, classes="reasoning-body")
        yield Static("", markup=True, classes="reasoning-summary")

    @property
    def text(self) -> str:
        return self._buffer

    def append_text(self, fragment: str) -> None:
        if self._finalized:
            return
        self._buffer += fragment
        self._refresh_live()

    def update_text(self, full_text: str) -> None:
        """Replace the buffer (used by streaming flush)."""
        if self._finalized:
            return
        self._buffer = full_text
        self._refresh_live()

    def _refresh_live(self) -> None:
        try:
            body = self.query_one(".reasoning-body", Static)
            scroll = self.query_one(".reasoning-scroll", VerticalScroll)
        except Exception:
            return
        body.update(self._buffer)
        try:
            scroll.scroll_end(animate=False, immediate=True)
        except Exception:
            pass

    def finalize(self) -> None:
        if self._finalized:
            return
        self._finalized = True
        try:
            summary = self.query_one(".reasoning-summary", Static)
        except Exception:
            return
        first_line = next(
            (ln for ln in self._buffer.splitlines() if ln.strip()), ""
        ).strip()
        if len(first_line) > 80:
            first_line = first_line[:80] + "…"
        # Rough token estimate (~4 chars/token) — matches the rest of the
        # codebase's estimator and avoids a tokenizer dependency.
        tokens = max(1, len(self._buffer) // 4) if self._buffer else 0
        token_str = f"[{tokens:,}]"
        if first_line:
            summary.update(
                f"[dim]▸ {escape(first_line)}  {token_str}[/dim]"
            )
        else:
            summary.update(f"[dim]▸ Reasoning  {token_str}[/dim]")
        self.add_class("collapsed")

    async def on_click(self, event: events.Click) -> None:
        if not self._finalized:
            return
        event.stop()
        if not self._buffer:
            return
        await self.app.push_screen(ReasoningModal(self._buffer))
