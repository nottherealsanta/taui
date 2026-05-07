# Store & Streams

The Store is an append-only event log backed by SQLite. Every action in the system — agent state changes, tool calls, messages, questions — is persisted as an event.

---

## Architecture

```
AgentLoop / Frontend
       ↓ write events
StreamClient (high-level API)
       ↓
Store (SQLite, WAL mode)
       ↑
StreamClient.tail() (async iteration)
       ↑
Frontend / Debugger
```

---

## SQLite Schema (`taui/store/store.py`)

```sql
CREATE TABLE streams (
    stream_id   TEXT PRIMARY KEY,       -- e.g. "agents/abc-123"
    parent_id   TEXT REFERENCES streams(stream_id),  -- for sub-agents
    created_at  REAL NOT NULL,
    closed      INTEGER DEFAULT 0,       -- 1 = no more appends
    closed_at   REAL
);

CREATE TABLE events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_id   TEXT NOT NULL REFERENCES streams(stream_id),
    offset      INTEGER NOT NULL,        -- position within stream
    type        TEXT NOT NULL,           -- EventType enum value
    data        TEXT NOT NULL,           -- JSON payload
    created_at  REAL NOT NULL,
    UNIQUE(stream_id, offset)           -- offset uniqueness per stream
);

CREATE INDEX idx_events_stream_offset ON events(stream_id, offset);
```

**Database location**: `<workspace>/.taui/store.db`  
**Journal mode**: WAL (Write-Ahead Logging) for concurrent reads during writes.

---

## Event Types (`taui/store/events.py`)

```python
class EventType(str, Enum):
    # Agent lifecycle
    STREAM_START = "stream_start"       # Agent begins
    STREAM_END = "stream_end"           # Agent finishes
    STATE_CHANGE = "state_change"       # thinking → tool_execution → ...

    # Messages
    USER_MESSAGE = "user_message"       # User input
    ASSISTANT_MESSAGE = "assistant_message"  # LLM text output
    SYSTEM_MESSAGE = "system_message"   # System prompt changes

    # Tool cycle
    TOOL_CALL = "tool_call"             # {name, arguments, call_id}
    TOOL_RESULT = "tool_result"         # {content, error, call_id}

    # Streaming
    TOKEN = "token"                     # Individual token (for streaming UI)

    # Interaction
    QUESTION = "question"               # Agent asks user
    ANSWER = "answer"                   # User responds

    # Tracking
    USAGE = "usage"                     # {input_tokens, output_tokens, ...}
    ERROR = "error"                     # {error: str}
```

### Event Record

```python
@dataclass(frozen=True, slots=True)
class Event:
    stream_id: str
    offset: int                 # Position in stream (0-indexed)
    type: EventType
    data: dict[str, Any]        # JSON-decoded payload
    created_at: float           # Unix timestamp
```

---

## Store API (`taui/store/store.py`)

### Lifecycle

```python
store = Store(workspace_path)     # or Store(workspace_path, db_path=custom_path)
await store.connect()             # Opens DB, creates schema
await store.close()               # Commits, closes DB, wakes all waiters
```

### Stream CRUD

```python
await store.create_stream("agents/abc-123")                  # → True (created) or False (exists)
await store.create_stream("sub/child", parent_id="agents/abc-123")  # Sub-agent stream
await store.stream_exists(stream_id)                         # → bool
await store.get_stream_info(stream_id)                       # → dict with length
await store.close_stream(stream_id)                          # No more appends
await store.is_closed(stream_id)                             # → bool
```

### Append

```python
offset = await store.append(stream_id, EventType.STATE_CHANGE, {"state": "thinking"})
# Auto-assigns next offset

offset = await store.append(stream_id, event_type, data, offset=5)
# Explicit offset — idempotent if type+data match, raises OffsetConflictError if different
```

**Idempotency**: if you append at an offset that already has identical type+data, it's a no-op. Different data at same offset raises `OffsetConflictError`. This enables safe retries.

### Read

```python
events = await store.read(stream_id, from_offset=0, limit=1000)   # → list[Event]
length = await store.get_length(stream_id)                         # → int (max offset + 1)
```

### Live-tail

```python
got_data = await store.wait_for_new(stream_id, timeout=30.0)  # → bool
# Blocks until new data arrives or timeout
# Wakes on: append(), close_stream(), close()
```

**Implementation**: uses `asyncio.Event` per stream per waiter. `_notify()` sets all events on append/close.

---

## StreamClient (`taui/store/stream.py`)

High-level wrapper over Store used by agent components:

```python
client = StreamClient(store)

# Writing
await client.ensure_stream(stream_id)                    # Idempotent create
await client.append(stream_id, EventType.TOOL_CALL, data)
await client.close_stream(stream_id)

# Reading
events = await client.read(stream_id, from_offset=5)
events = await client.read_all(stream_id)                # All events

# Live-tail (async generator)
async for event in client.tail(stream_id, from_offset=0):
    # Catches up from offset, then blocks waiting for new events
    # Exits when stream is closed
    print(event.type, event.data)
```

**`tail()`** is the key consumer interface:
1. Reads existing events from `from_offset`
2. Yields them
3. Checks if stream is closed → exits if so
4. Calls `store.wait_for_new()` with poll_timeout
5. Loops back to step 1

---

## Error Types

```python
StreamNotFoundError(stream_id)    # Stream doesn't exist
StreamClosedError(stream_id)      # Append to closed stream
OffsetConflictError(stream_id, offset)  # Conflicting data at offset
```

---

## How the Agent Uses Streams

```python
# AgentLoop._emit() writes to stream
async def _emit(self, event_type, data):
    if self._stream:
        await self._stream.append(self.stream_id, event_type, data)

# Stream ID format: "agents/{agent_id}"
# Sub-agents (future): "agents/{parent_id}/sub/{child_id}"
```

Events emitted during a typical run:
```
offset 0: STREAM_START          {agent_id: "abc123"}
offset 1: USER_MESSAGE          {text: "Fix the bug in main.py"}
offset 2: STATE_CHANGE          {state: "thinking", turn: 0}
offset 3: ASSISTANT_MESSAGE     {text: "I'll look at the file..."}
offset 4: TOOL_CALL             {name: "read", arguments: {path: "main.py"}, call_id: "tc_1"}
offset 5: TOOL_RESULT           {content: "1| import sys...", error: false, call_id: "tc_1"}
offset 6: USAGE                 {input_tokens: 1200, output_tokens: 150}
offset 7: STATE_CHANGE          {state: "thinking", turn: 1}
...
offset N: STREAM_END            {reason: "complete", turns: 3}
```

---

## Files

| File | Purpose |
|------|---------|
| `taui/store/events.py` | EventType enum, Event dataclass |
| `taui/store/store.py` | Store: SQLite backend, schema, CRUD, live-tail |
| `taui/store/stream.py` | StreamClient: high-level read/write/tail |
| `taui/store/__init__.py` | Re-exports |
