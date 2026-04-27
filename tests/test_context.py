"""Tests for taui.agent.context — compaction."""

from taui.agent.context import (
    compact_messages,
    estimate_message_tokens,
    estimate_total_tokens,
)
from taui.agent.loop import Message


class TestEstimateTokens:
    def test_simple_message(self):
        msg = Message(role="user", content="Hello world")
        tokens = estimate_message_tokens(msg)
        assert tokens > 0

    def test_empty_content(self):
        msg = Message(role="system")
        tokens = estimate_message_tokens(msg)
        assert tokens >= 1  # At least 1

    def test_total_tokens(self):
        msgs = [
            Message(role="system", content="You are helpful."),
            Message(role="user", content="What is 2+2?"),
        ]
        total = estimate_total_tokens(msgs)
        assert total > 0
        assert total == sum(estimate_message_tokens(m) for m in msgs)


class TestCompaction:
    def test_no_compaction_under_budget(self):
        msgs = [
            Message(role="system", content="System."),
            Message(role="user", content="Hi."),
        ]
        removed = compact_messages(msgs, max_input_tokens=100_000)
        assert removed == 0

    def test_compacts_when_over_budget(self):
        # Build a conversation that exceeds a small budget
        msgs = [Message(role="system", content="System prompt.")]
        for i in range(100):
            msgs.append(Message(role="user", content=f"Message {i} " * 100))
            msgs.append(Message(role="assistant", content=f"Response {i} " * 100))

        original_count = len(msgs)
        removed = compact_messages(msgs, max_input_tokens=5_000)
        assert removed > 0
        assert len(msgs) < original_count

    def test_preserves_system_prompt(self):
        msgs = [Message(role="system", content="System.")]
        for i in range(50):
            msgs.append(Message(role="user", content=f"Msg {i} " * 200))
            msgs.append(Message(role="assistant", content=f"Reply {i} " * 200))

        compact_messages(msgs, max_input_tokens=2_000)
        assert msgs[0].role == "system"
        assert msgs[0].content == "System."

    def test_preserves_latest_user_message(self):
        msgs = [
            Message(role="system", content="System."),
            Message(role="user", content="Old question " * 200),
            Message(role="assistant", content="Old answer " * 200),
            Message(role="user", content="LATEST QUESTION"),
        ]
        compact_messages(msgs, max_input_tokens=500)
        user_msgs = [m for m in msgs if m.role == "user"]
        assert any("LATEST QUESTION" in (m.content or "") for m in user_msgs)

    def test_inserts_summary_marker(self):
        msgs = [Message(role="system", content="System.")]
        for i in range(50):
            msgs.append(Message(role="user", content=f"Msg {i} " * 200))
            msgs.append(Message(role="assistant", content=f"Reply {i} " * 200))

        compact_messages(msgs, max_input_tokens=2_000)
        summaries = [m for m in msgs if "context trimmed" in (m.content or "").lower()
                     or "compacted" in (m.content or "").lower()]
        assert len(summaries) >= 1

    def test_no_duplicate_summary(self):
        msgs = [Message(role="system", content="System.")]
        for i in range(50):
            msgs.append(Message(role="user", content=f"Msg {i} " * 200))

        compact_messages(msgs, max_input_tokens=2_000)
        compact_messages(msgs, max_input_tokens=2_000)
        summaries = [m for m in msgs if "compacted" in (m.content or "").lower()]
        assert len(summaries) <= 1
