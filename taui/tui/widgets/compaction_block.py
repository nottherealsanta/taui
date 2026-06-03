"""Clickable gray block that stands in for compacted chat turns.

When the agent loop compacts older messages out of the LLM context, the
matching ``TurnContainer`` widgets are detached from the chat scroll and
absorbed into a ``CompactionBlock``. The block renders as a single dimmed
row showing the compaction stats; clicking it opens
``CompactionInspectorScreen`` with the LLM-generated summary and the
absorbed turns rebuilt inside the modal.

The goal is for the main chat to mirror what is actually in the LLM's
context: compacted turns disappear from the main scroll and live only
inside this block.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual import events
from textual.widgets import Static


def _short_tokens(n: int) -> str:
    if n < 1_000:
        return str(n)
    return f"{n / 1_000:.1f}k"


@dataclass
class AbsorbedTurn:
    """Compact snapshot of a turn that was removed from the chat scroll.

    Only data needed to re-render the turn inside the inspector modal is
    captured here. Holding the original ``TurnContainer`` widget would
    keep its body alive even after we removed it from the chat log.
    """

    user_text: str
    image_note: str
    turn_id: int
    replay_items: list
    total_tokens: int
    tool_count: int
    model: str
    duration_s: float
    agent_id: str


class CompactionBlock(Static):
    """A clickable gray bar that opens the compaction inspector."""

    DEFAULT_CSS = """
    CompactionBlock {
        height: 1;
        margin: 1 0 1 0;
        padding: 0 2;
        color: $text-muted;
        background: $taui-option-active;
        text-style: none;
    }
    CompactionBlock:hover {
        background: $taui-option-active;
        color: $foreground;
    }
    """

    def __init__(
        self,
        removed: int,
        before_tokens: int,
        after_tokens: int,
        *,
        summary_text: str = "",
        absorbed: list[AbsorbedTurn] | None = None,
        kind: str = "auto",
    ) -> None:
        super().__init__("", markup=True)
        self._removed = removed
        self._before_tokens = before_tokens
        self._after_tokens = after_tokens
        self._summary_text = summary_text
        self._absorbed: list[AbsorbedTurn] = list(absorbed or [])
        self._kind = kind

    @property
    def absorbed_turns(self) -> list[AbsorbedTurn]:
        return list(self._absorbed)

    @property
    def summary_text(self) -> str:
        return self._summary_text

    @property
    def removed(self) -> int:
        return self._removed

    @property
    def before_tokens(self) -> int:
        return self._before_tokens

    @property
    def after_tokens(self) -> int:
        return self._after_tokens

    @property
    def kind(self) -> str:
        return self._kind

    def _label(self) -> str:
        turns = len(self._absorbed)
        parts = ["▾ context compacted"]
        if turns:
            parts.append(f"{turns} turn{'s' if turns != 1 else ''}")
        if self._removed:
            parts.append(f"{self._removed} msgs")
        if self._before_tokens or self._after_tokens:
            parts.append(
                f"{_short_tokens(self._before_tokens)} → "
                f"{_short_tokens(self._after_tokens)}"
            )
        parts.append("[dim](click to inspect)[/dim]")
        return "  ·  ".join(parts)

    def _render_line(self, width: int) -> str:
        return self._label()

    def on_mount(self, _event: events.Mount) -> None:
        self.update(self._render_line(self.size.width or 80))

    def on_resize(self, event: events.Resize) -> None:
        self.update(self._render_line(event.size.width or 80))

    async def on_click(self, event: events.Click) -> None:
        event.stop()
        from taui.tui.screens.compaction_inspector import CompactionInspectorScreen

        await self.app.push_screen(CompactionInspectorScreen(self))
