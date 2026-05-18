"""Paste-as-attachment behavior on the chat input.

Verifies that multi-line pastes become attachment pills instead of being
inlined into the text area, and that the AttachmentsBar shows the pill.
"""

from __future__ import annotations

import pytest
from textual.events import Paste

from tests.scenarios import scenarios
from tests.scenarios.tui_harness import use_scripted_provider
from taui.tui.widgets.attachments_bar import AttachmentsBar
from taui.tui.widgets.chat_input import ChatInput


def _make_app(monkeypatch, tmp_path):
    provider = scenarios.happy_path("(unused)")
    return use_scripted_provider(monkeypatch, tmp_path, provider)


async def _wait_until_ready(pilot, *, timeout: float = 2.0) -> None:
    import asyncio

    app = pilot.app
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        await pilot.pause()
        if (
            not getattr(app, "_session_initializing", True)
            and getattr(app, "_session", None) is not None
        ):
            await pilot.pause()
            return
    raise TimeoutError("Session never finished initializing")


@pytest.mark.asyncio
async def test_multi_line_paste_becomes_pill_only(tmp_path, monkeypatch):
    """Pasting 5+ lines should attach a pill and leave the input empty."""
    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        chat_input = pilot.app.query_one(ChatInput)
        bar = pilot.app.query_one(AttachmentsBar)
        assert chat_input.text == ""
        assert bar.count == 0

        big = "\n".join(f"line {i}" for i in range(10))
        chat_input.focus()
        await pilot.pause()
        chat_input.post_message(Paste(big))
        await pilot.pause()
        await pilot.pause()

        assert chat_input.pending_paste_count == 1, (
            f"expected one pending paste, got {chat_input.pending_paste_count}"
        )
        assert bar.count == 1, f"expected one pill, got {bar.count}"
        assert chat_input.text == "", (
            f"text area should be empty after attach, got {chat_input.text!r}"
        )


@pytest.mark.asyncio
async def test_short_paste_stays_inline(tmp_path, monkeypatch):
    """Pasting a short single line should NOT create an attachment."""
    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        chat_input = pilot.app.query_one(ChatInput)
        bar = pilot.app.query_one(AttachmentsBar)

        chat_input.focus()
        await pilot.pause()
        chat_input.post_message(Paste("hi there"))
        await pilot.pause()
        await pilot.pause()

        assert chat_input.pending_paste_count == 0
        assert bar.count == 0
        assert "hi there" in chat_input.text
