# Store & Streams

The Store is an append-only event log backed by SQLite. Every action in the system —
agent state changes, tool calls, messages, questions, token deltas — is persisted as an
event row. Nothing is ever updated or deleted; the log is the source of truth.

---

## Architecture

```
AgentLoop / TUI / Extensions
         │
         │  write events (EventType, data)
         ▼
  StreamClient                   ← high-level async producer/consumer API
  taui/store/stream.py
         │
         │  create_stream / append / read / wait_for_new
         ▼
     Store                       ← SQLite backend, schema, CRUD, live-tail
  taui/store/store.py
         │
         │  aiosqlite (WAL mode)
         ▼
  .taui/store.db                 ← append-only rows, never mutated
         │
         │  tail() / subscribe()
         ▼
  StreamClient.tail()            ← async generator consumed by TUI / replay
         │
         ▼
  TUI / Session replay / Diagnostics
```

---

## Database Location

```
<workspace>/.taui/store.db
```

Customizable via `Store(workspace, db_path=custom_path)`. The parent directory is
created automatically on `connect()`.

**Journal mode**: WAL (Write-Ahead Logging) — `PRAGMA journal_mode = WAL` — allows
concurrent readers during writes. `PRAGMA synchronous = NORMAL` balances durability and
throughput. A passive WAL checkpoint runs automatically every 100 writes.

---

## SQLite Schema

Defined in `taui/store/store.py` as `_SCHEMA`. Three tables:

```sql
-- Named, ordered sequences of events
CREATE TABLE IF NOT EXISTS streams (
    stream_id   TEXT PRIMARY KEY,                      -- e.g. "agents/abc-123"
    parent_id   TEXT REFERENCES streams(stream_id),   -- parent for sub-agent streams
    created_at  REAL NOT NULL,                         -- Unix timestamp (float)
    closed      INTEGER NOT NULL DEFAULT 0,            -- 1 = EOF, no more appends
    closed_at   REAL                                   -- Unix timestamp when closed
);

-- Immutable event rows; offset is the position within a stream
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_id   TEXT NOT NULL REFERENCES streams(stream_id),
    offset      INTEGER NOT NULL,                      -- 0-indexed position in stream
    type        TEXT NOT NULL,                         -- EventType enum string value
    data        TEXT NOT NULL,                         -- compact JSON payload
    created_at  REAL NOT NULL,                         -- Unix timestamp (float)
    UNIQUE(stream_id, offset)                          -- enforces offset uniqueness
);

CREATE INDEX IF NOT EXISTS idx_events_stream_offset
    ON events(stream_id, offset);

-- Session metadata (separate from event content)
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    stream_id     TEXT NOT NULL DEFAULT '',            -- associated event stream
    description   TEXT NOT NULL DEFAULT '',
    mode          TEXT NOT NULL DEFAULT 'normal',
    created_at    REAL NOT NULL,
    last_active   REAL NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0
);
```

The `stream_id` column in `sessions` is added via migration if absent, making the schema
forward-compatible with older databases.

---

## EventType Enum

Defined in `taui/store/events.py` as `EventType(StrEnum)`. Every event row carries
exactly one of these string values in its `type` column:

| Value | String | Description |
|---|---|---|
| `STREAM_START` | `"stream_start"` | Agent session begins |
| `STREAM_END` | `"stream_end"` | Agent session finishes (normal or error) |
| `STATE_CHANGE` | `"state_change"` | Agent transitions between states (e.g. `thinking → tool_execution`) |
| `USER_MESSAGE` | `"user_message"` | User input submitted to the agent |
| `ASSISTANT_MESSAGE` | `"assistant_message"` | Full LLM text response |
| `SYSTEM_MESSAGE` | `"system_message"` | System prompt or system-level message |
| `TOOL_CALL` | `"tool_call"` | Agent requests a tool execution |
| `TOOL_RESULT` | `"tool_result"` | Result returned from a tool |
| `TOKEN` | `"token"` | Individual streaming token delta for the TUI |
| `QUESTION` | `"question"` | Agent asks the user an inline question |
| `ANSWER` | `"answer"` | User's response to an inline question |
| `USAGE` | `"usage"` | Token usage statistics for the turn |
| `ERROR` | `"error"` | Error encountered during agent execution |

`EventType` extends `StrEnum` so enum values compare equal to plain strings and
serialize naturally to JSON without extra conversion.

---

## Event Dataclass

Defined in `taui/store/events.py`:

```python
@dataclass(frozen=True, slots=True)
class Event:
    stream_id:  str               # Identifies the stream (e.g. "agents/abc-123")
    offset:     int               # 0-indexed position within the stream
    type:       EventType         # One of the EventType enum values
    data:       dict[str, Any]    # JSON-decoded payload (structure varies by type)
    created_at: float             # Unix timestamp (seconds)
```

`frozen=True` and `slots=True` make Event instances immutable and memory-efficient.
The `data` payload is decoded from the stored compact JSON on read; it is never mutated
after construction.

---

## Error Types

Defined in `taui/store/store.py`:

```python
class StreamNotFoundError(Exception):
    """Raised when the requested stream does not exist."""
    stream_id: str

class StreamClosedError(Exception):
    """Raised when attempting to append to a closed stream."""
    stream_id: str

class OffsetConflictError(Exception):
    """Raised when an explicit offset conflicts with different existing event data."""
    stream_id: str
    offset: int
```

All three carry the `stream_id` attribute for programmatic handling. `OffsetConflictError`
additionally carries `offset`.

---

## Store API

`Store` is the low-level SQLite backend. Direct consumers are `StreamClient` and tests.
Most application code should use `StreamClient` instead.

### Lifecycle

```python
store = Store(workspace_path)
# or with a custom DB location:
store = Store(workspace_path, db_path=Path("/custom/path/store.db"))

await store.connect()    # Opens DB, enables WAL, creates schema, runs migrations
await store.close()      # Commits, closes connection, wakes all live-tail waiters
await store.checkpoint() # Explicit WAL checkpoint (also runs automatically every 100 writes)
```

`connect()` is idempotent — calling it twice is a no-op. `close()` wakes every
`asyncio.Event` registered by `wait_for_new()` so tailing coroutines can exit cleanly.

### Stream CRUD

```python
# Create a stream; returns True if created, False if already exists
created: bool = await store.create_stream("agents/abc-123")

# Create a child stream for a sub-agent
created: bool = await store.create_stream("agents/abc-123/sub/def-456",
                                          parent_id="agents/abc-123")

await store.stream_exists("agents/abc-123")    # → bool
await store.get_stream_info("agents/abc-123")  # → dict | None
# dict keys: stream_id, parent_id, created_at, closed, closed_at, length

await store.close_stream("agents/abc-123")     # Marks closed=1; raises StreamNotFoundError
await store.is_closed("agents/abc-123")        # → bool; raises StreamNotFoundError
await store.get_length("agents/abc-123")       # → int (max offset + 1, or 0)
```

### Append

```python
# Auto-assign next offset
offset: int = await store.append(
    stream_id,
    EventType.STATE_CHANGE,
    {"state": "thinking", "turn": 0},
)

# Explicit offset (for idempotent replay)
offset: int = await store.append(
    stream_id,
    EventType.TOOL_CALL,
    {"name": "read", "call_id": "tc_1"},
    offset=4,
)
```

**Idempotency**: if an explicit `offset` is given and the row already exists with
identical `type` and `data`, the call returns the offset without writing. If the
existing row has different content, `OffsetConflictError` is raised. This design allows
safe at-least-once delivery.

**Concurrency**: append uses `BEGIN IMMEDIATE` to serialise writes and prevent
lost-update races on the auto-increment offset calculation.

**WAL checkpoint**: a passive checkpoint runs every 100 successful writes to bound
WAL file growth.

### Read

```python
events: list[Event] = await store.read(
    stream_id,
    from_offset=0,   # default: start from the beginning
    limit=1000,      # default: 1000 events per call
)

length: int = await store.get_length(stream_id)
```

`read()` raises `StreamNotFoundError` if the stream does not exist.

### Live-tail

#### `wait_for_new`

```python
got_data: bool = await store.wait_for_new(stream_id, timeout=30.0)
# Returns True when woken by new data, False on timeout.
# Woken by: append(), close_stream(), close()
```

Registers an `asyncio.Event` for the given stream and blocks until it is set.
Multiple coroutines can wait on the same stream simultaneously.

#### `subscribe`

```python
async for event in store.subscribe(stream_id, from_offset=0, poll_interval=0.5):
    print(event.type, event.data)
```

Async generator that catches up from `from_offset` and then polls for new events,
yielding each one as it arrives. Exits when the store is closed (`self._db is None`).
Prefer `StreamClient.tail()` for application code — it handles stream closure more
precisely.

### Session CRUD

```python
# Create a session record (idempotent — INSERT OR IGNORE)
await store.create_session(
    session_id,
    mode="normal",       # default
    stream_id="agents/abc-123",
)

# Update mutable fields; always updates last_active
await store.update_session(
    session_id,
    description="Fix login bug",
    message_count=5,
    mode="normal",
    stream_id="agents/abc-123",
)

# List sessions, newest first
sessions: list[dict] = await store.list_sessions(limit=20)

# List with parent session resolved through stream parent links
sessions: list[dict] = await store.list_sessions_with_parents(limit=50)
# Each dict may include parent_session_id when a parent stream exists

# Get a single session
session: dict | None = await store.get_session(session_id)
```

Session dicts contain: `session_id`, `stream_id`, `description`, `mode`,
`created_at`, `last_active`, `message_count`.

---

## StreamClient API

`StreamClient` (`taui/store/stream.py`) is the high-level async facade used by
`AgentLoop`, the TUI, and session replay. It wraps `Store` and adds semantic projection
methods that hide raw `EventType` and offset details from callers.

```python
client = StreamClient(store)
```

### Stream Lifecycle

```python
await client.ensure_stream(stream_id)                        # Idempotent create
await client.ensure_stream(stream_id, parent_id="agents/x") # With parent
await client.close_stream(stream_id)                         # Signal EOF; logs on missing stream
```

### Writing

```python
offset: int = await client.append(stream_id, EventType.TOOL_CALL, {
    "name": "bash",
    "arguments": {"command": "ls"},
    "call_id": "tc_42",
})
```

Appends at the next available offset. Returns the offset written.

### Reading

```python
events: list[Event] = await client.read(stream_id, from_offset=5, limit=100)
events: list[Event] = await client.read_all(stream_id)   # limit=2^31

exists: bool = await client.stream_exists(stream_id)
length: int  = await client.get_length(stream_id)
```

### Semantic Projections

These methods reconstruct higher-level structures from raw events without exposing
`EventType`, offsets, or the event model to callers.

```python
from taui.session_replay import ReplayTranscript, ReplayItem, ToolPair

# Full conversation as display items + agent messages
transcript: ReplayTranscript = await client.load_conversation(stream_id)

# Items grouped by turn (one list per user message)
turns: list[list[ReplayItem]] = await client.load_turns(stream_id)

# All tool calls paired with their results (result=None if pending)
pairs: list[ToolPair] = await client.load_tool_history(stream_id)
```

`load_conversation` is the canonical way to reconstruct a session for replay or context
building — never parse raw events manually when these projections cover the use case.

### Tail (live async generator)

```python
async for event in client.tail(stream_id, from_offset=0, poll_timeout=30.0):
    print(event.type, event.data)
```

`tail()` is the primary live-consumer interface:

1. Reads existing events from `from_offset` in batches of 100.
2. Yields each event and advances the local offset cursor.
3. Checks `is_closed()` — exits if stream is done.
4. If no new events were returned, calls `store.wait_for_new(timeout=poll_timeout)`.
5. If `wait_for_new` returns `False` (timeout), checks `is_closed()` again.
6. Handles `StreamNotFoundError` from any step by exiting cleanly.
7. Loops back to step 1.

This means `tail()` will always drain any backlog before blocking, and will exit without
raising when the stream ends or disappears.

---

## Typical Event Sequence

Events emitted during a single agent turn:

```
offset  type                data (abbreviated)
──────  ──────────────────  ─────────────────────────────────────────────
0       STREAM_START        {agent_id: "abc123"}
1       USER_MESSAGE        {text: "Fix the null check in main.py"}
2       STATE_CHANGE        {state: "thinking", turn: 0}
3       TOKEN               {text: "I'll "}
4       TOKEN               {text: "read the file first."}
5       ASSISTANT_MESSAGE   {text: "I'll read the file first."}
6       TOOL_CALL           {name: "read", arguments: {path: "main.py"}, call_id: "tc_1"}
7       TOOL_RESULT         {content: "1| import sys\n...", error: false, call_id: "tc_1"}
8       STATE_CHANGE        {state: "thinking", turn: 1}
9       TOOL_CALL           {name: "edit", arguments: {...}, call_id: "tc_2"}
10      TOOL_RESULT         {content: "OK", error: false, call_id: "tc_2"}
11      ASSISTANT_MESSAGE   {text: "Done. I've added the null check."}
12      USAGE               {input_tokens: 1420, output_tokens: 210, model: "..."}
13      STREAM_END          {reason: "complete", turns: 2}
```

---

## Source Files

| File | Purpose |
|---|---|
| `taui/store/events.py` | `EventType` enum, `Event` frozen dataclass |
| `taui/store/store.py` | `Store`: SQLite backend, schema, CRUD, live-tail, error types |
| `taui/store/stream.py` | `StreamClient`: high-level read/write/tail/projection API |
| `taui/store/__init__.py` | Re-exports |
| `taui/session_replay.py` | `replay_events`, `ReplayTranscript`, `ReplayItem`, `ToolPair` |
