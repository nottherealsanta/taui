# Agent Loop

The agent loop (`taui/agent/loop.py`) is the core runtime: think → tool → observe, repeated until the LLM produces a final text response or hits `max_turns`. All events are written to the Store via `StreamClient`.

---

## State Machine

`AgentState` is a `StrEnum` with five values:

```python
class AgentState(StrEnum):
    IDLE = "idle"
    THINKING = "thinking"
    TOOL_EXECUTION = "tool_execution"
    DONE = "done"
    ERROR = "error"
```

Transition diagram:

```
IDLE
  └─ run(message)
       └─ THINKING  ← _think_and_act() starts; _call_llm() is in flight
            ├─ no tool_calls  → DONE
            └─ tool_calls     → TOOL_EXECUTION → THINKING (next turn) → ...
                                     └─ max_turns hit → DONE
```

Any unhandled exception (including `ContextOverflowError`, `QuotaExceededError`) transitions to `ERROR` and re-raises.

---

## Message Dataclass

Defined in `taui/agent/types.py`. Represents one entry in the flat conversation history.

```python
@dataclass
class Message:
    role: str                               # "system" | "user" | "assistant" | "tool"
    content: str | None = None
    tool_calls: list[ProviderToolCall] | None = None  # assistant messages with tool calls
    tool_call_id: str | None = None         # links a tool result back to its call
    name: str | None = None                 # tool name for role="tool" messages
    kind: str = "user"                      # "user" | "contextual" | "steer"
    images: list[str] | None = None         # data: URLs for inline images (multimodal)
```

**`kind`** is an internal tag used by compaction and steering:
- `"user"` — normal user turn (preserved by compaction)
- `"steer"` — injected mid-run via `steer()` (can be dropped)
- `"contextual"` — injected context (can be dropped)

Conversation history is stored as `_messages: list[Message]`. The system prompt is prepended as a `role="system"` message on the first `run()` call.

---

## Turn Lifecycle (`_think_and_act`)

`run()` iterates up to `max_turns` (default 50), calling `_think_and_act(turn)` each iteration.

```
_think_and_act(turn):
  1. await self._paused.wait()          # Block if loop is paused
  2. state = THINKING
  3. emit STATE_CHANGE(thinking, turn)
  4. _call_llm()
     a. _maybe_compact()                # Auto-compact if over soft token limit
     b. _build_llm_messages()           # Convert Message list → provider dicts
     c. Wire on_text_delta / on_reasoning_delta to provider
     d. provider.create_turn(messages, model, tools=schemas)
        └─ On ContextOverflowError: aggressive compaction (0.50/0.60) + one retry
  5. Append Message(role="assistant", content, tool_calls) to _messages
  6. emit ASSISTANT_MESSAGE
  7. If text → fire on_text callback
  8. If usage data → emit USAGE; calibrate tokenizer against actual input_tokens
  9. If no tool_calls → return TurnResult(tool_calls_count=0)  # loop exits

 10. state = TOOL_EXECUTION
 11. emit STATE_CHANGE(tool_execution, turn)
 12. Separate question tools from other tools
 13. Execute non-question tools (with parallelism for FILE_READ / SEARCH categories):
     For each tool call:
       a. emit TOOL_CALL
       b. fire on_tool_call callback
       c. executor.run(call_id, name, arguments)
          - Completed  → use result.content / result.error
          - NeedsApproval → fire on_approval; if approved re-run with approved=True
          - Denied     → content = "Tool call denied by user."
       d. (optional) fire on_result_process to post-process content
       e. Append Message(role="tool", content, tool_call_id, name)
       f. emit TOOL_RESULT
       g. fire on_tool_result callback
       h. _drain_steering() — inject any queued steer() messages
 14. Execute question tools (batched via on_questions_batch if available)
 15. return TurnResult(tool_calls_count=N)
```

### Parallel tool execution

Consecutive tool calls whose `tool.category` is `ToolCategory.FILE_READ` or `ToolCategory.SEARCH` are gathered and run with `asyncio.gather`. All other categories execute sequentially.

### Multimodal messages

When a `Message` has both `content` and `images`, `_build_llm_messages()` emits a content-block array (`[{type: text}, {type: image_url}, ...]`) instead of a plain string.

---

## TurnResult and RunResult

```python
@dataclass
class TurnResult:
    text: str | None              # LLM text this turn (None if tool-calls only)
    tool_calls_count: int         # Number of tool calls executed
    turn_number: int
    usage: dict[str, Any] | None  # Token counts from provider
    metadata: dict[str, Any] | None  # Extra provider metadata (e.g. reasoning)
```

```python
@dataclass
class RunResult:
    text: str                       # Final assistant response
    turns: int                      # Total turns taken
    state: AgentState               # DONE or ERROR
    turn_results: list[TurnResult]

    # Computed properties:
    total_usage -> dict[str, int]   # Sum of input/output/cache/reasoning tokens
    cost_usd -> float | None        # Sum of cost_usd from all turns (None if no data)
```

`total_usage` keys: `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens`.

---

## Callbacks

All callbacks are optional. `AgentLoop.__init__` accepts them as keyword arguments.

| Callback | Signature | When fired |
|---|---|---|
| `on_tool_call` | `async (call_id, name, arguments) -> None` | Before a tool executes |
| `on_tool_result` | `async (call_id, name, content, is_error) -> None` | After a tool returns |
| `on_approval` | `async (call_id, name, arguments) -> bool` | Tool needs user approval |
| `on_text` | `async (text) -> None` | LLM produced a complete text response |
| `on_text_delta` | `(text) -> None` | Streaming text delta (sync) |
| `on_reasoning_delta` | `(text) -> None` | Streaming reasoning delta (sync) |

Two additional internal callbacks:

| Callback | Signature | Purpose |
|---|---|---|
| `_on_questions_batch` | `async (list[(question, options)]) -> list[str\|None]` | Batch question tool handler |
| `_on_compact` | `(removed, before_tokens, after_tokens) -> None` | Notifies UI of compaction |
| `_on_result_process` | `(tool_name, call_id, content) -> content` | Post-process tool result content |

The TUI wires `on_tool_call`, `on_tool_result`, `on_approval`, `on_text_delta`, and `on_reasoning_delta` to Textual widgets for live tool status, approval prompts, and streamed text rendering.

---

## Context Compaction (`taui/agent/context.py`)

### Constants

```python
DEFAULT_MAX_INPUT_TOKENS = 180_000
COMPACTION_SOFT_RATIO    = 0.80   # 144K tokens → trigger auto-compaction
COMPACTION_HARD_RATIO    = 0.90   # 162K tokens → aggressive phase
```

### Token estimation

```python
estimate_message_tokens(msg, tokenizer=None) -> int
    # Sums: len(role) + len(content) + serialized tool_calls + tool_call_id + name
    # If tokenizer provided: passes representative char-length string to tokenizer
    # Fallback: max(1, char_total // 4 + 1)

estimate_total_tokens(messages, tokenizer=None) -> int
    # Sum of estimate_message_tokens for all messages
```

The tokenizer is calibrated after each LLM call: actual `input_tokens` from the provider are compared to the estimate, and the `Tokenizer` adjusts its ratio for future estimates.

### Compaction algorithm

`compact_messages(messages, max_input_tokens, soft_ratio, hard_ratio, tokenizer)`:

**Preserved** (never dropped):
- Latest `role="system"` message
- Latest `role="user"` message with `kind="user"` (falls back to any user message)
- Any assistant message containing unresolved tool calls
- Any tool result whose `tool_call_id` is still unresolved

**Dropped** (oldest first): everything else — older user/assistant/tool messages and resolved tool call pairs.

Two-phase loop:
1. **Soft phase** — drop oldest droppable messages until total tokens ≤ `soft_limit`
2. **Hard phase** — if still over `hard_limit`, continue dropping

After any removal, inserts one summary marker (once per compaction):
```
[Context compacted: N older messages removed to stay within token budget.]
```

### Auto-compaction trigger

```python
# AgentLoop._maybe_compact() — called before every _call_llm():
soft = int(DEFAULT_MAX_INPUT_TOKENS * 0.80)   # 144K
if estimate_total_tokens(messages) > soft:
    compact_messages(messages, tokenizer=tokenizer)
```

### Recovery compaction on ContextOverflowError

If the provider raises `ContextOverflowError`, the loop immediately retries with aggressive ratios before propagating the error:

```python
compact_messages(messages, soft_ratio=0.50, hard_ratio=0.60, tokenizer=tokenizer)
```

### Manual compaction (`/compact` command)

```python
manual_compact(messages, max_input_tokens, tokenizer) -> int
    # Calls compact_messages with soft_ratio=0.60, hard_ratio=0.70
```

More aggressive than auto-compaction since the user explicitly requested it.

---

## Steering

`steer(message: str)` enqueues a mid-run user message without requiring a full new `run()` call:

```python
loop.steer("Focus on the authentication module only.")
```

Steering messages are injected into `_messages` (with `kind="steer"`) between tool call executions via `_drain_steering()`. The `_steering_queue` is a simple `list[str]`; messages drain FIFO.

Steering is distinct from `run()`: it does not add a `USER_MESSAGE` event to the store and does not start a new agent run — it only influences the in-progress turn's context.

---

## Pause / Resume

```python
loop.pause()    # Clears internal asyncio.Event; next LLM call blocks
loop.resume()   # Sets event; loop proceeds
loop.is_paused  # bool property
```

In-flight tool calls complete before the pause takes effect. New LLM calls block at `await self._paused.wait()` at the top of `_think_and_act`.

---

## System Prompt Hot-swap

```python
loop.update_system_prompt(new_prompt)
```

Replaces `_system_prompt` and, if the first message in `_messages` is a system message, overwrites it in place. Safe to call between turns.

---

## Agent Variants (`taui/agent/variants.py`)

Agent variants are named configuration bundles that can override the model, system prompt, tool subset, read-only flag, turn limit, and per-variant permissions.

### `AgentVariant` dataclass

```python
@dataclass(slots=True)
class AgentVariant:
    name: str
    description: str = ""
    model: str | None = None         # None → use session default
    system_prompt: str | None = None # None → use session default
    tool_names: list[str] | None = None  # None → all tools
    read_only: bool = False          # True → excludes FILE_WRITE / SHELL / GIT tools
    max_turns: int | None = None     # None → use session default
    permission: dict[str, dict[str, str]] = field(default_factory=dict)
```

### `AgentVariantRegistry`

Holds variants keyed by name. Methods:

```python
registry.register(variant)
registry.get(name) -> AgentVariant | None
registry.names() -> list[str]           # sorted
registry.all() -> list[AgentVariant]
registry.unregister(name)
registry.discover_from_dir(agents_dir: Path) -> list[str]  # loads *.toml
```

### Built-in variants

| Name | Description |
|---|---|
| `build` | Default. Full tool access, no restrictions. |
| `plan` | Read-only (`read_only=True`). Scoped system prompt for planning/analysis. |

### TOML discovery

`discover_from_dir` loads `*.toml` files from a directory (typically `.taui/agents/`). Each file can set:

```toml
name        = "review"
description = "Read-only code reviewer"
model       = "gpt-4o"
system_prompt = "..."
tools       = ["read", "glob", "grep"]
read_only   = true
max_turns   = 20

[permission]
bash = { "git log *" = "allow", "*" = "deny" }
```

Errors loading individual files are silently ignored so a bad TOML does not block startup.

---

## Event Emission

The loop writes events to the Store via `StreamClient.append()`. Failures are logged and swallowed — a store write failure does not crash the loop.

| Event | When |
|---|---|
| `STREAM_START` | `run()` begins |
| `USER_MESSAGE` | User message appended (includes `images` key if present) |
| `STATE_CHANGE` | Transitions to `thinking` or `tool_execution` |
| `ASSISTANT_MESSAGE` | LLM produces text or tool calls |
| `TOOL_CALL` | Tool invocation with `call_id`, `name`, `arguments` |
| `TOOL_RESULT` | Tool result with `content` and `error` flag |
| `USAGE` | Token counts and `cost_usd` from provider |
| `STREAM_END` | Loop completes (`reason`: `"complete"` or `"max_turns"`) |
| `ERROR` | Unrecoverable error (`error_type`: `"context_overflow"`, `"quota_exceeded"`, or generic) |

Stream ID format: `agents/{agent_id}`. Sub-agents get their own stream.

---

## Key Design Decisions

1. **Flat message list** — no tree structure, no branching. Simple and predictable. History is a `list[Message]` mutated in place.
2. **Sync compaction** — `_maybe_compact()` is synchronous (pure list mutation). No async overhead.
3. **Tool errors returned, not raised** — tool failures produce `Completed(error=True)`. Only provider failures (quota, context overflow) raise exceptions.
4. **Selective parallelism** — `FILE_READ` and `SEARCH` category tools run in parallel via `asyncio.gather`; all others run sequentially. This avoids race conditions on write tools.
5. **Question tool batching** — multiple `question` tool calls in one turn are batched to the UI via `_on_questions_batch`, letting the user answer them together.
6. **Tokenizer calibration** — after each LLM call the tokenizer's estimate ratio is adjusted against actual `input_tokens`, improving compaction accuracy over time.
7. **Stream per agent** — each `AgentLoop` instance gets a unique stream ID. The Store is the single source of truth for replay; no side-channel state is kept.
8. **System prompt caching** — `_build_llm_messages()` marks system messages with `_cache: True` as a hint to the provider for prompt caching.

---

## Files

| File | Purpose |
|---|---|
| `taui/agent/loop.py` | `AgentLoop`, `AgentState`, `TurnResult`, `RunResult` |
| `taui/agent/types.py` | `Message` dataclass |
| `taui/agent/context.py` | `estimate_*_tokens`, `compact_messages`, `manual_compact`, constants |
| `taui/agent/variants.py` | `AgentVariant`, `AgentVariantRegistry` |
| `taui/agent/tokenizer.py` | `Tokenizer` protocol, `create_tokenizer`, calibration |
| `taui/agent/__init__.py` | Re-exports `AgentLoop`, `AgentState` |
