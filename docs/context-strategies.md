# 10.2 Context Strategies

Managing context is what separates a good harness from a great one. An LLM's input window
is finite. If the conversation grows unchecked, the provider rejects the request with a
context overflow error, the agent stalls, or older details silently fall off the edge of
what the model can see. A deliberate context strategy keeps the conversation coherent,
cost-effective, and within budget.

---

## How Compaction Works

The primary compaction function is `compact_messages()` in `taui/agent/context.py`:

```python
def compact_messages(
    messages: list[Message],
    max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS,  # 180_000
    soft_ratio: float = COMPACTION_SOFT_RATIO,          # 0.80
    hard_ratio: float = COMPACTION_HARD_RATIO,          # 0.90
    tokenizer: Tokenizer | None = None,
) -> int:
    ...
```

It operates in two phases:

1. **Soft phase** — while estimated token count exceeds `max_input_tokens * soft_ratio`
   (default 144 000 tokens), drop the oldest droppable message and re-evaluate.
2. **Hard phase** — if the list is still above `max_input_tokens * hard_ratio`
   (default 162 000 tokens) after the soft phase, continue dropping.

After any messages are removed, a summary marker is inserted immediately after the system
prompt:

```
[Context compacted: N older messages removed to stay within token budget.]
```

The function modifies `messages` in place and returns the number of messages removed.

### What is preserved

`_preserved_indexes()` in `taui/agent/context.py` marks messages that must not be dropped:

- The most recent **system** message.
- The most recent **user** message.
- All **unresolved tool calls** — both the assistant message that issued the call and any
  partial tool results for the same `call_id`.

Everything else is a candidate for dropping, oldest first.

---

## The Default Strategy: DropOldest

`DropOldestStrategy` in `taui/agent/context_strategy.py` is registered automatically and
is the strategy used by all sessions unless overridden:

```python
@dataclass(slots=True)
class DropOldestStrategy:
    name: str = "drop_oldest"

    def prepare(self, messages: list[Message], max_tokens: int) -> list[Message]:
        from taui.agent.context import compact_messages
        compact_messages(messages, max_input_tokens=max_tokens)
        return messages

    def on_turn_result(self, usage: dict[str, Any]) -> None:
        pass
```

It delegates entirely to `compact_messages()` with default soft/hard ratios and no custom
tokenizer. It is the right choice for most workloads.

---

## How the Tokenizer Works

`Tokenizer` lives in `taui/agent/tokenizer.py`. Its default estimator is:

```python
def _default_estimator(text: str) -> int:
    return max(1, len(text) // 4 + 1)
```

That is approximately four characters per token — a reasonable heuristic for English prose
and code. The `Tokenizer` class wraps this with an EMA calibration mechanism:

```python
def calibrate(self, estimated_tokens: int, actual_tokens: int) -> None:
    if estimated_tokens <= 0 or actual_tokens <= 0:
        return
    ratio = actual_tokens / estimated_tokens
    # Exponential moving average, alpha = 0.3
    self._calibration_factor = 0.7 * self._calibration_factor + 0.3 * ratio
```

After each LLM turn, `AgentLoop` calls `tokenizer.calibrate(estimated, actual)` where
`actual` comes from the provider's `Usage.input_tokens`. Over several turns the factor
converges toward the true ratio for this model and content mix, making compaction
thresholds progressively more accurate.

All estimates from `tokenizer.estimate(text)` are multiplied by `_calibration_factor`
before being returned.

---

## Auto-Recovery on ContextOverflowError

When the provider rejects a request with `ContextOverflowError` (defined in
`taui/llm_provider/errors.py`), `AgentLoop._call_llm()` in `taui/agent/loop.py`
performs an aggressive compaction and retries once:

```python
except ContextOverflowError:
    before = estimate_total_tokens(self._messages, self._tokenizer)
    removed = compact_messages(
        self._messages,
        soft_ratio=0.50,
        hard_ratio=0.60,
        tokenizer=self._tokenizer,
    )
    if removed:
        after = estimate_total_tokens(self._messages, self._tokenizer)
        logger.info(
            "Auto-recovery compaction agent_id=%s removed=%d tokens=%d->%d",
            self.agent_id, removed, before, after,
        )
        if self._on_compact:
            self._on_compact(removed, before, after)
        messages = self._build_llm_messages()
    return await self._llm.create_turn(messages, self._model, tools=tools)
```

The recovery ratios (0.50/0.60) are much tighter than the normal pass, so the retry
almost always succeeds. If the retry also overflows — for example because a single message
is larger than the window — `ContextOverflowError` propagates to the caller and the loop
terminates with an error state.

---

## Writing a Custom Strategy

Implement the `ContextStrategy` protocol from `taui/agent/context_strategy.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from taui.agent.types import Message
from taui.agent.context import compact_messages, estimate_total_tokens


@dataclass(slots=True)
class BudgetWindowStrategy:
    """Maintain a rolling token budget window.

    Keeps the conversation within `target_tokens` by dropping oldest messages.
    Tracks actual vs estimated token drift via on_turn_result.
    """

    name: str = "budget_window"
    target_tokens: int = 60_000
    _drift_factor: float = field(default=1.0, repr=False, compare=False)

    def prepare(self, messages: list[Message], max_tokens: int) -> list[Message]:
        # Use a tighter soft limit based on target_tokens
        effective_max = min(max_tokens, int(self.target_tokens / self._drift_factor))
        compact_messages(
            messages,
            max_input_tokens=effective_max,
            soft_ratio=0.85,
            hard_ratio=0.95,
        )
        return messages

    def on_turn_result(self, usage: dict[str, Any]) -> None:
        actual = usage.get("input_tokens", 0)
        if actual > 0:
            # Adjust drift estimate with EMA
            self._drift_factor = 0.8 * self._drift_factor + 0.2 * (actual / self.target_tokens)
```

Protocol requirements:

| Member | Type | Purpose |
|--------|------|---------|
| `name` | `str` | Unique identifier used by the registry |
| `prepare(messages, max_tokens)` | method | Called before every LLM request; modify in place and return the list |
| `on_turn_result(usage)` | method | Called after every completed turn; `usage` keys: `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens` |

`prepare()` receives the live `messages` list — modifications are reflected in the
running conversation. It must return the same list (possibly modified).

---

## Registering a Custom Strategy via Extension

```python
# .taui/extensions/budget_context.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from taui.agent.types import Message
from taui.agent.context import compact_messages


@dataclass(slots=True)
class BudgetWindowStrategy:
    name: str = "budget_window"
    target_tokens: int = 60_000
    _drift_factor: float = field(default=1.0, repr=False, compare=False)

    def prepare(self, messages: list[Message], max_tokens: int) -> list[Message]:
        effective_max = min(max_tokens, int(self.target_tokens / self._drift_factor))
        compact_messages(messages, max_input_tokens=effective_max,
                         soft_ratio=0.85, hard_ratio=0.95)
        return messages

    def on_turn_result(self, usage: dict[str, Any]) -> None:
        actual = usage.get("input_tokens", 0)
        if actual > 0:
            self._drift_factor = 0.8 * self._drift_factor + 0.2 * (actual / self.target_tokens)


def register(ctx) -> None:
    if ctx.context is None:
        return
    ctx.context.register(BudgetWindowStrategy(target_tokens=80_000))
```

`ctx.context` is a `ContextStrategyRegistry` instance
(`taui/agent/context_strategy.py:ContextStrategyRegistry`). Calling `.register()` with a
strategy whose `name` matches an existing entry replaces it; registering with name
`"drop_oldest"` replaces the built-in default for the session.

After writing the extension, run `/reload` in Taui to activate it.

---

## Inspecting Token Usage

Press `Ctrl+X` in the TUI to open the context breakdown screen. It shows:

- Estimated total input tokens for the current conversation.
- Per-message breakdown with role and token count.
- Calibration factor (how much the char/4 heuristic has been adjusted).
- How far the conversation is from the soft and hard compaction thresholds.

This screen is the fastest way to verify that a custom strategy is behaving as expected
before deploying it to a real workload.
