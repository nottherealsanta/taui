"""Visual snapshot tests for ``ChatInput`` rich-text-movement keys.

These render a minimal harness containing only the ``ChatInput``, drive a
key sequence, and capture the final SVG so a human can eyeball cursor and
selection placement against the saved baseline.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.pilot import Pilot

from taui.tui.widgets.attachments_bar import AttachmentsBar
from taui.tui.widgets.chat_input import ChatInput
from taui.tui.widgets.info2 import Info2


TERMINAL_SIZE = (60, 6)
SEED_TEXT = "hello world foo bar"


class _Harness(App):
    CSS = """
    Screen { align: center middle; }
    AttachmentsBar { display: none; }
    Info2 { display: none; }
    ChatInput {
        width: 50;
        min-height: 3;
        max-height: 5;
        padding: 0 1;
        border: round $primary;
    }
    """

    def compose(self) -> ComposeResult:
        yield AttachmentsBar(id="attachments-bar")
        yield ChatInput(id="chat-input")
        yield Info2(id="info2")


def _make_app() -> _Harness:
    return _Harness()


async def _seed(pilot: Pilot) -> None:
    """Mount-time seed: set text + cursor + focus, then settle the UI."""
    ci = pilot.app.query_one(ChatInput)
    ci.text = SEED_TEXT
    ci.focus()
    ci.move_cursor((0, 0))
    await pilot.pause()


def test_visual_initial_cursor_at_start(snap_compare):
    """Baseline: cursor at the start of the text."""

    async def run(pilot: Pilot) -> None:
        await _seed(pilot)

    assert snap_compare(_make_app(), run_before=run, terminal_size=TERMINAL_SIZE)


def test_visual_alt_right_lands_after_first_word(snap_compare):
    async def run(pilot: Pilot) -> None:
        await _seed(pilot)
        await pilot.press("alt+right")
        await pilot.pause()

    assert snap_compare(_make_app(), run_before=run, terminal_size=TERMINAL_SIZE)


def test_visual_alt_shift_right_selects_first_word(snap_compare):
    async def run(pilot: Pilot) -> None:
        await _seed(pilot)
        await pilot.press("alt+shift+right")
        await pilot.pause()

    assert snap_compare(_make_app(), run_before=run, terminal_size=TERMINAL_SIZE)


def test_visual_super_right_jumps_to_line_end(snap_compare):
    async def run(pilot: Pilot) -> None:
        await _seed(pilot)
        await pilot.press("super+right")
        await pilot.pause()

    assert snap_compare(_make_app(), run_before=run, terminal_size=TERMINAL_SIZE)


def test_visual_super_shift_right_selects_whole_line(snap_compare):
    async def run(pilot: Pilot) -> None:
        await _seed(pilot)
        await pilot.press("super+shift+right")
        await pilot.pause()

    assert snap_compare(_make_app(), run_before=run, terminal_size=TERMINAL_SIZE)


def test_visual_word_select_then_type_replaces(snap_compare):
    async def run(pilot: Pilot) -> None:
        await _seed(pilot)
        await pilot.press("alt+shift+right")
        await pilot.press("X")
        await pilot.pause()

    assert snap_compare(_make_app(), run_before=run, terminal_size=TERMINAL_SIZE)


def test_visual_alt_backspace_deletes_last_word(snap_compare):
    async def run(pilot: Pilot) -> None:
        await _seed(pilot)
        await pilot.press("super+right")  # jump to end first
        await pilot.press("alt+backspace")
        await pilot.pause()

    assert snap_compare(_make_app(), run_before=run, terminal_size=TERMINAL_SIZE)


def test_visual_super_backspace_clears_line(snap_compare):
    async def run(pilot: Pilot) -> None:
        await _seed(pilot)
        await pilot.press("super+right")
        await pilot.press("super+backspace")
        await pilot.pause()

    assert snap_compare(_make_app(), run_before=run, terminal_size=TERMINAL_SIZE)
