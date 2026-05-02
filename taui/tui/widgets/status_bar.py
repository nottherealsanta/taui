"""Status bar with model info and context usage."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from taui.agent.context import DEFAULT_MAX_INPUT_TOKENS, estimate_total_tokens


class ModelStatus(Static):
    """Left side: provider/model."""

    DEFAULT_CSS = """
    ModelStatus {
        height: 1;
        width: auto;
        padding: 0 1 0 0;
        margin: 0 0 0 2;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._provider = ""
        self._model = ""
        self._extensions_mode = False

    def set_info(
        self, provider: str, model: str, extensions_mode: bool = False
    ) -> None:
        self._provider = provider
        self._model = model
        self._extensions_mode = extensions_mode
        self.refresh()

    def render(self) -> Text:
        if self._extensions_mode:
            return Text.from_markup(
                f"[bold yellow]EXTENSIONS[/bold yellow] [dim]|[/dim] "
                f"[bold]{self._model}[/bold] [dim]|[/dim] "
                f"[dim]{self._provider}[/dim]"
            )
        if self._model:
            return Text.from_markup(
                f"[bold]{self._model}[/bold] [dim]|[/dim] "
                f"[dim]{self._provider}[/dim]"
            )
        return Text.from_markup("[dim]Initializing...[/dim]")


class ContextStatus(Static):
    """Right side: context usage bar."""

    DEFAULT_CSS = """
    ContextStatus {
        height: 1;
        width: auto;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._tokens = 0
        self._max_tokens = DEFAULT_MAX_INPUT_TOKENS

    def set_usage(self, tokens: int, max_tokens: int | None = None) -> None:
        self._tokens = tokens
        if max_tokens:
            self._max_tokens = max_tokens
        self.refresh()

    def render(self) -> Text:
        if self._tokens == 0:
            return Text("")
        pct = (self._tokens / self._max_tokens) * 100 if self._max_tokens else 0
        if pct < 50:
            color = "green"
        elif pct < 75:
            color = "yellow"
        else:
            color = "red"
        bar_width = 10
        filled = int((pct / 100) * bar_width)
        empty = bar_width - filled
        bar = "\u2588" * filled + "\u2591" * empty
        return Text.from_markup(
            f"[{color}][{bar}] {pct:.1f}%[/{color}]  "
            f"[dim]{self._tokens:,} / {self._max_tokens:,} tokens[/dim]"
        )


class StatusBar(Widget):
    """Bottom bar: model info + context usage."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        width: 100%;
        layout: horizontal;
        dock: bottom;
    }
    """

    def compose(self) -> ComposeResult:
        yield ModelStatus()
        yield ContextStatus()

    def update_model(
        self, provider: str, model: str, extensions_mode: bool = False
    ) -> None:
        self.query_one(ModelStatus).set_info(provider, model, extensions_mode)

    def update_context(self, tokens: int, max_tokens: int | None = None) -> None:
        self.query_one(ContextStatus).set_usage(tokens, max_tokens)
