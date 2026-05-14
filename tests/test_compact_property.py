"""Property tests for compact_messages — tool-call pairing invariant."""

from __future__ import annotations

import random
import string

from taui.agent.context import compact_messages
from taui.agent.types import Message
from taui.llm_provider.types import ProviderToolCall


def _random_id(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _make_conversation(n_exchanges: int = 5) -> list[Message]:
    """Build a synthetic conversation with n tool-call/result exchanges."""
    msgs: list[Message] = [
        Message(role="system", content="You are a helpful assistant." * 50),
    ]
    for _ in range(n_exchanges):
        msgs.append(Message(role="user", content="Do something. " * 20))
        call_id = f"call_{_random_id()}"
        msgs.append(Message(
            role="assistant",
            content="I'll use a tool.",
            tool_calls=[ProviderToolCall(
                call_id=call_id, name="bash", arguments={"command": "ls"},
            )],
        ))
        msgs.append(Message(
            role="tool",
            content="file1.py\nfile2.py",
            tool_call_id=call_id,
            name="bash",
        ))
        msgs.append(Message(role="assistant", content="Here are the results. " * 30))
    msgs.append(Message(role="user", content="Final question"))
    return msgs


def _assert_tool_pairing(messages: list[Message]) -> None:
    """Assert every tool_calls entry in remaining assistants has a matching tool response."""
    requested: dict[str, int] = {}  # call_id -> assistant msg index
    resolved: set[str] = set()
    for i, m in enumerate(messages):
        if m.tool_calls:
            for tc in m.tool_calls:
                requested[tc.call_id] = i
        if m.role == "tool" and m.tool_call_id:
            resolved.add(m.tool_call_id)
    # Every requested call_id in the remaining messages must have its response
    orphaned = set(requested.keys()) - resolved
    assert not orphaned, f"Orphaned tool calls without results: {orphaned}"


class TestCompactMessagesInvariant:
    def test_pairing_preserved_after_soft_compact(self):
        """Tool-call/result pairs survive soft compaction."""
        msgs = _make_conversation(10)
        removed = compact_messages(msgs, max_input_tokens=2000, soft_ratio=0.5, hard_ratio=0.9)
        assert removed > 0, "Expected some messages to be removed"
        _assert_tool_pairing(msgs)

    def test_pairing_preserved_after_hard_compact(self):
        """Tool-call/result pairs survive hard compaction."""
        msgs = _make_conversation(15)
        removed = compact_messages(msgs, max_input_tokens=500, soft_ratio=0.3, hard_ratio=0.5)
        assert removed > 0
        _assert_tool_pairing(msgs)

    def test_pairing_preserved_random_conversations(self):
        """Run multiple random conversations and verify invariant."""
        for seed in range(20):
            random.seed(seed)
            n = random.randint(3, 12)
            msgs = _make_conversation(n)
            budget = random.randint(300, 3000)
            compact_messages(msgs, max_input_tokens=budget, soft_ratio=0.4, hard_ratio=0.7)
            _assert_tool_pairing(msgs)

    def test_system_message_always_preserved(self):
        """System message is never dropped."""
        msgs = _make_conversation(8)
        compact_messages(msgs, max_input_tokens=200, soft_ratio=0.3, hard_ratio=0.5)
        assert any(m.role == "system" for m in msgs)

    def test_latest_user_message_preserved(self):
        """The last user message is always preserved."""
        msgs = _make_conversation(8)
        # The last user message content
        last_user = None
        for m in reversed(msgs):
            if m.role == "user":
                last_user = m.content
                break
        compact_messages(msgs, max_input_tokens=300, soft_ratio=0.3, hard_ratio=0.5)
        user_msgs = [m for m in msgs if m.role == "user"]
        assert any(m.content == last_user for m in user_msgs)

    def test_no_compaction_needed(self):
        """When under budget, nothing is removed."""
        msgs = _make_conversation(2)
        removed = compact_messages(msgs, max_input_tokens=1_000_000)
        assert removed == 0
        _assert_tool_pairing(msgs)

    def test_empty_messages(self):
        """Empty message list doesn't crash."""
        msgs: list[Message] = []
        removed = compact_messages(msgs, max_input_tokens=100)
        assert removed == 0
