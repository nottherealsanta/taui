"""Modal that exposes the contents of a CompactionBlock.

Opened from ``CompactionBlock.on_click``. Shows two scrollable regions:

  1. The LLM-generated structured summary that replaced the dropped
     messages in the agent's context, or — when no LLM summary exists
     — the fallback marker text inserted by ``compact_messages``.
  2. The chat turns that were absorbed out of the main scroll, rebuilt
     from their cached ``ReplayItem`` snapshots.

The user can verify what was preserved in the LLM context versus what
was removed from their view of the conversation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from taui.tui.widgets.agent_response import AgentResponse
from taui.tui.widgets.reply_footer import ReplyFooter
from taui.tui.widgets.tool_status import ToolStatusWidget

if TYPE_CHECKING:
    from taui.tui.widgets.compaction_block import AbsorbedTurn, CompactionBlock


def _short_tokens(n: int) -> str:
    if n < 1_000:
        return str(n)
    return f"{n / 1_000:.1f}k"


class _AbsorbedTurnView(Vertical):
    """Read-only re-render of an absorbed turn inside the inspector."""

    DEFAULT_CSS = """
    _AbsorbedTurnView {
        height: auto;
        margin: 0 0 1 0;
        border-left: solid #3a3a3a;
        padding: 0 0 0 1;
    }
    _AbsorbedTurnView > .ci-user-text {
        height: auto;
        padding: 1 1 1 0;
        color: #e6e6e6;
        text-style: bold;
    }
    _AbsorbedTurnView > .ci-body {
        height: auto;
        padding: 0 1 0 0;
    }
    """

    def __init__(self, turn: AbsorbedTurn) -> None:
        super().__init__()
        self._turn = turn

    def compose(self) -> ComposeResult:
        yield Static(
            f"{escape(self._turn.user_text)}{self._turn.image_note}",
            classes="ci-user-text",
            markup=True,
        )
        yield Vertical(classes="ci-body")

    async def on_mount(self) -> None:
        body = self.query_one(".ci-body", Vertical)
        tool_section: Vertical | None = None
        pending: dict[str, ToolStatusWidget] = {}
        pending_order: list[str] = []

        for item in self._turn.replay_items:
            if item.kind == "assistant":
                resp = AgentResponse()
                await body.mount(resp)
                await resp.append_text(item.text)
                await resp.finalize()
                tool_section = None
            elif item.kind == "reasoning":
                from taui.tui.widgets.reasoning import ReasoningWidget

                rw = ReasoningWidget()
                await body.mount(rw)
                rw.update_text(item.text)
                rw.finalize()
                tool_section = None
            elif item.kind == "tool_call":
                if tool_section is None:
                    tool_section = Vertical(classes="tool-section")
                    await body.mount(tool_section)
                args_str = ", ".join(
                    f"{key}={str(value)[:60]}"
                    for key, value in (item.arguments or {}).items()
                )
                widget = ToolStatusWidget(
                    item.name, args_str, arguments=item.arguments
                )
                await tool_section.mount(widget)
                key = item.call_id or f"__pos_{len(pending_order)}"
                pending[key] = widget
                pending_order.append(key)
            elif item.kind == "tool_result":
                key = item.call_id if item.call_id in pending else (
                    pending_order[0] if pending_order else ""
                )
                widget = pending.pop(key, None) if key else None
                if widget and key in pending_order:
                    pending_order.remove(key)
                if widget is not None:
                    if item.is_error:
                        await widget.fail(item.text)
                    else:
                        await widget.complete(item.text)
            elif item.kind == "error":
                await body.mount(
                    Static(f"[red]Error: {escape(item.text)}[/red]", markup=True)
                )
                tool_section = None

        if self._turn.agent_id or self._turn.model:
            footer = ReplyFooter(self._turn.agent_id, self._turn.model, live=False)
            if self._turn.duration_s > 0:
                footer.finalize(self._turn.duration_s)
            await body.mount(footer)


class CompactionInspectorScreen(ModalScreen[None]):
    """Two-pane modal: summary on top, absorbed turns below."""

    DEFAULT_CSS = """
    CompactionInspectorScreen {
        align: center middle;
    }
    #ci-dialog {
        width: 90%;
        height: 90%;
        background: $surface;
        border: thick #3a3a3a;
        padding: 1 2;
    }
    #ci-dialog .ci-title {
        width: 100%;
        content-align: center middle;
        padding: 0 0 1 0;
        color: $primary;
        text-style: bold;
    }
    #ci-dialog .ci-stats {
        width: 100%;
        padding: 0 0 1 0;
        color: #8b949e;
    }
    #ci-dialog .ci-section-label {
        width: 100%;
        padding: 1 0 0 0;
        color: #6e7681;
        text-style: bold;
    }
    #ci-dialog #ci-summary {
        height: 1fr;
        border: solid #3a3a3a;
        padding: 1;
        background: #161616;
    }
    #ci-dialog #ci-summary-text {
        height: auto;
        color: #c9d1d9;
    }
    #ci-dialog #ci-turns {
        height: 1fr;
        border: solid #3a3a3a;
        padding: 1;
        background: #0d0d0d;
    }
    #ci-dialog .ci-empty {
        color: #6e7681;
        padding: 1;
    }
    #ci-dialog .ci-buttons {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
    }
    """

    def __init__(self, block: CompactionBlock) -> None:
        super().__init__()
        self._block = block

    def compose(self) -> ComposeResult:
        b = self._block
        with Container(id="ci-dialog"):
            yield Label("[bold]Compaction[/bold]", classes="ci-title")
            yield Label(
                f"{b.removed} message{'s' if b.removed != 1 else ''} removed  ·  "
                f"{_short_tokens(b.before_tokens)} → {_short_tokens(b.after_tokens)} tokens"
                f"  ·  {b.kind}",
                classes="ci-stats",
            )

            yield Label("Summary (kept in context)", classes="ci-section-label")
            with VerticalScroll(id="ci-summary"):
                if b.summary_text:
                    yield Static(
                        b.summary_text,
                        id="ci-summary-text",
                        markup=False,
                    )
                else:
                    yield Static(
                        "[dim](no LLM-generated summary — fallback marker only)[/dim]",
                        classes="ci-empty",
                        markup=True,
                    )

            yield Label("Compacted turns (removed from main chat)", classes="ci-section-label")
            with VerticalScroll(id="ci-turns"):
                turns = b.absorbed_turns
                if not turns:
                    yield Static(
                        "[dim](no turns were absorbed into this block)[/dim]",
                        classes="ci-empty",
                        markup=True,
                    )
                else:
                    for t in turns:
                        yield _AbsorbedTurnView(t)

            with Horizontal(classes="ci-buttons"):
                yield Button("Close", variant="primary", id="ci-close")

    def on_button_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
