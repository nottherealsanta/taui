"""Indeterminate progress widget shown during LLM processing."""

from __future__ import annotations

from rich.text import Text
from textual.timer import Timer
from textual.widgets import Static


class ActivityProgress(Static):
    """Activity progress row above the info bar."""

    DEFAULT_CSS = """
    ActivityProgress {
        height: 1;
        padding: 0;
        margin: 0 1;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._offset = 0
        self._direction = 1
        self._running = False
        self._active_style = "#3fb950"
        self._refresh_timer: Timer | None = None

    def _advance(self) -> None:
        self._offset += 1 * self._direction
        self.refresh()

    def set_active_style(self, style: str) -> None:
        self._active_style = style or "#3fb950"
        self.refresh()

    def start(self) -> None:
        self._running = True
        if self._refresh_timer is None:
            self._refresh_timer = self.set_interval(0.02, self._advance)
        else:
            self._refresh_timer.resume()
        self.refresh()

    def stop(self) -> None:
        self._running = False
        if self._refresh_timer is not None:
            self._refresh_timer.pause()
        self._offset = 0
        self._direction = 1
        self.refresh()

    def render(self) -> Text:
        width = max(12, self.size.width or 40)
        if not self._running:
            return Text("━" * width, style="#30363d")

        segment = max(4, width // 5)
        travel = max(1, width - segment)
        position = self._offset
        if position >= travel:
            position = travel
            self._direction = -1
            self._offset = travel
        elif position <= 0:
            position = 0
            self._direction = 1
            self._offset = 0

        bar = Text()
        for index in range(width):
            if position <= index < position + segment:
                bar.append("━", style=self._active_style)
            else:
                bar.append("━", style="#30363d")
        return bar
