"""Standalone prototype of the dynamic widget rendering proposal.

Run with: uv run python scripts/widget_rendering_prototype.py

Demonstrates:
- Per-turn collapsible containers with chevron + clickable header.
- Auto-collapse of turns older than current - 1.
- Tool-status widgets with a "peek more" expansion for full output.

The widgets here are the same shapes that land in taui — but the
prototype is self-contained so it can be visually inspected (and
snapshot-tested via `tests/test_widget_rendering_prototype.py`) without
needing a Session, provider, or any of the agent loop machinery.
"""

from __future__ import annotations

from rich.markup import escape
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Footer, Static


# ── Turn container ────────────────────────────────────────────────────────


class TurnContainer(Vertical):
    """A single user→assistant exchange with a collapsible body."""

    DEFAULT_CSS = """
    TurnContainer {
        height: auto;
        margin: 0;
    }
    TurnContainer > .turn-header {
        height: auto;
        layout: horizontal;
        padding: 0 0 0 0;
        background: $surface;
        margin: 1 0 0 0;
    }
    TurnContainer > .turn-header > .chevron {
        width: 2;
        height: 1;
        color: $text-muted;
        padding: 1 0 0 1;
    }
    TurnContainer > .turn-header > .user-text {
        width: 1fr;
        padding: 1 2 1 0;
        color: #e6edf3;
        text-style: bold;
    }
    TurnContainer > .turn-body {
        height: auto;
        padding: 0;
    }
    TurnContainer.collapsed > .turn-body { display: none; }
    """

    def __init__(self, user_text: str, *, turn_id: int) -> None:
        super().__init__(id=f"turn-{turn_id}")
        self.user_text = user_text
        self.turn_id = turn_id
        self.sticky_expanded = False  # user explicitly toggled

    def compose(self) -> ComposeResult:
        with Vertical(classes="turn-header"):
            # Horizontal layout via flat children + CSS layout: horizontal.
            pass
        yield Vertical(id=f"turn-body-{self.turn_id}", classes="turn-body")

    async def on_mount(self) -> None:
        # Build the header manually so we can give the chevron its own id.
        header = self.query_one(".turn-header", Vertical)
        await header.mount(Static("▼ ", classes="chevron", id="chev"))
        await header.mount(
            Static(escape(self.user_text), classes="user-text", id="user-text")
        )

    @property
    def body(self) -> Vertical:
        return self.query_one(f"#turn-body-{self.turn_id}", Vertical)

    def is_collapsed(self) -> bool:
        return self.has_class("collapsed")

    def collapse(self, *, sticky: bool = False) -> None:
        if not self.has_class("collapsed"):
            self.add_class("collapsed")
            self.query_one("#chev", Static).update("▶ ")
        if sticky:
            self.sticky_expanded = False

    def expand(self, *, sticky: bool = False) -> None:
        if self.has_class("collapsed"):
            self.remove_class("collapsed")
            self.query_one("#chev", Static).update("▼ ")
        if sticky:
            self.sticky_expanded = True

    def toggle(self) -> None:
        if self.is_collapsed():
            self.expand(sticky=True)
        else:
            self.collapse(sticky=True)

    async def on_click(self) -> None:
        # Only treat clicks on the header as toggles, not clicks on the body.
        # Cheap heuristic: if the body isn't even mounted yet, treat all clicks
        # as header clicks.
        self.toggle()


# ── Tool widget with peek-more ────────────────────────────────────────────


class ToolRow(Widget):
    """A tool status row with optional expandable full output."""

    DEFAULT_CSS = """
    ToolRow {
        width: 100%;
        height: auto;
        padding: 0 2;
    }
    ToolRow > .tool-line {
        height: 1;
        layout: horizontal;
    }
    ToolRow > .tool-line > .tool-icon {
        width: 2;
        color: #6e7681;
    }
    ToolRow > .tool-line > .tool-summary {
        width: 1fr;
        color: #8b949e;
    }
    ToolRow.expandable > .tool-line > .tool-icon { color: $accent; }
    ToolRow > .tool-output-full {
        color: $text-muted;
        padding: 0 0 0 4;
        margin: 0;
    }
    ToolRow.collapsed-output > .tool-output-full { display: none; }
    """

    def __init__(
        self, name: str, args: str, *, summary: str = "", full_output: str = ""
    ) -> None:
        super().__init__()
        self.tool_name = name
        self.args = args
        self.summary = summary
        self.full_output = full_output
        if full_output:
            self.add_class("expandable")
        self.add_class("collapsed-output")

    def compose(self) -> ComposeResult:
        line = Vertical(classes="tool-line")
        yield line
        yield Static(escape(self.full_output), classes="tool-output-full")

    async def on_mount(self) -> None:
        line = self.query_one(".tool-line", Vertical)
        await line.mount(Static("✦ ", classes="tool-icon"))
        first = f"[#8b949e]{escape(self.tool_name)}[/#8b949e] "
        second = f"[#6e7681]{escape(self.args)}[/#6e7681]"
        third = (
            f"   [#6e7681]{escape(self.summary)}[/#6e7681]" if self.summary else ""
        )
        await line.mount(Static(f"{first}{second}{third}", markup=True, classes="tool-summary"))

    async def on_click(self) -> None:
        if not self.full_output:
            return
        if self.has_class("collapsed-output"):
            self.remove_class("collapsed-output")
        else:
            self.add_class("collapsed-output")


# ── Prototype app ─────────────────────────────────────────────────────────


class WidgetRenderingApp(App):
    """Visual prototype: three turns, auto-collapse policy, peek-more tool."""

    CSS = """
    Screen { background: #0d1117; }
    #log { padding: 1 2; }
    """

    BINDINGS = [
        ("n", "next_turn", "Add turn"),
        ("e", "expand_all", "Expand all"),
        ("c", "collapse_old", "Collapse old"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._turns: list[TurnContainer] = []

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="log")
        yield Footer()

    async def on_mount(self) -> None:
        await self._add_turn(
            "first user message — short",
            assistant_body="Sure, here's a quick answer.",
            tool=("read", "note.txt", "read me", "read me\nline two\nline three"),
        )
        await self._add_turn(
            "second user message — a bit longer to exercise wrapping",
            assistant_body="### Steps\n\n1. one\n2. two\n3. three",
            tool=(
                "grep",
                "pattern foo",
                "3 matches",
                "src/a.py:12: foo\nsrc/b.py:4: foo\nsrc/c.py:99: foo",
            ),
        )
        await self._add_turn(
            "third user message — current turn, should be expanded",
            assistant_body="Final reply for the prototype.",
            tool=("bash", "echo hi", "hi", "hi\n"),
        )

    async def _add_turn(
        self,
        user_text: str,
        *,
        assistant_body: str,
        tool: tuple[str, str, str, str] | None = None,
    ) -> None:
        log = self.query_one("#log", VerticalScroll)
        turn = TurnContainer(user_text, turn_id=len(self._turns))
        self._turns.append(turn)
        await log.mount(turn)
        # Now that the turn is mounted, populate its body.
        body = turn.body
        await body.mount(Static(assistant_body))
        if tool is not None:
            name, args, summary, full = tool
            await body.mount(ToolRow(name, args, summary=summary, full_output=full))
        self._autocollapse_old_turns()

    def _autocollapse_old_turns(self) -> None:
        if not self._turns:
            return
        keep = set(self._turns[-2:])
        for t in self._turns:
            if t in keep or t.sticky_expanded:
                t.expand()
            else:
                t.collapse()

    async def action_next_turn(self) -> None:
        await self._add_turn(
            f"new user message #{len(self._turns)}",
            assistant_body=f"reply {len(self._turns)}",
        )

    def action_expand_all(self) -> None:
        for t in self._turns:
            t.expand(sticky=True)

    def action_collapse_old(self) -> None:
        for t in self._turns:
            t.sticky_expanded = False
        self._autocollapse_old_turns()


if __name__ == "__main__":
    WidgetRenderingApp().run()
