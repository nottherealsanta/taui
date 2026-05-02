"""Spinner widget shown during LLM processing."""

from __future__ import annotations

import asyncio

from rich.text import Text
from textual.widgets import Static


class SpinnerWidget(Static):
    """Global thinking spinner, hidden by default."""

    DEFAULT_CSS = """
    SpinnerWidget {
        height: 1;
        padding: 0 2;
        display: none;
    }
    SpinnerWidget.visible {
        display: block;
    }
    """

    SPINNER_FRAMES = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]

    def __init__(self) -> None:
        super().__init__()
        self._frame = 0
        self._status_text = "Thinking..."
        self._running = False

    def set_status(self, text: str) -> None:
        self._status_text = text or "Thinking..."
        self._refresh_display()

    def _refresh_display(self) -> None:
        frame = self.SPINNER_FRAMES[self._frame % len(self.SPINNER_FRAMES)]
        self.update(
            Text.from_markup(
                f" [bold #3fb950]{frame}[/bold #3fb950]"
                f" [#8b949e]{self._status_text}[/#8b949e]"
            )
        )

    async def start(self) -> None:
        self._running = True
        self.add_class("visible")
        while self._running:
            self._frame += 1
            self._refresh_display()
            await asyncio.sleep(0.1)

    def stop(self) -> None:
        self._running = False
        self.remove_class("visible")
