"""Indeterminate progress widget shown during LLM processing."""

from __future__ import annotations

import math

from rich.text import Text
from textual.timer import Timer
from textual.widgets import Static


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    s = value.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def _blend_hex(c1: str, c2: str, t: float) -> str:
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


_IDLE_COLOR = "#30363d"


class ActivityProgress(Static):
    """Activity progress row above the info bar."""

    DEFAULT_CSS = """
    ActivityProgress {
        height: 1;
        padding: 0;
        margin: 0 2;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._offset = 0
        self._direction = 1
        self._running = False
        self._mode: str = "idle"  # "idle" | "bounce" | "breathe"
        self._active_style = "#3fb950"
        self._breath_phase = 0.0
        self._timer: Timer | None = None

    def _advance_bounce(self) -> None:
        self._offset += 1 * self._direction
        self.refresh()

    def _advance_breath(self) -> None:
        # ~6s per full sin cycle at 0.05s tick → calm, slow pulse.
        self._breath_phase += 0.05
        self.refresh()

    def set_active_style(self, style: str) -> None:
        self._active_style = style or "#3fb950"
        self.refresh()

    def _restart_timer(self, interval: float, callback) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._timer = self.set_interval(interval, callback)

    def start(self) -> None:
        """Indeterminate bouncing bar — active LLM processing."""
        self._running = True
        self._mode = "bounce"
        self._offset = 0
        self._direction = 1
        self._restart_timer(0.02, self._advance_bounce)
        self.refresh()

    def start_breathing(self) -> None:
        """Slow breathing pulse — session loading."""
        self._running = True
        self._mode = "breathe"
        self._breath_phase = 0.0
        self._restart_timer(0.05, self._advance_breath)
        self.refresh()

    def stop(self) -> None:
        self._running = False
        self._mode = "idle"
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._offset = 0
        self._direction = 1
        self._breath_phase = 0.0
        self.refresh()

    def render(self) -> Text:
        width = max(12, self.size.width or 40)
        if not self._running:
            return Text("━" * width, style=_IDLE_COLOR)

        if self._mode == "breathe":
            t = (math.sin(self._breath_phase) + 1) / 2
            color = _blend_hex(_IDLE_COLOR, self._active_style, t)
            return Text("━" * width, style=color)

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
                bar.append("━", style=_IDLE_COLOR)
        return bar
