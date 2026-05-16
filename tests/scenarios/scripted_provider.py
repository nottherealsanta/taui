"""ScriptedProvider — a deterministic, scriptable LLM provider for tests.

`AgentLoop` only needs two things from a provider:

1. ``await provider.create_turn(messages, model, tools=...)`` returning a
   ``ProviderTurnResult``.
2. Optional ``provider.on_text_delta`` / ``provider.on_reasoning_delta``
   attributes that the loop sets to receive streaming deltas during a turn.

This module exposes a `ScriptedProvider` that plays back a list of `Turn`
objects. Each `Turn` describes one full create_turn call:

- text/reasoning deltas to emit (with optional inter-chunk delay)
- final text and tool calls to return
- usage values
- or an exception to raise *instead* of returning (to simulate provider errors
  like rate limiting, context overflow, auth expiry, quota)

The provider also records every call it received so tests can assert on
prompt content and tool-call ordering.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from taui.llm_provider.types import ProviderToolCall, ProviderTurnResult, Usage


@dataclass(slots=True)
class ScriptedToolCall:
    """A tool call to return from a scripted turn."""

    name: str
    arguments: dict[str, Any]
    call_id: str | None = None  # auto-generated if None

    def to_provider(self, fallback_id: str) -> ProviderToolCall:
        return ProviderToolCall(
            call_id=self.call_id or fallback_id,
            name=self.name,
            arguments=self.arguments,
        )


@dataclass(slots=True)
class Turn:
    """One scripted LLM turn.

    If ``raises`` is set, the provider raises it instead of returning a result.
    Deltas (if any) are still emitted before the raise — that mirrors real
    providers that surface a partial stream and then fail.
    """

    text: str = ""
    text_deltas: list[str] = field(default_factory=list)
    reasoning_deltas: list[str] = field(default_factory=list)
    tool_calls: list[ScriptedToolCall] = field(default_factory=list)
    usage: Usage | None = None
    stop_reason: str = "stop"
    delta_delay: float = 0.0  # seconds between deltas (for slow-stream tests)
    raises: BaseException | None = None
    response_id: str | None = None


def raises(exc: BaseException) -> Turn:
    """Shorthand: a turn that just raises an exception."""
    return Turn(raises=exc)


@dataclass(slots=True)
class _CallRecord:
    messages: list[Any]
    model: str
    tools: Any
    kwargs: dict[str, Any]


class ScriptedProvider:
    """Plays back a list of `Turn` definitions in order.

    Once the script is exhausted, further calls return a benign "done" turn so
    `AgentLoop` can settle. Pass ``strict=True`` to raise `IndexError` instead.

    Streaming callbacks (`on_text_delta` / `on_reasoning_delta`) are set by
    `AgentLoop` before each call and cleared afterwards. The provider invokes
    them in order for any configured deltas.
    """

    def __init__(
        self,
        turns: list[Turn] | None = None,
        *,
        strict: bool = False,
        default_usage: Usage | None = None,
    ) -> None:
        self._turns: list[Turn] = list(turns or [])
        self._strict = strict
        self._default_usage = default_usage or Usage(input_tokens=10, output_tokens=5)
        self._idx = 0
        self.calls: list[_CallRecord] = []
        # AgentLoop will set these attributes around each call:
        self.on_text_delta: Callable[[str], None] | None = None
        self.on_reasoning_delta: Callable[[str], None] | None = None

    # ── script management ────────────────────────────────────────────────

    def extend(self, turns: list[Turn]) -> None:
        self._turns.extend(turns)

    def add(self, turn: Turn) -> None:
        self._turns.append(turn)

    @property
    def remaining(self) -> int:
        return max(0, len(self._turns) - self._idx)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    # ── provider contract ────────────────────────────────────────────────

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

        if self._idx >= len(self._turns):
            if self._strict:
                raise IndexError(
                    f"ScriptedProvider exhausted: call #{self._idx + 1} has no turn"
                )
            return ProviderTurnResult(
                response_id=None,
                text="done",
                tool_calls=[],
                usage=self._default_usage,
                stop_reason="stop",
            )

        turn = self._turns[self._idx]
        self._idx += 1

        # Emit reasoning deltas first (mirrors how providers usually order them).
        await _emit_deltas(turn.reasoning_deltas, self.on_reasoning_delta, turn.delta_delay)
        await _emit_deltas(turn.text_deltas, self.on_text_delta, turn.delta_delay)

        if turn.raises is not None:
            raise turn.raises

        tool_calls = [
            sc.to_provider(fallback_id=f"call_{self._idx}_{i}")
            for i, sc in enumerate(turn.tool_calls)
        ]

        return ProviderTurnResult(
            response_id=turn.response_id,
            text=turn.text,
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
