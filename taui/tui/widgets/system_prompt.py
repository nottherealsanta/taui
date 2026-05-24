"""System prompt preview widget and full-content modal."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

PREVIEW_LINES = 5


class SystemPromptModal(ModalScreen[None]):
    """Modal showing the full system prompt content."""

    DEFAULT_CSS = """
    SystemPromptModal {
        align: center middle;
    }
    #system-prompt-dialog {
        width: 90%;
        height: 90%;
        background: $surface;
        border: thick $surface-lighten-1;
        padding: 1 2;
    }
    #system-prompt-dialog .dialog-title {
        width: 100%;
        content-align: center middle;
        padding: 0 0 1 0;
        color: cyan;
        text-style: bold;
    }
    #system-prompt-dialog #system-prompt-scroll {
        height: 1fr;
        border-top: solid $surface-lighten-1;
        padding: 1 0 0 0;
    }
    #system-prompt-dialog .button-container {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
    }
    """

    def __init__(self, prompt: str, title: str = "System prompt") -> None:
        super().__init__()
        self._prompt = prompt
        self._title = title

    def compose(self) -> ComposeResult:
        with Container(id="system-prompt-dialog"):
            yield Static(f"[bold]{self._title}[/bold]", classes="dialog-title")
            with VerticalScroll(id="system-prompt-scroll"):
                yield Static(self._prompt, markup=False, id="system-prompt-body")
            with Horizontal(classes="button-container"):
                yield Button("Close", variant="primary", id="close-button")

    def on_button_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


class SystemPromptWidget(Container):
    """Compact preview of the system prompt — click to open full modal.

    The widget renders ``PREVIEW_LINES`` lines of the prompt, with a hint
    line that the rest is available behind a click.
    """

    DEFAULT_CSS = """
    SystemPromptWidget {
        width: 100%;
        height: auto;
        color: #a0a0a0;
    }
    SystemPromptWidget:hover {
        color: #d0d0d0;
        background: $surface-lighten-1 10%;
    }
    SystemPromptWidget .sp-label {
        width: 100%;
        height: auto;
        padding: 0;
        margin: 0 1;
    }
    SystemPromptWidget .sp-body {
        width: 100%;
        height: auto;
        padding: 0 1 0 2;
        margin: 0 1 0 1;
    }
    """

    def __init__(
        self,
        prompt: str,
        *,
        label: str = "System prompt",
        label_style: str = "bold #58a6ff",
    ) -> None:
        self._prompt = prompt
        self._label = label
        self._label_style = label_style
        super().__init__()

    def compose(self) -> ComposeResult:
        label_markup, body_markup = self._render_parts()
        yield Static(label_markup, classes="sp-label", markup=True)
        yield Static(body_markup, classes="sp-body", markup=True)

    def set_prompt(self, prompt: str, *, label_style: str | None = None) -> None:
        self._prompt = prompt
        if label_style is not None:
            self._label_style = label_style
        label_markup, body_markup = self._render_parts()
        self.query_one(".sp-label", Static).update(label_markup)
        self.query_one(".sp-body", Static).update(body_markup)

    def _render_parts(self) -> tuple[str, str]:
        label_markup = f"[{self._label_style}]{self._label}[/]"
        if not self._prompt:
            return label_markup, "[dim](empty)[/dim]"
        lines = self._prompt.splitlines() or [self._prompt]
        head = lines[:PREVIEW_LINES]
        more = len(lines) - len(head)
        safe = "\n".join(line.replace("[", r"\[") for line in head)
        plural = "s" if more != 1 else ""
        if more > 0:
            hint = f"[dim italic]… +{more} more line{plural}[/dim italic]"
            return label_markup, f"{safe}\n{hint}"
        return label_markup, safe

    async def on_click(self, event: events.Click) -> None:
        event.stop()
        if not self._prompt:
            return
        await self.app.push_screen(SystemPromptModal(self._prompt, title=self._label))
