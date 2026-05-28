"""Standalone visual preview for the CompactionBlock + inspector modal.

Builds a minimal Textual app that mounts a chat-like scroll with a few
fake "remaining" turns plus a ``CompactionBlock`` carrying absorbed
turn snapshots. Saves an SVG of the chat view, then opens the
inspector modal and saves a second SVG.

Run via::

    uv run python scripts/compaction_ui_preview.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from taui.tui.widgets.compaction_block import AbsorbedTurn, CompactionBlock
from taui.tui.widgets.turn_container import TurnContainer
from taui.session_replay import ReplayItem  # noqa: E402  (load after store init)


_SUMMARY = """## Goal
- Build the new compaction UI so the main chat reflects what's in context.

## Constraints & Preferences
- Gray clickable block replaces compacted turns.
- Modal shows summary + absorbed turns.

## Progress
### Done
- Added CompactionBlock widget.
- Added CompactionInspectorScreen modal.

### In Progress
- Visual verification.

### Blocked
- (none)

## Key Decisions
- Capture AbsorbedTurn snapshots up-front so we can detach the live widgets.

## Next Steps
- Snap a screenshot, eyeball the result.

## Critical Context
- Compaction fires from agent_loop._maybe_compact() before each LLM call.

## Relevant Files
- taui/tui/widgets/compaction_block.py: the gray block.
- taui/tui/screens/compaction_inspector.py: the modal.
"""


def _absorbed_turn(turn_id: int, user_text: str, reply_text: str) -> AbsorbedTurn:
    return AbsorbedTurn(
        user_text=user_text,
        image_note="",
        turn_id=turn_id,
        replay_items=[
            ReplayItem(kind="assistant", text=reply_text, model="scripted"),
        ],
        total_tokens=120,
        tool_count=0,
        model="scripted",
        duration_s=0.4,
        agent_id="demo",
    )


class CompactionPreviewApp(App[None]):
    CSS = """
    Screen { background: #0d0d0d; }
    #chat-log {
        height: 1fr;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="chat-log")

    async def on_mount(self) -> None:
        chat = self.query_one("#chat-log", VerticalScroll)
        block = CompactionBlock(
            removed=12,
            before_tokens=142_300,
            after_tokens=38_100,
            summary_text=_SUMMARY,
            absorbed=[
                _absorbed_turn(0, "How does the agent loop trigger compaction?",
                               "It checks token budget before each LLM call..."),
                _absorbed_turn(1, "Show me where the turn widgets live.",
                               "TurnContainer in taui/tui/widgets/turn_container.py..."),
                _absorbed_turn(2, "OK now let's wire the gray block.",
                               "Detaching the prior turns and mounting a CompactionBlock."),
            ],
            kind="threshold",
        )
        await chat.mount(block)

        live_turn = TurnContainer(
            "And here's the live turn that stays in the main chat.",
            "",
            turn_id=99,
        )
        await chat.mount(live_turn)


async def _main() -> None:
    app = CompactionPreviewApp()
    out_dir = Path(__file__).resolve().parent.parent / "tmp"
    out_dir.mkdir(exist_ok=True)
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        await pilot.pause()
        app.save_screenshot(str(out_dir / "compaction_block.svg"))
        # Click the block to open the inspector modal.
        block = app.query_one(CompactionBlock)
        await pilot.click(block)
        await pilot.pause()
        await pilot.pause()
        app.save_screenshot(str(out_dir / "compaction_inspector.svg"))


if __name__ == "__main__":
    asyncio.run(_main())
