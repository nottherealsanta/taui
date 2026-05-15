"""Per-reply footer bar — shows agent id + model under each turn's content."""

from __future__ import annotations

from rich.markup import escape
from textual.widgets import Static

from taui.tui.widgets.info_bar import _agent_color


class ReplyFooter(Static):
    """Small dim bar pinned to the bottom of a single reply turn."""

    DEFAULT_CSS = """
    ReplyFooter {
        height: 1;
        padding: 0 2;
        margin: 1 0 0 0;
        color: $text-muted;
        background: transparent;
    }
    """

    def __init__(self, agent_id: str = "", model: str = "") -> None:
        super().__init__("", markup=True)
        self._agent_id = agent_id
        self._model = model

    def on_mount(self) -> None:
        self._refresh_text()

    def set_info(self, agent_id: str, model: str) -> None:
        self._agent_id = agent_id
        self._model = model
        self._refresh_text()

    def _refresh_text(self) -> None:
        parts: list[str] = []
        if self._agent_id:
            color = _agent_color(self._agent_id)
            parts.append(f"[{color}]{escape(self._agent_id)}[/{color}]")
        if self._model:
            parts.append(f"[dim]{escape(self._model)}[/dim]")
        self.update("[dim] · [/dim]".join(parts))
