"""Tests for the `@<file>` autocomplete: scanner ranking and ChatInput hook-up."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult

from taui.tui.widgets.at_completer import AtCompleter
from taui.tui.widgets.attachments_bar import AttachmentsBar
from taui.tui.widgets.chat_input import ChatInput
from taui.tui.widgets.info2 import Info2, Info2Mode


def _make_tree(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("x = 1")
    (root / "src" / "utils.py").write_text("y = 2")
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text("z = 3")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "ignored.js").write_text("nope")
    (root / ".hidden").mkdir()
    (root / ".hidden" / "secret").write_text("nope")
    (root / "README.md").write_text("hi")


class TestAtCompleter:
    def test_walk_excludes_common_ignored_dirs(self, tmp_path: Path) -> None:
        _make_tree(tmp_path)
        completer = AtCompleter(tmp_path)
        all_paths = {rel for rel, _ in completer.complete("", limit=100)}
        assert "README.md" in all_paths
        assert "src" in all_paths
        assert "tests" in all_paths
        assert not any("node_modules" in p for p in all_paths)
        assert not any(p.startswith(".hidden") for p in all_paths)

    def test_prefix_match_ranks_higher_than_substring(self, tmp_path: Path) -> None:
        _make_tree(tmp_path)
        completer = AtCompleter(tmp_path)
        results = completer.complete("src", limit=10)
        # "src" path-prefix wins; "tests/test_app.py" should NOT come before src
        assert results[0][0] == "src"

    def test_filename_prefix_match_beats_substring(self, tmp_path: Path) -> None:
        _make_tree(tmp_path)
        completer = AtCompleter(tmp_path)
        # "app" is a filename prefix for src/app.py and tests/test_app.py
        # (filename in test_app.py is "test_app.py", doesn't start with "app").
        rels = [r for r, _ in completer.complete("app", limit=10)]
        assert "src/app.py" in rels
        # `tests/test_app.py` matches as a substring, so it appears later.
        assert rels.index("src/app.py") < rels.index("tests/test_app.py")

    def test_is_dir_flag_preserved(self, tmp_path: Path) -> None:
        _make_tree(tmp_path)
        completer = AtCompleter(tmp_path)
        by_path = dict(completer.complete("", limit=100))
        assert by_path["src"] is True
        assert by_path["README.md"] is False


class _Harness(App):
    def compose(self) -> ComposeResult:
        yield AttachmentsBar(id="attachments-bar")
        yield ChatInput(id="chat-input")
        yield Info2(id="info2")


class TestChatInputAtCompletion:
    @pytest.mark.asyncio
    async def test_at_token_detection_mid_sentence(self) -> None:
        app = _Harness()
        async with app.run_test():
            ci = app.query_one(ChatInput)
            ci.text = "hey @src/ut and more"
            ci.move_cursor((0, len("hey @src/ut")))
            tok = ci._at_token_at_cursor()
            assert tok is not None
            start, end, prefix = tok
            assert ci.text[start:end] == "@src/ut"
            assert prefix == "src/ut"

    @pytest.mark.asyncio
    async def test_at_token_requires_word_boundary(self) -> None:
        app = _Harness()
        async with app.run_test():
            ci = app.query_one(ChatInput)
            ci.text = "user@example"
            ci.move_cursor((0, len(ci.text)))
            assert ci._at_token_at_cursor() is None

    @pytest.mark.asyncio
    async def test_accept_strips_at_token_and_posts_attach(self) -> None:
        app = _Harness()
        async with app.run_test():
            ci = app.query_one(ChatInput)
            ci.set_at_completer(
                lambda prefix: [("src/app.py", False), ("tests", True)]
            )
            ci.text = "look at @src"
            ci.move_cursor((0, len(ci.text)))
            assert ci._show_at_completion() is True
            info2 = app.query_one(Info2)
            assert info2.mode == Info2Mode.COMPLETIONS

            attached: list[tuple[str, bool]] = []

            original_post = ci.post_message

            def _capture(msg):
                if isinstance(msg, ChatInput.AtAttachRequested):
                    attached.append((msg.path, msg.is_dir))
                    return True
                return original_post(msg)

            ci.post_message = _capture
            ci._accept_at_completion()
            assert ci.text == "look at "
            assert attached == [("src/app.py", False)]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
