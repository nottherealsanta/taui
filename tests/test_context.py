"""Tests for taui.agent.context — compaction."""

from __future__ import annotations

from typing import Any

import pytest

from taui.agent.context import (
    async_compact_messages,
    compact_messages,
    estimate_message_tokens,
    estimate_total_tokens,
    prune_tool_outputs,
    select_head_and_tail,
)
from taui.agent.loop import Message
from taui.agent.tokenizer import Tokenizer
from taui.llm_provider.types import ProviderTurnResult


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


class TestPruneToolOutputs:
    def test_prune_protect_recent_user_turn(self):
        # Tools in the current/most recent user turn must NOT be pruned.
        # Here we have 1 user turn at the end.
        msgs = [
            Message(role="system", content="System."),
            Message(role="user", content="Query 1"),
            Message(role="assistant", content="Thinking..."),
            Message(role="tool", name="read_file", content="A" * 50_000, tool_call_id="call1"),
        ]
        pruned = prune_tool_outputs(msgs, max_tool_tokens=10_000)
        assert pruned == 0
        assert "Truncated" not in msgs[3].content

    def test_prune_older_large_tool_outputs(self):
        # Tools in older turns that exceed budget should be pruned.
        # User turns: 3 (Query 1, Query 2 and Query 3)
        msgs = [
            Message(role="system", content="System."),
            Message(role="user", content="Query 1"),
            Message(role="assistant", content="Thinking..."),
            Message(role="tool", name="read_file", content="A" * 50_000, tool_call_id="call1"),
            Message(role="user", content="Query 2"),
            Message(role="assistant", content="Thinking..."),
            Message(role="tool", name="read_file", content="B" * 5_000, tool_call_id="call2"),
            Message(role="user", content="Query 3"),
            Message(role="assistant", content="Thinking..."),
            Message(role="tool", name="read_file", content="C" * 5_000, tool_call_id="call3"),
        ]
        pruned = prune_tool_outputs(msgs, max_tool_tokens=10_000)
        assert pruned == 1
        assert "[Truncated tool output" in msgs[3].content
        assert msgs[6].content == "B" * 5_000  # Protect within latest 2 turns
        assert msgs[9].content == "C" * 5_000  # Protect within latest 2 turns

    def test_prune_protects_skill(self):
        # 'skill' tool outputs must never be pruned.
        msgs = [
            Message(role="system", content="System."),
            Message(role="user", content="Query 1"),
            Message(role="assistant", content="Thinking..."),
            Message(role="tool", name="skill", content="A" * 50_000, tool_call_id="call1"),
            Message(role="user", content="Query 2"),
        ]
        pruned = prune_tool_outputs(msgs, max_tool_tokens=10_000)
        assert pruned == 0
        assert msgs[3].content == "A" * 50_000

    def test_prune_stops_at_summary_marker(self):
        # Scanning stops when we hit a past summary or compaction system message.
        msgs = [
            Message(role="system", content="System."),
            Message(role="user", content="Query 1"),
            Message(role="assistant", content="Thinking..."),
            Message(role="tool", name="read_file", content="A" * 50_000, tool_call_id="call1"),
            Message(role="system", content="[Context compacted: 5 older messages removed]"),
            Message(role="user", content="Query 2"),
            Message(role="assistant", content="Thinking..."),
            Message(role="tool", name="read_file", content="B" * 5_000, tool_call_id="call2"),
            Message(role="user", content="Query 3"),
        ]
        pruned = prune_tool_outputs(msgs, max_tool_tokens=10_000)
        # Even though msg[3] is large and old, the marker is at index 4 which stops scanning
        assert pruned == 0
        assert msgs[3].content == "A" * 50_000


class TestSelectHeadAndTail:
    def test_select_head_and_tail_basic(self):
        msgs = [
            Message(role="system", content="System."),
            Message(role="user", content="Query 1"),
            Message(role="assistant", content="Reply 1"),
            Message(role="user", content="Query 2"),
            Message(role="assistant", content="Reply 2"),
            Message(role="user", content="Query 3"),
        ]
        head, tail = select_head_and_tail(msgs, max_input_tokens=10_000, tail_turns=1)
        assert len(head) > 0
        assert len(tail) > 0
        # The tail must contain the very last turn (Query 3)
        assert tail[0].content == "Query 3"


class MockLLM:
    def __init__(self, text: str, fail: bool = False) -> None:
        self.text = text
        self.fail = fail
        self.calls = []

    async def create_turn(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
    ) -> ProviderTurnResult:
        self.calls.append((messages, model, temperature))
        if self.fail:
            raise Exception("LLM call failed")
        return ProviderTurnResult(
            response_id="res_1",
            text=self.text,
            tool_calls=[],
        )


class TestAsyncCompactMessages:
    @pytest.mark.asyncio
    async def test_async_compact_success(self):
        # We need enough tokens in head to trigger summarization
        msgs = [
            Message(role="system", content="System."),
            Message(role="user", content="Query 1 " * 500),
            Message(role="assistant", content="Reply 1 " * 500),
            Message(role="user", content="Query 2 " * 500),
            Message(role="assistant", content="Reply 2 " * 500),
            Message(role="user", content="Query 3"),
        ]
        tokenizer = Tokenizer()
        summary_text = (
            "## Goal\n- Summarize query\n\n"
            "## Constraints & Preferences\n- None\n\n"
            "## Progress\n### Done\n- Completed step\n"
            "### In Progress\n- None\n### Blocked\n- None\n\n"
            "## Key Decisions\n- None\n\n"
            "## Next Steps\n- None\n\n"
            "## Critical Context\n- None\n\n"
            "## Relevant Files\n- None"
        )
        llm = MockLLM(text=summary_text)
        
        # Call async compact with small max_input_tokens to force it
        removed = await async_compact_messages(
            msgs,
            tokenizer=tokenizer,
            llm=llm,
            model="mock-model",
            provider_name="copilot",
            max_input_tokens=1_000,
        )
        assert removed > 0
        # The list must now contain: System message, Summary system message, and the protected tail
        assert len(msgs) >= 3
        assert msgs[0].role == "system"
        assert msgs[1].role == "system"
        assert "## Goal" in msgs[1].content
        assert msgs[-1].content == "Query 3"

    @pytest.mark.asyncio
    async def test_async_compact_fallback(self):
        # If the LLM fails or doesn't produce a proper summary,
        # it should fall back to sync compaction
        msgs = [
            Message(role="system", content="System."),
            Message(role="user", content="Query 1 " * 500),
            Message(role="assistant", content="Reply 1 " * 500),
            Message(role="user", content="Query 2 " * 500),
            Message(role="assistant", content="Reply 2 " * 500),
            Message(role="user", content="Query 3"),
        ]
        tokenizer = Tokenizer()
        llm = MockLLM(text="This is a bad response", fail=True)
        
        original_count = len(msgs)
        removed = await async_compact_messages(
            msgs,
            tokenizer=tokenizer,
            llm=llm,
            model="mock-model",
            provider_name="copilot",
            max_input_tokens=1_000,
        )
        assert removed > 0
        # Should have been compacted synchronously with the sync marker
        assert len(msgs) < original_count
        assert any("compacted" in (m.content or "").lower() for m in msgs)
