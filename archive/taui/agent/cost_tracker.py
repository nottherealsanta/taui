"""Per-session cost and token accounting.

Inspired by claw-code's CostTracker: maintains a running ledger of
input/output tokens and estimated USD cost for every LLM turn and tool
call within an agent session.  Emits ``cost_update`` events through the
AgentRunner event callback so the UI can display live cost information.

Usage::

    tracker = CostTracker(session_id="abc123")
    tracker.record_llm_turn(model="claude-sonnet-4-20250514", input_tokens=1200, output_tokens=400)
    tracker.record_tool_call(tool_name="bash", duration_ms=350)
    print(tracker.total_cost_usd)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


# ── Pricing table (USD per 1M tokens) ─────────────────────────────────────────
# Kept intentionally simple — add models as needed.  Prices are per 1 million
# tokens following Anthropic / OpenAI published pricing (as of early 2025).

_PRICING: dict[str, tuple[float, float]] = {
    # (input $/1M, output $/1M)
    # Anthropic
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-opus-4-20250514": (15.00, 75.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    "claude-3-haiku-20240307": (0.25, 1.25),
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "o1": (15.00, 60.00),
    "o1-mini": (3.00, 12.00),
    "o3-mini": (1.10, 4.40),
    # Fallback
    "_default": (3.00, 15.00),
}


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Estimate cost in USD for a single LLM turn."""
    # Try exact match, then prefix match, then default
    pricing = _PRICING.get(model)
    if pricing is None:
        for key, val in _PRICING.items():
            if key != "_default" and model.startswith(key):
                pricing = val
                break
    if pricing is None:
        pricing = _PRICING["_default"]

    input_rate, output_rate = pricing
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


@dataclass(slots=True)
class LLMTurnRecord:
    """One LLM turn's accounting entry."""

    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    timestamp: float  # time.monotonic()


@dataclass(slots=True)
class ToolCallRecord:
    """One tool call's accounting entry."""

    tool_name: str
    duration_ms: int
    timestamp: float


@dataclass(slots=True)
class CostTracker:
    """Accumulates token usage and cost for one agent session.

    Thread-safe for single-writer (the agent loop) — no locks needed.
    """

    session_id: str
    llm_turns: list[LLMTurnRecord] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)

    # Running totals (avoid re-summing on every access)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    total_tool_duration_ms: int = 0

    def record_llm_turn(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float | None = None,
    ) -> LLMTurnRecord:
        """Record tokens and cost for one LLM turn.

        If ``cost_usd`` is not provided, it is estimated from the pricing
        table.  Returns the record for event emission.
        """
        if cost_usd is None:
            cost_usd = estimate_cost_usd(model, input_tokens, output_tokens)

        record = LLMTurnRecord(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            timestamp=time.monotonic(),
        )
        self.llm_turns.append(record)
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost_usd += cost_usd
        return record

    def record_tool_call(
        self,
        *,
        tool_name: str,
        duration_ms: int,
    ) -> ToolCallRecord:
        """Record a tool execution for accounting."""
        record = ToolCallRecord(
            tool_name=tool_name,
            duration_ms=duration_ms,
            timestamp=time.monotonic(),
        )
        self.tool_calls.append(record)
        self.total_tool_duration_ms += duration_ms
        return record

    @property
    def turn_count(self) -> int:
        return len(self.llm_turns)

    @property
    def tool_call_count(self) -> int:
        return len(self.tool_calls)

    def to_dict(self) -> dict[str, Any]:
        """Snapshot for event payloads and persistence."""
        return {
            "session_id": self.session_id,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "total_tool_duration_ms": self.total_tool_duration_ms,
            "turn_count": self.turn_count,
            "tool_call_count": self.tool_call_count,
        }

    def summary(self) -> str:
        """Human-readable one-line summary."""
        return (
            f"tokens: {self.total_input_tokens:,}in / {self.total_output_tokens:,}out | "
            f"cost: ${self.total_cost_usd:.4f} | "
            f"turns: {self.turn_count} | "
            f"tools: {self.tool_call_count} ({self.total_tool_duration_ms:,}ms)"
        )
