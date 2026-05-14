"""Tests for idempotent tool retry in ToolExecutor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

from taui.tools.base import ToolCategory, ToolResult
from taui.tools.executor import _RETRY_DELAYS, Completed, ToolExecutor
from taui.tools.registry import ToolRegistry

# ── Flakey test tools ─────────────────────────────────────────────────────────


@dataclass
class FlakeyReadTool:
    """A read tool that fails N times then succeeds."""

    name: str = "flakey_read"
    description: str = "Flakey reader"
    category: ToolCategory = ToolCategory.FILE_READ
    schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    _fail_count: int = 0
    _attempts: int = 0

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self._attempts += 1
        if self._attempts <= self._fail_count:
            return ToolResult.fail(f"Transient error (attempt {self._attempts})")
        return ToolResult.ok(f"Success on attempt {self._attempts}")


@dataclass
class FlakeyWriteTool:
    """A write tool that fails — should NOT retry."""

    name: str = "flakey_write"
    description: str = "Flakey writer"
    category: ToolCategory = ToolCategory.FILE_WRITE
    schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    _attempts: int = 0

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self._attempts += 1
        return ToolResult.fail(f"Write error (attempt {self._attempts})")


@dataclass
class FlakeySearchTool:
    """A search tool that fails then succeeds — should retry."""

    name: str = "flakey_search"
    description: str = "Flakey searcher"
    category: ToolCategory = ToolCategory.SEARCH
    schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    _fail_count: int = 0
    _attempts: int = 0

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self._attempts += 1
        if self._attempts <= self._fail_count:
            return ToolResult.fail("Search failed")
        return ToolResult.ok("Found results")


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_executor(*tools) -> ToolExecutor:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return ToolExecutor(reg)


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestIdempotentRetry:
    async def test_read_tool_retries_on_failure(self):
        tool = FlakeyReadTool(_fail_count=2)
        executor = make_executor(tool)
        with patch("taui.tools.executor.asyncio.sleep"):
            outcome = await executor.run("c1", "flakey_read", {})
        assert isinstance(outcome, Completed)
        assert not outcome.result.error
        assert tool._attempts == 3  # failed twice, succeeded on third

    async def test_read_tool_gives_up_after_max_retries(self):
        tool = FlakeyReadTool(_fail_count=10)  # always fails
        executor = make_executor(tool)
        with patch("taui.tools.executor.asyncio.sleep"):
            outcome = await executor.run("c1", "flakey_read", {})
        assert isinstance(outcome, Completed)
        assert outcome.result.error
        assert tool._attempts == len(_RETRY_DELAYS) + 1  # 1 initial + retries

    async def test_write_tool_does_not_retry(self):
        tool = FlakeyWriteTool()
        executor = make_executor(tool)
        with patch("taui.tools.executor.asyncio.sleep") as mock_sleep:
            outcome = await executor.run("c1", "flakey_write", {})
        assert isinstance(outcome, Completed)
        assert outcome.result.error
        assert tool._attempts == 1  # no retries for write tools
        mock_sleep.assert_not_called()

    async def test_search_tool_retries(self):
        tool = FlakeySearchTool(_fail_count=1)
        executor = make_executor(tool)
        with patch("taui.tools.executor.asyncio.sleep"):
            outcome = await executor.run("c1", "flakey_search", {})
        assert isinstance(outcome, Completed)
        assert not outcome.result.error
        assert tool._attempts == 2

    async def test_successful_tool_no_retry(self):
        tool = FlakeyReadTool(_fail_count=0)  # succeeds immediately
        executor = make_executor(tool)
        with patch("taui.tools.executor.asyncio.sleep") as mock_sleep:
            outcome = await executor.run("c1", "flakey_read", {})
        assert isinstance(outcome, Completed)
        assert not outcome.result.error
        assert tool._attempts == 1
        mock_sleep.assert_not_called()

    async def test_retry_uses_correct_delay_sequence(self):
        tool = FlakeyReadTool(_fail_count=2)
        executor = make_executor(tool)
        with patch("taui.tools.executor.asyncio.sleep") as mock_sleep:
            await executor.run("c1", "flakey_read", {})
        # Should have slept twice (after attempt 1 and attempt 2)
        assert mock_sleep.call_count == 2
        assert mock_sleep.call_args_list[0][0][0] == _RETRY_DELAYS[0]
        assert mock_sleep.call_args_list[1][0][0] == _RETRY_DELAYS[1]

    async def test_duration_metadata_present(self):
        tool = FlakeyReadTool(_fail_count=0)
        executor = make_executor(tool)
        outcome = await executor.run("c1", "flakey_read", {})
        assert isinstance(outcome, Completed)
        assert "duration_ms" in outcome.result.metadata
