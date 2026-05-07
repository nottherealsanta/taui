"""Context breakdown modal screen."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, Label

from taui.agent.context import DEFAULT_MAX_INPUT_TOKENS, estimate_total_tokens


class ContextBreakdownScreen(ModalScreen[None]):
    """Modal showing token usage breakdown."""

    DEFAULT_CSS = """
    ContextBreakdownScreen {
        align: center middle;
    }
    #context-dialog {
        width: 70;
        height: auto;
        max-height: 90%;
        background: $surface;
        border: thick #586069;
        padding: 1 2;
    }
    #context-dialog .dialog-title {
        width: 100%;
        content-align: center middle;
        padding: 0 0 1 0;
        color: cyan;
        text-style: bold;
    }
    #context-dialog .total-usage {
        width: 100%;
        padding: 0 0 1 0;
        color: $text;
    }
    #context-dialog .component-row {
        width: 100%;
        height: auto;
        layout: horizontal;
    }
    #context-dialog .component-label {
        width: 20;
        color: $text-muted;
    }
    #context-dialog .component-bar {
        width: 30;
        padding: 0 1;
    }
    #context-dialog .component-value {
        width: 15;
        color: $text;
    }
    #context-dialog .button-container {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
    }
    """

    def __init__(self, messages: list, max_tokens: int = DEFAULT_MAX_INPUT_TOKENS) -> None:
        super().__init__()
        self._messages = messages
        self._max_tokens = max_tokens

    def compose(self) -> ComposeResult:
        total_tokens = estimate_total_tokens(self._messages)
        pct = (total_tokens / self._max_tokens * 100) if self._max_tokens else 0

        # Categorize messages
        system_tokens = 0
        user_tokens = 0
        assistant_tokens = 0
        tool_tokens = 0
        for msg in self._messages:
            content = msg.content or ""
            est = len(content) // 4
            match msg.role:
                case "system":
                    system_tokens += est
                case "user":
                    user_tokens += est
                case "assistant":
                    assistant_tokens += est
                case "tool":
                    tool_tokens += est

        with Container(id="context-dialog"):
            yield Label("[bold]Context Usage Breakdown[/bold]", classes="dialog-title")
            yield Label(
                f"Total: {total_tokens:,} / {self._max_tokens:,} tokens ({pct:.1f}%)",
                classes="total-usage",
            )

            components = [
                ("System", system_tokens),
                ("User Messages", user_tokens),
                ("Assistant", assistant_tokens),
                ("Tool Results", tool_tokens),
            ]

            with VerticalScroll():
                for label, tokens in components:
                    if tokens == 0:
                        continue
                    comp_pct = (tokens / self._max_tokens * 100) if self._max_tokens else 0
                    bar_width = 20
                    filled = int((comp_pct / 100) * bar_width) if comp_pct > 0 else 0
                    empty = bar_width - filled
                    bar = "\u2588" * filled + "\u2591" * empty
                    if comp_pct < 15:
                        color = "green"
                    elif comp_pct < 30:
                        color = "yellow"
                    else:
                        color = "red"

                    with Horizontal(classes="component-row"):
                        yield Label(label, classes="component-label")
                        yield Label(
                            f"[{color}]{bar}[/{color}]",
                            classes="component-bar",
                            markup=True,
                        )
                        yield Label(
                            f"{tokens:,} ({comp_pct:.1f}%)",
                            classes="component-value",
                        )

            with Horizontal(classes="button-container"):
                yield Button("Close", variant="primary", id="close-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
