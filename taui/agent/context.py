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

    # Tool call integrity — assistant messages with tool_calls and their
    # matching tool result messages must be dropped together or not at all.
    # Build a mapping from call_id to the indexes that reference it.
    call_id_indexes: dict[str, list[int]] = {}
    for i, m in enumerate(messages):
        if m.tool_calls:
            for tc in m.tool_calls:
                call_id_indexes.setdefault(tc.call_id, []).append(i)
        if m.role == "tool" and m.tool_call_id:
            call_id_indexes.setdefault(m.tool_call_id, []).append(i)

    # Group indexes that share an assistant message (parallel tool calls).
    # All indexes in a group must be preserved together.
    visited: set[int] = set()
    groups: list[set[int]] = []
    for i, m in enumerate(messages):
        if i in visited:
            continue
        if not m.tool_calls:
            continue
        group = {i}
        for tc in m.tool_calls:
            group.update(call_id_indexes.get(tc.call_id, []))
        groups.append(group)
        visited.update(group)

    # If any member of a group is already preserved, preserve the whole group.
    # Also, if the group is incomplete (missing a tool result), preserve it.
    for group in groups:
        # Collect call_ids requested by assistant messages in this group
        requested: set[str] = set()
        resolved: set[str] = set()
        for idx in group:
            m = messages[idx]
            if m.tool_calls:
                for tc in m.tool_calls:
                    requested.add(tc.call_id)
            if m.role == "tool" and m.tool_call_id:
                resolved.add(m.tool_call_id)
        if requested - resolved or group & preserve:
            preserve.update(group)

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


def manual_compact(
    messages: list[Message],
    max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS,
    tokenizer: Tokenizer | None = None,
) -> int:
    """User-initiated compaction via /compact. More aggressive than auto."""
    return compact_messages(
        messages,
        max_input_tokens=max_input_tokens,
        soft_ratio=0.60,
        hard_ratio=0.70,
        tokenizer=tokenizer,
    )
