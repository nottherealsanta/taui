"""Tests for auto-recovery on ContextOverflowError."""
from __future__ import annotations

from typing import Any

import pytest

from taui.agent.loop import AgentLoop
from taui.agent.types import Message
from taui.llm_provider.errors import ContextOverflowError
from taui.llm_provider.types import ProviderTurnResult
from taui.tools.executor import ToolExecutor
from taui.tools.registry import ToolRegistry


class OverflowThenOkProvider:
    """Fails with overflow on first call, succeeds on second."""

    def __init__(self) -> None:
        self._calls = 0
        self.on_text_delta = None
        self.on_reasoning_delta = None

    async def create_turn(
        self,
        messages: list[dict[str, Any]],
        model: str = "mock",
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ProviderTurnResult:
        self._calls += 1
        if self._calls == 1:
            raise ContextOverflowError("context too long")
        return ProviderTurnResult(response_id=None, text="Recovered!", tool_calls=[])


class AlwaysOverflowProvider:
    """Always fails with overflow."""

    def __init__(self) -> None:
        self.on_text_delta = None
        self.on_reasoning_delta = None

    async def create_turn(
        self,
        messages: list[dict[str, Any]],
        model: str = "mock",
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ProviderTurnResult:
        raise ContextOverflowError("always too long")


def _make_executor() -> ToolExecutor:
    return ToolExecutor(ToolRegistry())


def _make_loop_with_history(provider: Any) -> AgentLoop:
    """Return a loop pre-populated with enough messages to trigger compaction.

    We need total tokens > 50% of DEFAULT_MAX_INPUT_TOKENS (180k) = 90k tokens.
    Rough estimate: 1 token ≈ 4 chars, so we need ~360k chars total.
    """
    loop = AgentLoop(llm=provider, executor=_make_executor())
    # Large repeated content to push well past the 50% compaction threshold
    chunk = "word " * 1000  # ~5000 chars ≈ 1250 tokens per message
    loop._messages = [Message(role="system", content="System prompt")]
    for i in range(80):  # 80 pairs × ~2500 tokens ≈ 200k tokens total
        loop._messages.append(Message(role="user", content=f"Q{i}: {chunk}"))
        loop._messages.append(Message(role="assistant", content=f"A{i}: {chunk}"))
    return loop


class TestAutoRecovery:
    @pytest.mark.asyncio
    async def test_recovers_after_compaction(self) -> None:
        """If first call overflows, compaction + retry succeeds."""
        provider = OverflowThenOkProvider()
        loop = _make_loop_with_history(provider)
        result = await loop.run("New question")
        assert result.text == "Recovered!"
        assert provider._calls == 2

    @pytest.mark.asyncio
    async def test_raises_if_still_overflows(self) -> None:
        """If compaction doesn't help, the error propagates."""
        provider = AlwaysOverflowProvider()
        loop = AgentLoop(llm=provider, executor=_make_executor())
        with pytest.raises(ContextOverflowError):
            await loop.run("Hi")

    @pytest.mark.asyncio
    async def test_compact_callback_fires_on_recovery(self) -> None:
        """The on_compact callback fires during auto-recovery."""
        provider = OverflowThenOkProvider()
        compactions: list[tuple[int, int, int]] = []

        def on_compact(removed: int, before: int, after: int) -> None:
            compactions.append((removed, before, after))

        loop = _make_loop_with_history(provider)
        loop._on_compact = on_compact
        await loop.run("Question")
        assert len(compactions) >= 1
        removed, before, after = compactions[-1]
        assert removed > 0
        assert after < before
