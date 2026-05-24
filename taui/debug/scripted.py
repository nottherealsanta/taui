"""Runtime scripted LLM provider, driveable over the debug MCP server.

Mirrors ``tests/scenarios/scripted_provider.py`` but lives inside the
package so the live TUI can use it without depending on the test tree.

``AgentLoop`` only needs two things from a provider:

1. ``await provider.create_turn(messages, model, tools=...)`` returning a
   ``ProviderTurnResult``.
2. Optional ``provider.on_text_delta`` / ``provider.on_reasoning_delta``
   attributes that the loop sets to receive streaming deltas.

The ``ScriptedProvider`` plays back a queue of ``Turn`` objects. Each
turn can emit text/reasoning deltas (with optional inter-chunk delay),
return final text + tool calls, or raise an exception to simulate
provider errors. New turns can be appended at any time so an external
driver (the MCP debug client) can react to in-flight UI state.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from taui.llm_provider.types import ProviderToolCall, ProviderTurnResult, Usage


@dataclass(slots=True)
class ScriptedToolCall:
    name: str
    arguments: dict[str, Any]
    call_id: str | None = None

    def to_provider(self, fallback_id: str) -> ProviderToolCall:
        return ProviderToolCall(
            call_id=self.call_id or fallback_id,
            name=self.name,
            arguments=self.arguments,
        )


@dataclass(slots=True)
class Turn:
    text: str = ""
    text_deltas: list[str] = field(default_factory=list)
    reasoning_deltas: list[str] = field(default_factory=list)
    tool_calls: list[ScriptedToolCall] = field(default_factory=list)
    usage: Usage | None = None
    stop_reason: str = "stop"
    delta_delay: float = 0.0
    raises: BaseException | None = None
    response_id: str | None = None


@dataclass(slots=True)
class _CallRecord:
    messages: list[Any]
    model: str
    tools: Any
    kwargs: dict[str, Any]


class ScriptedProvider:
    """Plays back queued turns; appends safe-by-default empty turns when exhausted."""

    def __init__(
        self,
        turns: list[Turn] | None = None,
        *,
        default_usage: Usage | None = None,
    ) -> None:
        self._turns: list[Turn] = list(turns or [])
        self._default_usage = default_usage or Usage(input_tokens=10, output_tokens=5)
        self._idx = 0
        self.calls: list[_CallRecord] = []
        self.on_text_delta: Callable[[str], None] | None = None
        self.on_reasoning_delta: Callable[[str], None] | None = None

    # ── script management ───────────────────────────────────────────────

    def add(self, turn: Turn) -> None:
        self._turns.append(turn)

    def extend(self, turns: list[Turn]) -> None:
        self._turns.extend(turns)

    @property
    def remaining(self) -> int:
        return max(0, len(self._turns) - self._idx)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    # ── provider contract ───────────────────────────────────────────────

    async def create_turn(
        self,
        messages: list[Any],
        model: str,
        *,
        tools: Any = None,
        **kwargs: Any,
    ) -> ProviderTurnResult:
        self.calls.append(
            _CallRecord(messages=messages, model=model, tools=tools, kwargs=kwargs)
        )

        # Wait briefly for a turn to be pushed so a test driver can
        # "react" — push a turn after observing the request. After the
        # grace period, return a benign empty turn so the agent loop
        # settles rather than hanging.
        deadline_loops = 50  # 50 * 100ms = 5s
        while self._idx >= len(self._turns) and deadline_loops > 0:
            await asyncio.sleep(0.1)
            deadline_loops -= 1

        if self._idx >= len(self._turns):
            return ProviderTurnResult(
                response_id=None,
                text="",
                tool_calls=[],
                usage=self._default_usage,
                stop_reason="stop",
            )

        turn = self._turns[self._idx]
        self._idx += 1

        await _emit_deltas(
            turn.reasoning_deltas, self.on_reasoning_delta, turn.delta_delay
        )
        await _emit_deltas(turn.text_deltas, self.on_text_delta, turn.delta_delay)

        if turn.raises is not None:
            raise turn.raises

        tool_calls = [
            sc.to_provider(fallback_id=f"call_{self._idx}_{i}")
            for i, sc in enumerate(turn.tool_calls)
        ]

        # Real providers' final text is the join of streamed deltas. When
        # text_deltas are given without an explicit text, mirror that so
        # the agent loop sees a coherent assistant message.
        final_text = turn.text or "".join(turn.text_deltas)

        return ProviderTurnResult(
            response_id=turn.response_id,
            text=final_text,
            tool_calls=tool_calls,
            usage=turn.usage or self._default_usage,
            stop_reason=turn.stop_reason,
        )


async def _emit_deltas(
    deltas: list[str],
    callback: Callable[[str], None] | Callable[[str], Awaitable[None]] | None,
    delay: float,
) -> None:
    if not deltas or callback is None:
        return
    for i, delta in enumerate(deltas):
        if i > 0 and delay > 0:
            await asyncio.sleep(delay)
        result = callback(delta)
        if asyncio.iscoroutine(result):
            await result
