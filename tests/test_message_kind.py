"""Tests for Message.kind and contextual message handling."""

from __future__ import annotations

from taui.agent.context import _preserved_indexes, compact_messages
from taui.agent.types import Message


class TestMessageKind:
    def test_default_kind_is_user(self):
        msg = Message(role="user", content="hello")
        assert msg.kind == "user"

    def test_steer_kind(self):
        msg = Message(role="user", content="focus on X", kind="steer")
        assert msg.kind == "steer"

    def test_contextual_kind(self):
        msg = Message(role="user", content="<file content>", kind="contextual")
        assert msg.kind == "contextual"


class TestPreservationPreference:
    def test_real_user_preserved_over_steer(self):
        """When both real user and steer messages exist, preserve the real one."""
        msgs = [
            Message(role="system", content="sys"),
            Message(role="user", content="real question", kind="user"),
            Message(role="assistant", content="response"),
            Message(role="user", content="steer msg", kind="steer"),
        ]
        preserved = _preserved_indexes(msgs)
        # Index 1 (real user) should be preserved, not just index 3
        assert 1 in preserved

    def test_only_steer_still_preserved(self):
        """If all user messages are steer, one is still preserved."""
        msgs = [
            Message(role="system", content="sys"),
            Message(role="user", content="steer1", kind="steer"),
            Message(role="assistant", content="ok"),
            Message(role="user", content="steer2", kind="steer"),
        ]
        preserved = _preserved_indexes(msgs)
        # At least one user message should be preserved
        user_preserved = [i for i in preserved if msgs[i].role == "user"]
        assert len(user_preserved) >= 1

    def test_contextual_droppable_before_real(self):
        """Contextual messages are dropped before real user messages."""
        msgs = [
            Message(role="system", content="sys prompt " * 100),
            Message(role="user", content="file content " * 200, kind="contextual"),
            Message(role="assistant", content="I see the file " * 100),
            Message(role="user", content="Now edit line 5"),
        ]
        compact_messages(msgs, max_input_tokens=200, soft_ratio=0.3, hard_ratio=0.5)
        # The real user message should survive
        user_msgs = [m for m in msgs if m.role == "user" and m.kind == "user"]
        assert len(user_msgs) >= 1
        assert "edit line 5" in user_msgs[0].content
