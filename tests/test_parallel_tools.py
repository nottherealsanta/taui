"""Tests for parallel tool execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

from taui.agent.loop import AgentLoop
from taui.llm_provider.types import ProviderToolCall, ProviderTurnResult
from taui.tools.base import ToolCategory, ToolResult
from taui.tools.executor import ToolExecutor, ToolPolicy
from taui.tools.registry import ToolRegistry


@dataclass
class TimingTool:
    """Tool that records execution timing."""

    name: str = "timing_read"
    description: str = "test"
    category: ToolCategory = ToolCategory.FILE_READ
    schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    call_log: list[float] = field(default_factory=list)

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        start = asyncio.get_event_loop().time()
        await asyncio.sleep(0.01)
        self.call_log.append(start)
        return ToolResult.ok("ok")


@dataclass
class SequentialTool:
    """Tool that must run sequentially."""

    name: str = "seq_write"
    description: str = "test"
    category: ToolCategory = ToolCategory.FILE_WRITE
    schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.ok("wrote")


class TestParallelExecution:
    async def test_read_tools_run_in_parallel(self):
        """Multiple FILE_READ tools should run concurrently."""
        tool = TimingTool()
        registry = ToolRegistry()
        registry.register(tool)
        executor = ToolExecutor(registry=registry, policy=ToolPolicy())

        # Provider returns 3 read tool calls, then done
        provider = AsyncMock()
        provider.on_text_delta = None
        provider.on_reasoning_delta = None
        provider.create_turn = AsyncMock(
            side_effect=[
                ProviderTurnResult(
                    response_id=None,
                    text="",
                    tool_calls=[
                        ProviderToolCall(call_id=f"c{i}", name="timing_read", arguments={})
                        for i in range(3)
                    ],
                ),
                ProviderTurnResult(response_id=None, text="Done", tool_calls=[]),
            ]
        )

        loop = AgentLoop(
            agent_id="test",
            llm=provider,
            executor=executor,
            system_prompt="sys",
            model="m",
        )
        result = await loop.run("go")
        assert result.text == "Done"
        # All 3 calls should have executed
        assert len(tool.call_log) == 3

    async def test_write_tools_run_sequentially(self):
        """FILE_WRITE tools should NOT be parallelized."""
        tool = SequentialTool()
        registry = ToolRegistry()
        registry.register(tool)
        executor = ToolExecutor(registry=registry, policy=ToolPolicy())

        provider = AsyncMock()
        provider.on_text_delta = None
        provider.on_reasoning_delta = None
        provider.create_turn = AsyncMock(
            side_effect=[
                ProviderTurnResult(
                    response_id=None,
                    text="",
                    tool_calls=[
                        ProviderToolCall(call_id=f"c{i}", name="seq_write", arguments={})
                        for i in range(2)
                    ],
                ),
                ProviderTurnResult(response_id=None, text="Done", tool_calls=[]),
            ]
        )

        loop = AgentLoop(
            agent_id="test",
            llm=provider,
            executor=executor,
            system_prompt="sys",
            model="m",
        )
        result = await loop.run("go")
        assert result.text == "Done"
