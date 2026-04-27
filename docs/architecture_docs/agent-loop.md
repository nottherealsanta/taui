# Agent Loop

The agent loop is the core runtime: think → tool → observe, repeated until the LLM produces a final text response or hits max turns.

---

## State Machine

```
IDLE → run(message) → THINKING → (tool_calls?) →
  ├── no tools  → DONE (return text)
  └── has tools → TOOL_EXECUTION → observe results → THINKING → ...
```

```python
class AgentState(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    TOOL_EXECUTION = "tool_execution"
    DONE = "done"
    ERROR = "error"
```

---

## Message Types

```python
@dataclass
class Message:
    role: str               # "system" | "user" | "assistant" | "tool"
    content: str | None
    tool_calls: list[ProviderToolCall] | None    # assistant messages with tool calls
    tool_call_id: str | None                     # tool result → links to call
    name: str | None                             # tool name for role="tool"
```

Conversation history is a flat list `_messages: list[Message]`. The system prompt is the first message (role="system"), inserted on the first `run()` call.

---

## Turn Lifecycle

Each call to `_think_and_act(turn)`:

```
1. _maybe_compact()                  # Check token budget, compact if needed
2. _build_llm_messages()             # Convert Message list to dicts for LLM
3. _call_llm()                       # Send to provider with tool schemas
4. Record assistant message          # Append to _messages
5. Fire on_text callback             # If response has text
6. Record usage                      # If usage data present
7. If no tool_calls → return         # Turn done, loop exits
8. For each tool_call:
   a. Fire on_tool_call callback     # UI: show tool name + args
   b. executor.run(call_id, name, arguments)
   c. Handle outcome:
      - Completed → record result
      - NeedsApproval → call on_approval → re-run with approved flag
      - Denied → record denial message
   d. Fire on_tool_result callback   # UI: show result summary
   e. Append Message(role="tool", content, tool_call_id)
9. Emit TOOL_RESULT event to Store
```

---

## Results

```python
@dataclass
class TurnResult:
    text: str | None              # LLM text output (may be None if only tool calls)
    tool_calls_count: int         # Number of tool calls this turn
    turn_number: int
    usage: dict[str, Any] | None  # Token counts from provider

@dataclass
class RunResult:
    text: str                     # Final text response
    turns: int                    # Total turns taken
    state: AgentState             # Final state (DONE or ERROR)
    turn_results: list[TurnResult]
```

---

## Callbacks

Four optional async callbacks for frontend integration:

```python
on_tool_call(call_id, name, arguments)     # Tool invocation started
on_tool_result(call_id, name, content, is_error)  # Tool finished
on_approval(call_id, name, arguments) -> bool      # User approves?
on_text(text)                               # Assistant text chunk
```

The CLI wires these to terminal output. A web frontend would wire them to WebSocket messages.

---

## Context Compaction (`taui/agent/context.py`)

When conversation history grows too large, the loop automatically compacts before calling the LLM.

### Token Estimation

```python
def estimate_message_tokens(msg: Message) -> int
    # ~4 chars per token heuristic
    # Counts: content + tool_call arguments + tool_call_id + name

def estimate_total_tokens(messages: list[Message]) -> int
```

### Compaction Strategy

```python
DEFAULT_MAX_INPUT_TOKENS = 180_000
COMPACTION_SOFT_RATIO = 0.80    # 144K tokens → start compacting
COMPACTION_HARD_RATIO = 0.90    # 162K tokens → aggressive mode

def compact_messages(messages, max_input_tokens, soft_ratio, hard_ratio) -> int
```

**Preserves** (never drops):
- Latest system message
- Latest user message
- Tool result messages with unresolved tool_call_ids (prevents dangling references)

**Drops** (oldest first):
- Older assistant messages
- Older user messages
- Resolved tool call/result pairs

**After compaction**: inserts a summary marker message:
```
[Context compacted: N older messages removed to stay within token budget]
```

### Integration

```python
# In AgentLoop._maybe_compact():
est = estimate_total_tokens(self._messages)
soft = int(DEFAULT_MAX_INPUT_TOKENS * 0.80)
if est > soft:
    removed = compact_messages(self._messages)
```

Called before every `_call_llm()`.

---

## Event Emission

The loop writes events to the Store via StreamClient for every significant action:

| Event | When |
|-------|------|
| `STREAM_START` | `run()` begins |
| `USER_MESSAGE` | User message added |
| `STATE_CHANGE` | State transitions (thinking, tool_execution) |
| `ASSISTANT_MESSAGE` | LLM produces text |
| `TOOL_CALL` | Tool invocation with name + args |
| `TOOL_RESULT` | Tool result with content + error flag |
| `USAGE` | Token counts from provider |
| `STREAM_END` | Loop completes (reason: complete | max_turns) |
| `ERROR` | Unrecoverable error |

These events enable: live-tail frontends, conversation replay, debugging, and analytics.

---

## Key Design Decisions

1. **Flat message list** — no tree structure, no branching. Simple and predictable.
2. **Sync compaction** — `_maybe_compact()` is synchronous (mutates `_messages` in place). No async needed since it's pure list manipulation.
3. **All errors returned, not raised** — tool failures become `Completed(error=True)`, which the LLM can react to. Only provider failures raise.
4. **No parallel tool calls** — tools execute sequentially within a turn. The LLM can request multiple tool calls, but they run one-at-a-time.
5. **Stream per agent** — each agent gets its own stream ID (`agents/{agent_id}`). Sub-agents (future) will get child streams.

---

## Files

| File | Purpose |
|------|---------|
| `taui/agent/loop.py` | AgentLoop, Message, TurnResult, RunResult, AgentState |
| `taui/agent/context.py` | estimate_*_tokens, compact_messages, DEFAULT_MAX_INPUT_TOKENS |
| `taui/agent/__init__.py` | Re-exports AgentLoop, AgentState |
