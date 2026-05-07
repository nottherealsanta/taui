"""Self-edit mode status indicator."""

from __future__ import annotations

from textual.widgets import Static


class SelfEditStatusBar(Static):
    """One-row self-edit mode divider mounted above the chat input."""

    DEFAULT_CSS = """
    SelfEditStatusBar {
        height: 1;
        padding: 0 2;
        margin: 0 2;
        color: $text-muted;
        background: $surface;
    }
    """

    def __init__(self, *, id: str = "self-edit-status") -> None:
        super().__init__("self-edit", id=id, markup=False)
