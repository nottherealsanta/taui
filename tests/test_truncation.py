"""Tests for output truncation and peek tool."""

from __future__ import annotations

import pytest

from taui.tools.builtins.peek import PeekTool
from taui.tools.truncation import TruncatedOutput, TruncationStore


class TestTruncationStore:
    def test_no_truncation_under_limit(self):
        store = TruncationStore(max_inline_bytes=100)
        result = store.maybe_truncate("short text")
        assert result == "short text"
        assert len(store.handles) == 0

    def test_truncation_over_limit(self):
        store = TruncationStore(max_inline_bytes=10)
        content = "a" * 100
        result = store.maybe_truncate(content, tool_name="bash")
        assert "[truncated;" in result
        assert 'handle="tr_' in result
        assert len(store.handles) == 1

    def test_peek_retrieves_content(self):
        store = TruncationStore(max_inline_bytes=10)
        content = "a" * 100
        store.maybe_truncate(content, tool_name="bash")
        handle = store.handles[0]
        peeked = store.peek(handle, offset=0, limit=50)
        assert peeked is not None
        assert "a" in peeked

    def test_peek_unknown_handle(self):
        store = TruncationStore()
        assert store.peek("nonexistent") is None

    def test_peek_with_offset(self):
        store = TruncationStore(max_inline_bytes=10)
        content = "abcdefghij" * 10  # 100 chars
        store.maybe_truncate(content)
        handle = store.handles[0]
        peeked = store.peek(handle, offset=50, limit=20)
        assert peeked is not None

    def test_clear(self):
        store = TruncationStore(max_inline_bytes=10)
        store.maybe_truncate("a" * 100)
        assert len(store.handles) == 1
        store.clear()
        assert len(store.handles) == 0

    def test_truncated_output_dataclass(self):
        entry = TruncatedOutput(
            handle="tr_abc",
            tool_name="bash",
            full_content="full",
            truncated_preview="prev",
        )
        assert entry.handle == "tr_abc"
        assert entry.tool_name == "bash"

    def test_peek_at_end_has_no_more_footer(self):
        store = TruncationStore(max_inline_bytes=10)
        content = "a" * 20
        store.maybe_truncate(content)
        handle = store.handles[0]
        # Peek past the end — no more footer
        peeked = store.peek(handle, offset=0, limit=1000)
        assert peeked is not None
        assert "KiB more" not in peeked

    def test_multiple_handles_independent(self):
        store = TruncationStore(max_inline_bytes=10)
        store.maybe_truncate("a" * 100, tool_name="tool1")
        store.maybe_truncate("b" * 100, tool_name="tool2")
        assert len(store.handles) == 2
        h1, h2 = store.handles
        assert store.peek(h1, offset=0, limit=50) is not None
        assert store.peek(h2, offset=0, limit=50) is not None

    def test_store_is_bounded_evicting_oldest(self):
        """A long session must not grow the store without bound: once the cap
        is exceeded the oldest entries are evicted (peek then returns None),
        while the most recent handles stay live."""
        store = TruncationStore(max_inline_bytes=10, max_entries=3)
        handles = [store.store("x" * 100, tool_name=f"t{i}") for i in range(5)]

        assert len(store.handles) == 3
        # The two oldest were evicted.
        assert store.peek(handles[0]) is None
        assert store.peek(handles[1]) is None
        # The three most recent survive.
        assert store.peek(handles[2]) is not None
        assert store.peek(handles[4]) is not None

    def test_maybe_truncate_also_respects_cap(self):
        store = TruncationStore(max_inline_bytes=10, max_entries=2)
        for i in range(4):
            store.maybe_truncate("y" * 100, tool_name=f"t{i}")
        assert len(store.handles) == 2


class TestPeekTool:
    @pytest.mark.asyncio
    async def test_peek_tool_success(self):
        store = TruncationStore(max_inline_bytes=10)
        store.maybe_truncate("a" * 100, tool_name="bash")
        handle = store.handles[0]

        tool = PeekTool()
        tool._truncation_store = store
        result = await tool.execute({"handle": handle})
        assert not result.error
        assert "a" in result.content

    @pytest.mark.asyncio
    async def test_peek_tool_missing_handle(self):
        store = TruncationStore()
        tool = PeekTool()
        tool._truncation_store = store
        result = await tool.execute({"handle": "nonexistent"})
        assert result.error

    @pytest.mark.asyncio
    async def test_peek_tool_no_store(self):
        tool = PeekTool()
        result = await tool.execute({"handle": "anything"})
        assert result.error

    @pytest.mark.asyncio
    async def test_peek_tool_with_offset_and_limit(self):
        store = TruncationStore(max_inline_bytes=10)
        store.maybe_truncate("x" * 200, tool_name="read")
        handle = store.handles[0]

        tool = PeekTool()
        tool._truncation_store = store
        result = await tool.execute({"handle": handle, "offset": 50, "limit": 30})
        assert not result.error
        assert "x" in result.content
