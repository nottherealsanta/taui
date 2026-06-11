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
import logging
from dataclasses import dataclass
from typing import Any

from taui.agent.tokenizer import Tokenizer
from taui.agent.types import Message

logger = logging.getLogger(__name__)

# ── Defaults ───────────────────────────────────────────────────────────────────

DEFAULT_MAX_INPUT_TOKENS = 180_000
COMPACTION_SOFT_RATIO = 0.80
COMPACTION_HARD_RATIO = 0.90


# ── Token estimation ──────────────────────────────────────────────────────────

# Conservative per-image token allowance.  Actual vision-model costs vary by
# resolution, but 1 500 tokens is a safe middle-ground for budget tracking.
IMAGE_TOKEN_ESTIMATE = 1_500


def estimate_message_tokens(msg: Message, tokenizer: Tokenizer | None = None) -> int:
    """Rough token estimate: ~4 chars per token, or via tokenizer if provided.

    Accounts for content, tool-call metadata, name, tool_call_id, **and images**.
    """
    total_chars = len(msg.role)
    if msg.content:
        total_chars += len(msg.content)
    if msg.tool_calls:
        for tc in msg.tool_calls:
            total_chars += len(tc.name) + len(tc.call_id)
            total_chars += len(json.dumps(tc.arguments, sort_keys=True))
    if msg.tool_call_id:
        total_chars += len(msg.tool_call_id)
    if msg.name:
        total_chars += len(msg.name)

    # Image tokens — fixed per-image allowance
    image_tokens = 0
    if msg.images:
        image_tokens = len(msg.images) * IMAGE_TOKEN_ESTIMATE

    if tokenizer is not None:
        return tokenizer.estimate_chars(total_chars) + image_tokens
    return max(1, total_chars // 4 + 1) + image_tokens


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

    # Skill instructions are exempt from pruning (Agent Skills spec).
    # A loaded skill is injected as a system message with name="skill:<name>".
    # Losing it silently degrades the agent, so preserve every such message.
    for i, m in enumerate(messages):
        if getattr(m, "name", None) and isinstance(m.name, str) and m.name.startswith("skill:"):
            preserve.add(i)

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

    # O(N): compute preserved indexes and per-message token sizes once
    preserve = _preserved_indexes(messages)
    sizes = [estimate_message_tokens(m, tokenizer) for m in messages]
    total = sum(sizes)

    # Collect droppable indexes oldest-first (already in order)
    droppable = [i for i in range(len(messages)) if i not in preserve]

    # Single pass: mark messages to drop until under soft, then hard limit
    drop_set: set[int] = set()
    target = soft_limit
    di = 0
    while total > target and di < len(droppable):
        idx = droppable[di]
        drop_set.add(idx)
        total -= sizes[idx]
        di += 1
        # After reaching soft limit, check if we also exceed hard limit
        if total <= target and target == soft_limit and total > hard_limit:
            target = hard_limit

    # Rebuild list in one pass
    removed = len(drop_set)
    if removed > 0:
        messages[:] = [m for i, m in enumerate(messages) if i not in drop_set]

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


# ── Tool Output Pruning & Advanced Compaction ─────────────────────────────────

PRUNE_MINIMUM = 20_000
PRUNE_PROTECT = 40_000
DEFAULT_TAIL_TURNS = 2
MIN_PRESERVE_RECENT_TOKENS = 2_000
MAX_PRESERVE_RECENT_TOKENS = 8_000

SUMMARY_TEMPLATE = (  # noqa: E501
    "Output exactly the Markdown structure shown inside <template>"
    " and keep the section order unchanged."
    " Do not include the <template> tags in your response.\n"
    "<template>\n"
    "## Goal\n"
    "- [single-sentence task summary]\n"
    "\n"
    "## Constraints & Preferences\n"
    '- [user constraints, preferences, specs, or "(none)"]\n'
    "\n"
    "## Progress\n"
    "### Done\n"
    '- [completed work or "(none)"]\n'
    "\n"
    "### In Progress\n"
    '- [current work or "(none)"]\n'
    "\n"
    "### Blocked\n"
    '- [blockers or "(none)"]\n'
    "\n"
    "## Key Decisions\n"
    '- [decision and why, or "(none)"]\n'
    "\n"
    "## Next Steps\n"
    '- [ordered next actions or "(none)"]\n'
    "\n"
    "## Critical Context\n"
    '- [important technical facts, errors, open questions, or "(none)"]\n'
    "\n"
    "## Relevant Files\n"
    '- [file or directory path: why it matters, or "(none)"]\n'
    "</template>\n"
    "\n"
    "Rules:\n"
    "- Keep every section, even when empty.\n"
    "- Use terse bullets, not prose paragraphs.\n"
    "- Preserve exact file paths, commands, error strings,"
    " and identifiers when known.\n"
    "- Do not mention the summary process or"
    " that context was compacted."
)


@dataclass(slots=True)
class Turn:
    start: int
    end: int


def prune_tool_outputs(
    messages: list[Message],
    max_tool_tokens: int = PRUNE_PROTECT,
    tokenizer: Tokenizer | None = None,
) -> int:
    """Scan tool output messages backwards and prune older large tool outputs.

    Protects tool outputs from the most recent turn (user turns < 2).
    Protects certain tools like 'skill'.
    Stops if it hits a compaction summary message.
    Returns the number of tool outputs pruned.
    """
    total_tokens = 0
    pruned_count = 0
    to_prune_indexes = []
    
    # We count user turns from the end of the list
    user_turns = 0
    
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.role == "user":
            user_turns += 1
            
        # Protect tool outputs from the current/most recent user turn
        if user_turns < 2:
            continue
            
        # Stop scanning if we hit a past summary or a system summary marker
        if msg.role == "system" and msg.content and "[Context compacted:" in msg.content:
            break
        if msg.role == "assistant" and msg.content and "## Goal" in msg.content:
            break
        if msg.role == "system" and msg.content and "## Goal" in msg.content:
            break

        if msg.role == "tool":
            # Protect 'skill' tool output
            if msg.name == "skill":
                continue
                
            # If already pruned/truncated, skip
            if msg.content and "[Truncated tool output]" in msg.content:
                continue
                
            # Estimate tokens of this tool output
            est = estimate_message_tokens(msg, tokenizer)
            total_tokens += est
            
            if total_tokens > max_tool_tokens:
                to_prune_indexes.append(i)
                
    for idx in to_prune_indexes:
        msg = messages[idx]
        if msg.content:
            orig_len = len(msg.content)
            msg.content = f"[Truncated tool output (original length: {orig_len} characters)]"
            pruned_count += 1
            
    return pruned_count


def find_turns(messages: list[Message]) -> list[Turn]:
    """Find the user turn boundaries in the message list."""
    turns = []
    for i, msg in enumerate(messages):
        # We look for user messages
        if msg.role == "user":
            turns.append(Turn(start=i, end=len(messages)))
            
    for i in range(len(turns) - 1):
        turns[i].end = turns[i+1].start
    return turns


def select_head_and_tail(
    messages: list[Message],
    max_input_tokens: int,
    tail_turns: int = DEFAULT_TAIL_TURNS,
    tokenizer: Tokenizer | None = None,
) -> tuple[list[Message], list[Message]]:
    """Split messages into head (to be summarized) and tail (to be preserved)."""
    all_turns = find_turns(messages)
    if not all_turns:
        return [], messages
        
    budget = min(
        MAX_PRESERVE_RECENT_TOKENS,
        max(MIN_PRESERVE_RECENT_TOKENS, int(max_input_tokens * 0.25)),
    )
    
    # We want to check up to `tail_turns` recent turns
    recent_turns = all_turns[-tail_turns:] if tail_turns > 0 else all_turns[-1:]
    
    # We MUST keep the very last turn to avoid breaking the current assistant-user loop
    keep_start_idx = len(messages)
    
    # Let's count tokens from the end to see how many turns fit in budget
    total_tokens = 0
    for turn in reversed(recent_turns):
        turn_msgs = messages[turn.start:turn.end]
        turn_tokens = estimate_total_tokens(turn_msgs, tokenizer)
        
        # If this is the absolute last turn, we MUST keep it even if it exceeds the budget
        if turn == all_turns[-1]:
            total_tokens += turn_tokens
            keep_start_idx = turn.start
            continue
            
        if total_tokens + turn_tokens <= budget:
            total_tokens += turn_tokens
            keep_start_idx = turn.start
        else:
            break
            
    # Head messages are those before keep_start_idx
    head = messages[:keep_start_idx]
    tail = messages[keep_start_idx:]
    
    return head, tail


def find_previous_summary(messages: list[Message]) -> str | None:
    """Find the last generated compaction summary in the messages."""
    for msg in reversed(messages):
        if msg.role in ("system", "assistant") and msg.content and "## Goal" in msg.content:
            return msg.content
    return None


def build_compaction_prompt(previous_summary: str | None = None) -> str:
    if previous_summary:
        anchor = (
            "Update the anchored summary below using the conversation history above.\n"
            "Preserve still-true details, remove stale details, and merge in the new facts.\n"
            "<previous-summary>\n"
            f"{previous_summary}\n"
            "</previous-summary>"
        )
    else:
        anchor = "Create a new anchored summary from the conversation history above."
    return f"{anchor}\n\n{SUMMARY_TEMPLATE}"


def to_dict_list(messages: list[Message]) -> list[dict[str, Any]]:
    result = []
    for msg in messages:
        entry = {"role": msg.role}
        if msg.content is not None:
            entry["content"] = msg.content
        if msg.tool_calls:
            entry["tool_calls"] = [
                tc.to_chat_completions_format() for tc in msg.tool_calls
            ]
            if msg.content is None:
                entry["content"] = None
        if msg.tool_call_id:
            entry["tool_call_id"] = msg.tool_call_id
        if msg.name and msg.role == "tool":
            entry["name"] = msg.name
        result.append(entry)
    return result


async def async_compact_messages(
    messages: list[Message],
    tokenizer: Tokenizer,
    llm: Any,
    model: str,
    provider_name: str,
    max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS,
) -> int:
    """Compact a message list asynchronously.
    
    First runs tool output pruning. If still over target, uses active LLM to generate
    a structured Markdown summary of older 'head' messages and replaces them in-place.
    Falls back to synchronous compaction if LLM calls fail.
    """
    # 1. Prune tool outputs first
    pruned_count = prune_tool_outputs(messages, tokenizer=tokenizer)
    
    # 2. Check if under soft limit
    before = estimate_total_tokens(messages, tokenizer)
    soft_limit = int(max_input_tokens * 0.80)
    if before <= soft_limit:
        return pruned_count
        
    # 3. Split into head and tail
    head, tail = select_head_and_tail(messages, max_input_tokens, tokenizer=tokenizer)
    
    # Extract system messages from head to preserve them
    system_messages = [m for m in head if m.role == "system"]
    non_system_head = [m for m in head if m.role != "system"]
    
    if not non_system_head:
        # Nothing in head to summarize, let's use sync fallback
        return compact_messages(messages, max_input_tokens, tokenizer=tokenizer)
        
    # 4. Find previous summary and build prompt
    previous_summary = find_previous_summary(messages)
    compaction_prompt = build_compaction_prompt(previous_summary)
    
    # 5. Call LLM to summarize
    llm_inputs = to_dict_list(non_system_head)
    llm_inputs.append({
        "role": "user",
        "content": compaction_prompt
    })
    
    try:
        # Use low temperature for deterministic structured output
        result = await llm.create_turn(llm_inputs, model, temperature=0.1)
        summary_text = result.text
        
        # Verify generated summary
        if not summary_text or "## Goal" not in summary_text:
            logger.warning("LLM generated invalid summary, falling back to sync compaction")
            return compact_messages(messages, max_input_tokens, tokenizer=tokenizer)
            
    except Exception as e:
        logger.error(f"Async compaction LLM call failed: {e}. Falling back to sync compaction")
        return compact_messages(messages, max_input_tokens, tokenizer=tokenizer)
        
    # 6. Replace head with summary system message in-place
    summary_message = Message(
        role="system",
        content=summary_text
    )
    
    removed_count = len(messages) - (len(system_messages) + 1 + len(tail))
    messages[:] = system_messages + [summary_message] + tail
    
    return removed_count
