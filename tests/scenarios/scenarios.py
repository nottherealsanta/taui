"""Pre-built provider scenarios.

Each factory returns a fully configured `ScriptedProvider`. Tests can grab one
by name and feed it into `Session`, `AgentLoop`, or `TauiApp` to exercise a
specific real-world LLM behavior without touching the network.

Keep these factories small and intention-revealing. If a test needs a one-off
shape, build a `ScriptedProvider` directly with explicit `Turn`s rather than
adding a near-duplicate factory here.
"""

from __future__ import annotations

from taui.llm_provider.errors import (
    AuthExpiredError,
    ContextOverflowError,
    QuotaExceededError,
    TransientProviderError,
)
from taui.llm_provider.types import Usage

from .scripted_provider import ScriptedProvider, ScriptedToolCall, Turn, raises


def happy_path(reply: str = "Hello!") -> ScriptedProvider:
    """Single non-streaming reply with a final text and stop."""
    return ScriptedProvider([Turn(text=reply)])


def streamed_reply(reply: str = "Hello, world!", *, chunk_size: int = 4) -> ScriptedProvider:
    """Reply delivered as text deltas, then a final text."""
    deltas = [reply[i : i + chunk_size] for i in range(0, len(reply), chunk_size)]
    return ScriptedProvider([Turn(text=reply, text_deltas=deltas)])


def slow_stream(reply: str = "slow words here", *, delta_delay: float = 0.02) -> ScriptedProvider:
    """Streamed reply with delay between chunks — exercises throttling/UI redraw."""
    deltas = reply.split(" ")
    deltas = [(d + " ") for d in deltas[:-1]] + [deltas[-1]]
    return ScriptedProvider(
        [Turn(text=reply, text_deltas=deltas, delta_delay=delta_delay)]
    )


def with_reasoning(
    reasoning: str = "thinking about this...",
    reply: str = "Done.",
) -> ScriptedProvider:
    """Reasoning deltas before the final answer (Copilot/Codex-style)."""
    return ScriptedProvider(
        [
            Turn(
                text=reply,
                reasoning_deltas=[reasoning],
                text_deltas=[reply],
                usage=Usage(input_tokens=20, output_tokens=10, reasoning_tokens=15),
            )
        ]
    )


def with_tool_call(
    tool_name: str = "read",
    arguments: dict | None = None,
    final_reply: str = "Here's what I found.",
) -> ScriptedProvider:
    """One tool call, then a final reply once the tool result returns."""
    return ScriptedProvider(
        [
            Turn(
                tool_calls=[ScriptedToolCall(name=tool_name, arguments=arguments or {})],
                stop_reason="tool_use",
            ),
            Turn(text=final_reply, text_deltas=[final_reply]),
        ]
    )


def parallel_tool_calls(
    names: list[str] | None = None,
    final_reply: str = "All done.",
) -> ScriptedProvider:
    """Multiple tool calls in a single turn — exercises parallel execution."""
    names = names or ["read", "ls", "grep"]
    return ScriptedProvider(
        [
            Turn(
                tool_calls=[ScriptedToolCall(name=n, arguments={}) for n in names],
                stop_reason="tool_use",
            ),
            Turn(text=final_reply),
        ]
    )


def malformed_tool_arguments(
    tool_name: str = "read",
    final_reply: str = "I'll try a different approach.",
) -> ScriptedProvider:
    """Tool call with bogus arguments — exercises tool-error -> recovery path."""
    return ScriptedProvider(
        [
            Turn(
                tool_calls=[
                    ScriptedToolCall(name=tool_name, arguments={"unexpected": "field"})
                ],
                stop_reason="tool_use",
            ),
            Turn(text=final_reply),
        ]
    )


def rate_limit_then_recover(reply: str = "Recovered.") -> ScriptedProvider:
    """First call raises a transient/rate-limit error; second succeeds."""
    return ScriptedProvider(
        [
            raises(TransientProviderError("rate limited", status_code=429, retry_after=0.0)),
            Turn(text=reply),
        ]
    )


def context_overflow_then_recover(reply: str = "After compaction.") -> ScriptedProvider:
    """First call raises ContextOverflowError; loop should compact and retry."""
    return ScriptedProvider(
        [
            raises(ContextOverflowError("prompt is too long", status_code=400)),
            Turn(text=reply),
        ]
    )


def auth_expired() -> ScriptedProvider:
    """Auth token expired — terminal for the turn."""
    return ScriptedProvider([raises(AuthExpiredError("token expired", status_code=401))])


def quota_exceeded(resets_in_seconds: int = 3600) -> ScriptedProvider:
    """Hard usage cap reached — terminal for the turn."""
    return ScriptedProvider(
        [
            raises(
                QuotaExceededError(
                    "monthly quota reached",
                    status_code=429,
                    resets_in_seconds=resets_in_seconds,
                )
            )
        ]
    )


def empty_response() -> ScriptedProvider:
    """Provider returns nothing — empty text, no tool calls."""
    return ScriptedProvider([Turn(text="")])
