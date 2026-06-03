"""Tests for session picker tree rendering."""

from __future__ import annotations

from taui.tui.screens.session_picker import (
    SessionPickerScreen,
    _build_tree_order,
    _fallback_name,
    _preview_text,
    _session_prompt,
    _time_ago,
)


class TestBuildTreeOrder:
    def test_flat_sessions(self):
        """Sessions without parents stay flat."""
        sessions = [
            {"session_id": "a", "last_active": 3.0},
            {"session_id": "b", "last_active": 2.0},
        ]
        result = _build_tree_order(sessions)
        assert len(result) == 2
        assert result[0]["depth"] == 0
        assert result[1]["depth"] == 0

    def test_parent_child(self):
        """Child session is nested under parent."""
        sessions = [
            {"session_id": "parent", "last_active": 2.0},
            {
                "session_id": "child",
                "last_active": 1.0,
                "parent_session_id": "parent",
            },
        ]
        result = _build_tree_order(sessions)
        assert len(result) == 2
        assert result[0]["session"]["session_id"] == "parent"
        assert result[0]["depth"] == 0
        assert result[1]["session"]["session_id"] == "child"
        assert result[1]["depth"] == 1

    def test_nested_tree(self):
        """Grandchild nesting works."""
        sessions = [
            {"session_id": "root", "last_active": 3.0},
            {
                "session_id": "child",
                "last_active": 2.0,
                "parent_session_id": "root",
            },
            {
                "session_id": "grandchild",
                "last_active": 1.0,
                "parent_session_id": "child",
            },
        ]
        result = _build_tree_order(sessions)
        assert len(result) == 3
        assert result[2]["depth"] == 2

    def test_orphan_treated_as_root(self):
        """Child whose parent is not in the set is treated as root."""
        sessions = [
            {
                "session_id": "orphan",
                "last_active": 1.0,
                "parent_session_id": "missing",
            },
        ]
        result = _build_tree_order(sessions)
        assert len(result) == 1
        assert result[0]["depth"] == 0


class TestSessionPrompt:
    def test_root_no_prefix(self):
        session = {
            "session_id": "abc123",
            "description": "Test session",
            "mode": "normal",
            "message_count": 5,
            "last_active": 0,
        }
        text = _session_prompt(session, depth=0)
        plain = str(text)
        assert "Test session" in plain
        assert "├─" not in plain

    def test_child_has_prefix(self):
        session = {
            "session_id": "child1",
            "description": "Child",
            "mode": "normal",
            "message_count": 1,
            "last_active": 0,
        }
        text = _session_prompt(session, depth=1)
        plain = str(text)
        assert "├─" in plain

    def test_extensions_mode_tag(self):
        session = {
            "session_id": "ext1",
            "description": "Ext session",
            "mode": "extensions",
            "message_count": 0,
            "last_active": 0,
        }
        text = _session_prompt(session, depth=0)
        assert "[ext]" in str(text)


class TestSessionSearchAndPreview:
    def test_content_search_requires_toggle(self):
        screen = SessionPickerScreen(
            [
                {
                    "session_id": "abc123",
                    "description": "Metadata only",
                    "first_message": "",
                }
            ]
        )
        screen._content_cache["abc123"] = "needle from transcript"

        assert screen._filter("needle") == []
        screen._content_search = True
        assert [s["session_id"] for s in screen._filter("needle")] == ["abc123"]

    def test_preview_text_includes_session_and_content(self):
        preview = _preview_text(
            {
                "session_id": "abc123",
                "description": "Refactor flow",
                "message_count": 2,
                "last_active": 0.0,
            },
            "User: hello\n\nAssistant: hi",
        )

        assert "Refactor flow" in preview
        assert "abc123" in preview
        assert "Assistant: hi" in preview


class TestHelpers:
    def test_fallback_name_unnamed(self):
        assert _fallback_name({}) == "(unnamed)"

    def test_fallback_name_with_timestamp(self):
        name = _fallback_name({"created_at": 1700000000.0})
        assert "2023" in name

    def test_time_ago_just_now(self):
        import time

        assert _time_ago(time.time()) == "just now"

    def test_time_ago_zero(self):
        assert _time_ago(0) == "unknown"
