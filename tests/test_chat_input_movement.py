"""Tests for rich text input movement / selection in ``ChatInput``.

These verify the VS Code / macOS-style key bindings layered on top of
Textual's ``TextArea``:

* ``alt+left/right`` for word-wise cursor movement
* ``alt+shift+left/right`` for word-wise selection extension
* ``super+left/right`` (cmd on macOS) for line start / end
* ``super+up/down`` for document start / end
* ``alt+backspace`` / ``super+backspace`` for word- / line-delete
* typing over a selection replaces the selection
"""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from taui.tui.widgets.attachments_bar import AttachmentsBar
from taui.tui.widgets.chat_input import ChatInput
from taui.tui.widgets.info2 import Info2


class _Harness(App):
    def compose(self) -> ComposeResult:
        yield AttachmentsBar(id="attachments-bar")
        yield ChatInput(id="chat-input")
        yield Info2(id="info2")


async def _seed(ci: ChatInput, text: str, row: int = 0, col: int = 0) -> None:
    ci.text = text
    ci.move_cursor((row, col))


class TestWordMovement:
    @pytest.mark.asyncio
    async def test_alt_right_jumps_word(self) -> None:
        app = _Harness()
        async with app.run_test() as pilot:
            ci = app.query_one(ChatInput)
            ci.focus()
            await _seed(ci, "hello world", 0, 0)
            await pilot.press("alt+right")
            # Textual's word_right lands at the end of the current word.
            assert ci.cursor_location == (0, 5)

    @pytest.mark.asyncio
    async def test_alt_left_jumps_word(self) -> None:
        app = _Harness()
        async with app.run_test() as pilot:
            ci = app.query_one(ChatInput)
            ci.focus()
            await _seed(ci, "hello world", 0, 11)
            await pilot.press("alt+left")
            # word_left from end-of-text lands at the start of the last word.
            assert ci.cursor_location == (0, 6)

    @pytest.mark.asyncio
    async def test_alt_shift_right_selects_word(self) -> None:
        app = _Harness()
        async with app.run_test() as pilot:
            ci = app.query_one(ChatInput)
            ci.focus()
            await _seed(ci, "hello world", 0, 0)
            await pilot.press("alt+shift+right")
            assert ci.selection.start == (0, 0)
            assert ci.selection.end == (0, 5)
            assert ci.selected_text == "hello"

    @pytest.mark.asyncio
    async def test_alt_shift_left_selects_word(self) -> None:
        app = _Harness()
        async with app.run_test() as pilot:
            ci = app.query_one(ChatInput)
            ci.focus()
            await _seed(ci, "hello world", 0, 11)
            await pilot.press("alt+shift+left")
            assert ci.selection.start == (0, 11)
            assert ci.selection.end == (0, 6)
            assert ci.selected_text == "world"


class TestLineMovement:
    @pytest.mark.asyncio
    async def test_super_left_goes_to_line_start(self) -> None:
        app = _Harness()
        async with app.run_test() as pilot:
            ci = app.query_one(ChatInput)
            ci.focus()
            await _seed(ci, "hello world", 0, 7)
            await pilot.press("super+left")
            assert ci.cursor_location == (0, 0)

    @pytest.mark.asyncio
    async def test_super_right_goes_to_line_end(self) -> None:
        app = _Harness()
        async with app.run_test() as pilot:
            ci = app.query_one(ChatInput)
            ci.focus()
            await _seed(ci, "hello world", 0, 3)
            await pilot.press("super+right")
            assert ci.cursor_location == (0, 11)

    @pytest.mark.asyncio
    async def test_super_shift_right_selects_to_line_end(self) -> None:
        app = _Harness()
        async with app.run_test() as pilot:
            ci = app.query_one(ChatInput)
            ci.focus()
            await _seed(ci, "hello world", 0, 6)
            await pilot.press("super+shift+right")
            assert ci.selected_text == "world"

    @pytest.mark.asyncio
    async def test_super_shift_left_selects_to_line_start(self) -> None:
        app = _Harness()
        async with app.run_test() as pilot:
            ci = app.query_one(ChatInput)
            ci.focus()
            await _seed(ci, "hello world", 0, 5)
            await pilot.press("super+shift+left")
            assert ci.selected_text == "hello"


class TestDocumentMovement:
    @pytest.mark.asyncio
    async def test_super_up_goes_to_doc_start(self) -> None:
        app = _Harness()
        async with app.run_test() as pilot:
            ci = app.query_one(ChatInput)
            ci.focus()
            await _seed(ci, "line1\nline2\nline3", 2, 3)
            await pilot.press("super+up")
            assert ci.cursor_location == (0, 0)

    @pytest.mark.asyncio
    async def test_super_down_goes_to_doc_end(self) -> None:
        app = _Harness()
        async with app.run_test() as pilot:
            ci = app.query_one(ChatInput)
            ci.focus()
            await _seed(ci, "line1\nline2\nline3", 0, 0)
            await pilot.press("super+down")
            assert ci.cursor_location == (2, 5)

    @pytest.mark.asyncio
    async def test_super_shift_down_selects_to_doc_end(self) -> None:
        app = _Harness()
        async with app.run_test() as pilot:
            ci = app.query_one(ChatInput)
            ci.focus()
            await _seed(ci, "ab\ncd", 0, 1)
            await pilot.press("super+shift+down")
            assert ci.selected_text == "b\ncd"


class TestWordAndLineDelete:
    @pytest.mark.asyncio
    async def test_alt_backspace_deletes_word_left(self) -> None:
        app = _Harness()
        async with app.run_test() as pilot:
            ci = app.query_one(ChatInput)
            ci.focus()
            await _seed(ci, "hello world", 0, 11)
            await pilot.press("alt+backspace")
            assert ci.text == "hello "

    @pytest.mark.asyncio
    async def test_alt_delete_deletes_word_right(self) -> None:
        app = _Harness()
        async with app.run_test() as pilot:
            ci = app.query_one(ChatInput)
            ci.focus()
            await _seed(ci, "hello world", 0, 0)
            await pilot.press("alt+delete")
            # delete_word_right deletes "hello" leaving " world".
            assert ci.text == " world"

    @pytest.mark.asyncio
    async def test_super_backspace_deletes_to_line_start(self) -> None:
        app = _Harness()
        async with app.run_test() as pilot:
            ci = app.query_one(ChatInput)
            ci.focus()
            await _seed(ci, "hello world", 0, 11)
            await pilot.press("super+backspace")
            assert ci.text == ""


class TestReplaceOnType:
    @pytest.mark.asyncio
    async def test_typing_replaces_selected_text(self) -> None:
        app = _Harness()
        async with app.run_test() as pilot:
            ci = app.query_one(ChatInput)
            ci.focus()
            await _seed(ci, "hello world", 0, 0)
            # Select "hello" via alt+shift+right, then type X.
            await pilot.press("alt+shift+right")
            assert ci.selected_text == "hello"
            await pilot.press("X")
            assert ci.text == "X world"

    @pytest.mark.asyncio
    async def test_backspace_deletes_selection(self) -> None:
        app = _Harness()
        async with app.run_test() as pilot:
            ci = app.query_one(ChatInput)
            ci.focus()
            await _seed(ci, "hello world", 0, 0)
            await pilot.press("alt+shift+right")
            await pilot.press("backspace")
            assert ci.text == " world"


class TestSelectAll:
    @pytest.mark.asyncio
    async def test_super_a_selects_all(self) -> None:
        app = _Harness()
        async with app.run_test() as pilot:
            ci = app.query_one(ChatInput)
            ci.focus()
            await _seed(ci, "abc def", 0, 0)
            await pilot.press("super+a")
            assert ci.selected_text == "abc def"
