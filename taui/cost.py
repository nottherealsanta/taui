"""Per-session cost and token accounting.

Maintains a running ledger of input/output tokens and estimated USD cost
for every LLM turn within a session.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# ── Pricing table (USD per 1M tokens) ─────────────────────────────────────────

_PRICING: dict[str, tuple[float, float]] = {
    # (input $/1M, output $/1M)
    # Anthropic
    "claude-sonnet-4.6": (3.00, 15.00),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-opus-4-20250514": (15.00, 75.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "o1": (15.00, 60.00),
    "o3-mini": (1.10, 4.40),
    # Fallback
    "_default": (3.00, 15.00),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a single LLM turn."""
    pricing = _PRICING.get(model)
    if pricing is None:
        # Try prefix match
        for key, val in _PRICING.items():
            if key != "_default" and model.startswith(key):
                pricing = val
                break
    if pricing is None:
        pricing = _PRICING["_default"]

    input_rate, output_rate = pricing
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


@dataclass(slots=True)
class TurnRecord:
    """One LLM turn's accounting entry."""

    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    timestamp: float


@dataclass(slots=True)
class CostTracker:
    """Accumulates token usage and cost for one session."""

    turns: list[TurnRecord] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0

    def record(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float | None = None,
    ) -> TurnRecord:
        """Record tokens and cost for one LLM turn."""
        if cost_usd is None:
            cost_usd = estimate_cost(model, input_tokens, output_tokens)

        record = TurnRecord(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            timestamp=time.monotonic(),
        )
        self.turns.append(record)
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost_usd += cost_usd
        return record

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    def summary(self) -> str:
        """Human-readable summary."""
        return (
            f"tokens: {self.total_input_tokens:,}in / "
            f"{self.total_output_tokens:,}out | "
            f"cost: ${self.total_cost_usd:.4f} | "
            f"turns: {self.turn_count}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "turn_count": self.turn_count,
        }
