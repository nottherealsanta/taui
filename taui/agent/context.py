"""Context management — conversation compaction for token budget.

When the conversation grows large, older messages are dropped to keep
context within the LLM's input token limit. The compaction algorithm:

1. Preserves: system prompt, latest user message, unresolved tool calls
2. Drops oldest non-preserved messages first
3. Inserts a summary marker so the agent knows context was trimmed

Used by AgentLoop._maybe_compact() before each LLM call.
"""

from __future__ import annotations

import json

from taui.agent.tokenizer import Tokenizer
from taui.agent.types import Message

# ── Defaults ───────────────────────────────────────────────────────────────────

DEFAULT_MAX_INPUT_TOKENS = 180_000
COMPACTION_SOFT_RATIO = 0.80
COMPACTION_HARD_RATIO = 0.90


# ── Token estimation ──────────────────────────────────────────────────────────


def estimate_message_tokens(msg: Message, tokenizer: Tokenizer | None = None) -> int:
    """Rough token estimate: ~4 chars per token, or via tokenizer if provided."""
    total = len(msg.role)
    if msg.content:
        total += len(msg.content)
    if msg.tool_calls:
        for tc in msg.tool_calls:
            total += len(tc.name) + len(tc.call_id)
            total += len(json.dumps(tc.arguments, sort_keys=True))
    if msg.tool_call_id:
        total += len(msg.tool_call_id)
    if msg.name:
        total += len(msg.name)
    if tokenizer is not None:
        # Build a representative string and let the tokenizer estimate
        return tokenizer.estimate(" " * total)
    return max(1, total // 4 + 1)


def estimate_total_tokens(messages: list[Message], tokenizer: Tokenizer | None = None) -> int:
    return sum(estimate_message_tokens(m, tokenizer) for m in messages)


# ── Preservation logic ────────────────────────────────────────────────────────


def _preserved_indexes(messages: list[Message]) -> set[int]:
    """Indexes of messages that must NOT be dropped."""
    preserve: set[int] = set()

    # Latest system message
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "system":
            preserve.add(i)
            break

    # Latest real user message (prefer kind="user" over "contextual"/"steer")
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "user" and getattr(messages[i], "kind", "user") == "user":
            preserve.add(i)
            break
    else:
        # Fallback: preserve any latest user message regardless of kind
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].role == "user":
                preserve.add(i)
                break

    # Unresolved tool calls — both the assistant message containing
    # the call and any partial tool results
    requested: set[str] = set()
    resolved: set[str] = set()
    for m in messages:
        if m.tool_calls:
            for tc in m.tool_calls:
                requested.add(tc.call_id)
        if m.role == "tool" and m.tool_call_id:
            resolved.add(m.tool_call_id)

    unresolved = requested - resolved
    if unresolved:
        for i, m in enumerate(messages):
            if m.tool_calls and any(tc.call_id in unresolved for tc in m.tool_calls):
                preserve.add(i)
            if m.role == "tool" and m.tool_call_id in unresolved:
                preserve.add(i)

    return preserve


def _oldest_droppable(messages: list[Message], preserve: set[int]) -> int | None:
    """Find the index of the oldest non-preserved message."""
    for i in range(len(messages)):
        if i not in preserve:
            return i
    return None


# ── Compaction ────────────────────────────────────────────────────────────────


def compact_messages(
    messages: list[Message],
    max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS,
    soft_ratio: float = COMPACTION_SOFT_RATIO,
    hard_ratio: float = COMPACTION_HARD_RATIO,
    tokenizer: Tokenizer | None = None,
) -> int:
    """Compact a message list in-place. Returns number of messages removed.

    Two phases:
    1. Drop oldest droppable messages until under soft limit
    2. If still over hard limit, continue aggressive dropping

    After dropping, inserts a summary marker after the system prompt.
    """
    from taui.agent.loop import Message

    soft_limit = int(max_input_tokens * soft_ratio)
    hard_limit = int(max_input_tokens * hard_ratio)
    removed = 0

    # Phase 1: soft compaction
    preserve = _preserved_indexes(messages)
    while estimate_total_tokens(messages, tokenizer) > soft_limit:
        idx = _oldest_droppable(messages, preserve)
        if idx is None:
            break
        del messages[idx]
        preserve = _preserved_indexes(messages)
        removed += 1

    # Phase 2: hard compaction
    if estimate_total_tokens(messages, tokenizer) > hard_limit:
        preserve = _preserved_indexes(messages)
        while estimate_total_tokens(messages, tokenizer) > hard_limit:
            idx = _oldest_droppable(messages, preserve)
            if idx is None:
                break
            del messages[idx]
            preserve = _preserved_indexes(messages)
            removed += 1

    # Insert summary marker
    if removed > 0:
        has_summary = any(
            m.role == "system" and m.content and "context trimmed" in m.content
            for m in messages
        )
        if not has_summary:
            summary = Message(
                role="system",
                content=(
                    f"[Context compacted: {removed} older messages removed "
                    f"to stay within token budget.]"
                ),
            )
            # Insert after the first system message
            insert_at = 1 if messages and messages[0].role == "system" else 0
            messages.insert(insert_at, summary)

    return removed
