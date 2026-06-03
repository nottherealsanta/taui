"""Visual snapshot tests for the dynamic widget rendering prototype.

These exercise the standalone prototype app (`scripts/widget_rendering_prototype.py`)
to verify the collapse/expand and peek-more behaviour before wiring it into
the main TUI. Run via:

    uv run python -m pytest tests/test_widget_rendering_prototype.py

To refresh baselines after an intentional change:

    uv run python -m pytest tests/test_widget_rendering_prototype.py --snapshot-update
"""

from __future__ import annotations

from textual.pilot import Pilot

from scripts.widget_rendering_prototype import (
    ToolRow,
    TurnContainer,
    WidgetRenderingApp,
)


async def _settle(pilot: Pilot, ticks: int = 4) -> None:
    for _ in range(ticks):
        await pilot.pause()


def test_three_turns_oldest_collapsed(snap_compare):
    """With three turns, the oldest auto-collapses and the latest two stay open."""

    app = WidgetRenderingApp()

    async def setup(pilot: Pilot) -> None:
        await _settle(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(100, 30))


def test_oldest_expand_sticks(snap_compare):
    """Clicking the oldest turn re-expands it and the sticky flag prevents
    the autocollapse from immediately closing it again on the next turn."""

    app = WidgetRenderingApp()

    async def setup(pilot: Pilot) -> None:
        await _settle(pilot)
        # The oldest is turn-0; expand it.
        turn0 = pilot.app.query_one("#turn-0", TurnContainer)
        turn0.expand(sticky=True)
        # Add a new turn; oldest should remain expanded because it's sticky.
        await pilot.app.action_next_turn()
        await _settle(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(100, 30))


def test_tool_peek_expanded(snap_compare):
    """Toggling a tool row shows the full output below the one-line summary."""

    app = WidgetRenderingApp()

    async def setup(pilot: Pilot) -> None:
        await _settle(pilot)
        # Pick the tool row inside the *current* (last) turn so it's visible.
        rows = list(pilot.app.query(ToolRow))
        assert rows, "prototype should mount tool rows"
        target = rows[-1]
        target.remove_class("collapsed-output")
        await _settle(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(100, 30))
