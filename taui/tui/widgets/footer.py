"""Custom footer with key legend."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class CustomFooter(Static):
    """Key shortcut legend."""

    DEFAULT_CSS = """
    CustomFooter {
        height: 1;
        color: $text-muted;
        padding: 0 2 0 1;
        text-align: right;
        dock: bottom;
    }
    """

    def __init__(self, busy: bool = False) -> None:
        super().__init__()
        self._busy = busy

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.refresh()

    def _chip(self, t: Text, key: str, label: str) -> None:
        t.append("[", style="#30363d")
        t.append(key, style="bold #e6edf3")
        t.append("] ", style="#30363d")
        t.append(label, style="#8b949e")
        t.append("  ")

    def render(self) -> Text:
        t = Text()
        self._chip(t, "ctrl+q", "quit")
        self._chip(t, "ctrl+n", "new")
        self._chip(t, "ctrl+b", "sidebar")
        self._chip(t, "ctrl+r", "info")
        self._chip(t, "ctrl+x", "context")
        self._chip(t, "alt+←/→", "focus pane")
        if self._busy:
            self._chip(t, "enter", "steer")
            self._chip(t, "alt+enter", "queue")
            self._chip(t, "ctrl+c", "cancel")
        else:
            self._chip(t, "enter", "send")
            self._chip(t, "shift+enter", "newline")
        return t
