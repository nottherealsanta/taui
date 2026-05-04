"""Info bar widget — shows provider, model, tokens, and cost."""

from __future__ import annotations

import asyncio

from rich.text import Text
from textual.widgets import Static

SPINNER_FRAMES = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]


def _fmt_tokens(n: int) -> str:
    """Format token count: 1234 → '1k', 12345 → '12k', 123456 → '123k'."""
    if n < 1000:
        return str(n)
    return f"{round(n / 1000)}k"


class InfoBar(Static):
    """Single-line bar below input showing session info."""

    DEFAULT_CSS = """
    InfoBar {
        height: 3;
        padding: 1 2;
        margin: 0 2;
        color: $text-muted;
        background: transparent;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._provider = ""
        self._model = ""
        self._tokens = 0
        self._max_tokens = 0
        self._cost = 0.0
        self._extensions_mode = False
        self._spinning = False
        self._spinner_frame = 0
        self._status_text = "Thinking..."

    def update_info(
        self,
        *,
        provider: str = "",
        model: str = "",
        tokens: int = 0,
        max_tokens: int = 0,
        cost: float = 0.0,
        extensions_mode: bool = False,
    ) -> None:
        self._provider = provider
        self._model = model
        self._tokens = tokens
        self._max_tokens = max_tokens
        self._cost = cost
        self._extensions_mode = extensions_mode
        self.refresh()

    def set_status(self, text: str) -> None:
        self._status_text = text or "Thinking..."
        if self._spinning:
            self.refresh()

    async def start(self) -> None:
        self._spinning = True
        self._status_text = "Thinking..."
        while self._spinning:
            self._spinner_frame += 1
            self.refresh()
            await asyncio.sleep(0.1)

    def stop(self) -> None:
        self._spinning = False
        self.refresh()

    def render(self) -> Text:
        t = Text()

        if self._spinning:
            frame = SPINNER_FRAMES[self._spinner_frame % len(SPINNER_FRAMES)]
            t.append(f"{frame} ", style="bold #3fb950")
        else:
            t.append("  ")

        if self._extensions_mode:
            t.append(" EXT ", style="bold black on yellow")
            t.append(" ", style="dim")

        if self._model:
            t.append(self._model, style="#e6edf3")
            if self._provider:
                t.append(f"  {self._provider}", style="#8b949e italic")
        else:
            t.append("initializing…", style="dim italic")

        if self._max_tokens:
            t.append("  ", style="dim")
            t.append(
                f"{_fmt_tokens(self._tokens)}/{_fmt_tokens(self._max_tokens)}",
                style="#c9d1d9 italic",
            )

        if self._cost > 0:
            t.append("  ", style="dim")
            t.append(f"${self._cost:.4f}", style="#c9d1d9 italic")

        return t
