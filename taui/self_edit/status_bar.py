"""Self-edit mode selection line."""

from __future__ import annotations

from textual.widgets import Static


class SelfEditStatusBar(Static):
    """One-row self-edit selection line mounted above the chat input."""

    DEFAULT_CSS = """
    SelfEditStatusBar {
        height: 1;
        padding: 0;
        margin: 1 3 0 3;
        color: #f0c808;
        background: transparent;
    }
    """

    def __init__(self, *, id: str = "self-edit-status") -> None:
        super().__init__("selection: -", id=id, markup=False)

    def set_selection(self, kind: str | None, name: str | None) -> None:
        if kind and name:
            self.update(f"selection: {kind} {name}")
        else:
            self.update("selection: -")
