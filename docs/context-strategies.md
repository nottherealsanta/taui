# Context Strategies

Taui manages the LLM's token budget by compacting the conversation history before each
call. The core algorithm is in `taui/agent/context.py`. Pluggable strategies are
registered in `taui/agent/context_strategy.py`.

## Token Estimation

```python
def estimate_message_tokens(msg: Message, tokenizer: Tokenizer | None = None) -> int
def estimate_total_tokens(messages: list[Message], tokenizer: Tokenizer | None = None) -> int
```

Default estimation: `max(1, total_chars // 4 + 1)`. When a `Tokenizer` is provided,
character counts are passed to `tokenizer.estimate()`.

`AgentLoop` holds a `Tokenizer` instance that is **calibrated** after each LLM response:

```python
self._tokenizer.calibrate(estimated, actual_input)
```

Over time, the tokenizer's estimates drift toward the provider's actual token counts.

## Compaction Thresholds

```python
DEFAULT_MAX_INPUT_TOKENS = 180_000
COMPACTION_SOFT_RATIO    = 0.80   # trigger at 80% = 144,000 tokens
COMPACTION_HARD_RATIO    = 0.90   # force at 90%  = 162,000 tokens
```

## `compact_messages` Algorithm

```python
def compact_messages(
    messages: list[Message],
    max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS,
    soft_ratio: float = COMPACTION_SOFT_RATIO,
    hard_ratio: float = COMPACTION_HARD_RATIO,
    tokenizer: Tokenizer | None = None,
) -> int:  # returns number of messages removed
```

Operates **in place** on the `messages` list.

### Phase 1 — Soft Compaction

While `estimated_tokens > soft_limit` (80%):

1. Compute preserved indexes (see below).
2. Drop the oldest message that is not preserved.
3. Recompute preserved indexes and repeat.

### Phase 2 — Hard Compaction

If still `> hard_limit` (90%) after phase 1, continue dropping oldest non-preserved
messages until under 90%.

### Summary Marker

After any messages are dropped, a system message is inserted after the first system
message:

```
[Context compacted: N older messages removed to stay within token budget.]
```

Only one such marker is ever present; the check `"context trimmed" in m.content`
prevents duplicates.

## Preserved Indexes

`_preserved_indexes(messages)` returns the set of message indexes that must **not** be
dropped:

1. **Latest system message** — the active system prompt.
2. **Latest real user message** — prefers `kind="user"` over `kind="steer"` or
   `kind="contextual"`. Falls back to any user message if no `kind="user"` exists.
3. **Unresolved tool calls** — any assistant message containing a tool call whose
   `call_id` has not yet appeared in a tool result message, plus any partial tool result
   for that call.

This ensures the agent always has its instructions, the user's latest request, and a
consistent tool call state.

## `manual_compact`

Triggered by the `/compact` slash command. Uses more aggressive ratios:

```python
def manual_compact(messages, max_input_tokens=DEFAULT_MAX_INPUT_TOKENS, tokenizer=None) -> int:
    return compact_messages(
        messages,
        max_input_tokens=max_input_tokens,
        soft_ratio=0.60,   # drop to 60%
        hard_ratio=0.70,   # force to 70%
        tokenizer=tokenizer,
    )
```

## `ContextOverflowError` Recovery

When the LLM returns a `ContextOverflowError`, `AgentLoop._call_llm()` performs an
automatic recovery compaction before retrying once:

```python
except ContextOverflowError:
    removed = compact_messages(
        self._messages,
        soft_ratio=0.50,
        hard_ratio=0.60,
        tokenizer=self._tokenizer,
    )
    if removed:
        # retry the LLM call
```

If the retry also fails with `ContextOverflowError`, the exception propagates to the
TUI which shows an error message.

## Automatic Compaction in the Loop

`AgentLoop._maybe_compact()` is called before every LLM call:

```python
def _maybe_compact(self) -> None:
    before = estimate_total_tokens(self._messages, self._tokenizer)
    soft = int(DEFAULT_MAX_INPUT_TOKENS * 0.80)
    if before > soft:
        removed = compact_messages(self._messages, tokenizer=self._tokenizer)
        if removed and self._on_compact:
            self._on_compact(removed, before, after)
```

The `_on_compact` callback notifies the TUI so it can display a compaction notice.

## `Ctrl+X` Context Breakdown

The context breakdown modal (`taui/tui/screens/`) reads
`SystemPromptBuilder.budget_report` and the current message list to show a per-section
token breakdown. It does not trigger compaction.

## Pluggable Context Strategies

Source: `taui/agent/context_strategy.py`

### `ContextStrategy` Protocol

```python
class ContextStrategy(Protocol):
    name: str

    def prepare(self, messages: list[Message], max_tokens: int) -> list[Message]:
        """Compact messages before an LLM call. May modify in place."""

    def on_turn_result(self, usage: dict[str, Any]) -> None:
        """Called after each LLM turn with usage stats."""
```

### Built-In Strategy: `drop_oldest`

```python
@dataclass(slots=True)
class DropOldestStrategy:
    name: str = "drop_oldest"

    def prepare(self, messages, max_tokens):
        compact_messages(messages, max_input_tokens=max_tokens)
        return messages

    def on_turn_result(self, usage): pass
```

This is the default. It wraps `compact_messages` with the same preserve/drop logic
described above.

### `ContextStrategyRegistry`

```python
registry = ContextStrategyRegistry()
registry.register(my_strategy)
strategy = registry.get("my_name")   # ContextStrategy | None
names = registry.names()             # sorted list
registry.unregister("my_name")
```

The registry is created during `Session.create()` and passed to extensions via
`ctx.context`. Extensions register custom strategies before the session's first run.

### Registering a Custom Strategy

```python
# .taui/extensions/my_strategy.py
from dataclasses import dataclass
from typing import Any
from taui.agent.types import Message


@dataclass(slots=True)
class SummariseOldestStrategy:
    name: str = "summarise_oldest"

    def prepare(self, messages: list[Message], max_tokens: int) -> list[Message]:
        # Custom logic: replace oldest non-preserved messages with a summary
        # For now, fall back to drop_oldest as a skeleton
        from taui.agent.context import compact_messages
        compact_messages(messages, max_input_tokens=max_tokens)
        return messages

    def on_turn_result(self, usage: dict[str, Any]) -> None:
        pass


def register(ctx):
    if ctx.context:
        ctx.context.register(SummariseOldestStrategy())
```
