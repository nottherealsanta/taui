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

    def render(self) -> Text:
        t = Text()
        t.append("ctrl+q", style="#e6edf3")
        t.append(" quit  ", style="#8b949e")
        t.append("ctrl+n", style="#e6edf3")
        t.append(" new  ", style="#8b949e")
        t.append("ctrl+b", style="#e6edf3")
        t.append(" sidebar  ", style="#8b949e")
        t.append("ctrl+r", style="#e6edf3")
        t.append(" info  ", style="#8b949e")
        t.append("ctrl+x", style="#e6edf3")
        t.append(" context  ", style="#8b949e")
        t.append("alt+←/→", style="#e6edf3")
        t.append(" focus pane  ", style="#8b949e")
        if self._busy:
            t.append("enter", style="#e6edf3")
            t.append(" steer  ", style="#8b949e")
            t.append("alt+enter", style="#e6edf3")
            t.append(" queue  ", style="#8b949e")
            t.append("ctrl+c", style="#e6edf3")
            t.append(" cancel", style="#8b949e")
        else:
            t.append("enter", style="#e6edf3")
            t.append(" send  ", style="#8b949e")
            t.append("shift+enter", style="#e6edf3")
            t.append(" newline", style="#8b949e")
        return t
