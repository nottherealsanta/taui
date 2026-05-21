"""Collapsible per-turn container — wraps a user message and its assistant body.

A "turn" is a single user → assistant exchange. The container has two visual
regions:

    TurnContainer
    ├── .turn-header  (chevron + user message text + collapsed summary)
    └── .turn-body    (assistant content goes here — markdown, tools, footer)

Only the chevron toggles the collapsed state. Clicks anywhere else on the
header row are ignored, leaving that area free for future affordances.
"""

from __future__ import annotations

from rich.markup import escape
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Static


class _Chevron(Static):
    """Clickable fold/unfold control."""

    DEFAULT_CSS = """
    _Chevron {
        width: 3;
        height: auto;
        padding: 1 0 1 1;
        color: #8b949e;
        text-style: bold;
    }
    _Chevron:hover {
        color: #e6edf3;
        background: $surface-lighten-1;
    }
    """

    def __init__(self) -> None:
        super().__init__("▼", id="chev", markup=False)

    async def on_click(self, event: events.Click) -> None:
        event.stop()
        parent: Widget | None = self.parent
        while parent is not None and not isinstance(parent, TurnContainer):
            parent = parent.parent
        if parent is not None:
            parent.toggle()


class TurnContainer(Vertical):
    """A collapsible wrapper for one user→assistant turn."""

    DEFAULT_CSS = """
    TurnContainer {
        height: auto;
        margin: 0 0 1 0;
    }
    TurnContainer.collapsed {
        margin: 0;
    }
    TurnContainer > .turn-header {
        height: auto;
        layout: horizontal;
        background: #1a1a1a;
        margin: 0;
    }
    TurnContainer > .turn-header > .user-text {
        width: 1fr;
        padding: 1 2 1 0;
        color: #e6e6e6;
        text-style: bold;
    }
    TurnContainer > .turn-summary {
        height: 1;
        padding: 0 2 0 4;
        margin: 0;
        layout: horizontal;
        color: #6e7681;
    }
    TurnContainer > .turn-summary > .turn-summary-left {
        width: 1fr;
        height: 1;
        color: #8b949e;
    }
    TurnContainer > .turn-summary > .turn-summary-right {
        width: auto;
        height: 1;
        color: #6e7681;
    }
    TurnContainer > .turn-body {
        height: auto;
        padding: 0;
        margin: 1 0 0 0;
    }
    TurnContainer.collapsed > .turn-body { display: none; }
    """

    def __init__(self, user_text: str, image_note: str = "", *, turn_id: int) -> None:
        super().__init__(id=f"turn-{turn_id}")
        self.user_text = user_text
        self.image_note = image_note
        self.turn_id = turn_id
        self.sticky_expanded = False
        self._total_tokens: int = 0
        self._tool_count: int = 0
        self._model: str = ""
        self._duration_s: float = 0.0
        self._agent_id: str = ""

    def compose(self) -> ComposeResult:
        yield Vertical(classes="turn-header")
        with Horizontal(classes="turn-summary", id="turn-summary"):
            yield Static(
                "",
                classes="turn-summary-left",
                id="turn-summary-left",
                markup=False,
            )
            yield Static(
                "",
                classes="turn-summary-right",
                id="turn-summary-right",
                markup=False,
            )
        yield Vertical(classes="turn-body")

    async def on_mount(self) -> None:
        header = self.query_one(".turn-header", Vertical)
        await header.mount(_Chevron())
        body_text = f"{escape(self.user_text)}{self.image_note}"
        await header.mount(
            Static(body_text, classes="user-text", id="user-text", markup=True)
        )
        # Summary is hidden until the turn collapses with stats to show.
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        try:
            row = self.query_one("#turn-summary", Horizontal)
            left = self.query_one("#turn-summary-left", Static)
            right = self.query_one("#turn-summary-right", Static)
        except Exception:
            return
        if self.has_class("collapsed"):
            left_text, right_text = _format_summary(
                self._total_tokens,
                self._tool_count,
                self._model,
                self._duration_s,
                self._agent_id,
            )
            row.display = True
            left.update(left_text)
            right.update(right_text)
        else:
            row.display = False
            left.update("")
            right.update("")

    @property
    def body(self) -> Vertical:
        return self.query_one(".turn-body", Vertical)

    def is_collapsed(self) -> bool:
        return self.has_class("collapsed")

    def collapse(self) -> None:
        if not self.has_class("collapsed"):
            self.add_class("collapsed")
            try:
                self.query_one("#chev", Static).update("▶")
            except Exception:
                pass
        self._refresh_summary()

    def expand(self, *, sticky: bool = False) -> None:
        if self.has_class("collapsed"):
            self.remove_class("collapsed")
            try:
                self.query_one("#chev", Static).update("▼")
            except Exception:
                pass
        if sticky:
            self.sticky_expanded = True
        self._refresh_summary()

    def toggle(self) -> None:
        if self.is_collapsed():
            self.expand(sticky=True)
        else:
            self.collapse()
            self.sticky_expanded = False

    def set_summary(
        self,
        *,
        total_tokens: int,
        tool_count: int,
        model: str = "",
        duration_s: float = 0.0,
        agent_id: str = "",
    ) -> None:
        self._total_tokens = total_tokens
        self._tool_count = tool_count
        self._model = model
        self._duration_s = duration_s
        self._agent_id = agent_id
        self._refresh_summary()


def _format_summary(
    tokens: int,
    tools: int,
    model: str,
    duration_s: float,
    agent_id: str = "",
) -> tuple[str, str]:
    """Return (left, right) summary halves for the collapsed turn footer.

    Left: agent · model · time   (identity / metadata)
    Right: tokens · tools         (volume metrics)
    """
    left_parts: list[str] = []
    if agent_id:
        left_parts.append(agent_id)
    if model:
        left_parts.append(model)
    if duration_s > 0:
        if duration_s >= 60:
            mins = int(duration_s // 60)
            secs = int(duration_s % 60)
            left_parts.append(f"{mins}m{secs}s")
        else:
            left_parts.append(f"{duration_s:.1f}s")

    if tokens >= 1000:
        tok_str = f"{tokens / 1000:.1f}k tok"
    else:
        tok_str = f"{tokens} tok"
    tool_str = f"{tools} tool{'s' if tools != 1 else ''}"
    right_parts = [tok_str, tool_str]

    left = " · ".join(left_parts)
    if left:
        left = "└ " + left
    return left, " · ".join(right_parts)
