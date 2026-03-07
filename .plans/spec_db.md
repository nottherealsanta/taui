# Spec DB — SQLite Ground Truth Layer

## Goal

Replace the current file-read-on-every-call approach with a SQLite database that is the **single source of truth** for the spec tree, the UI, and all agents. Markdown files become a human-readable reflection of the DB, kept in bidirectional sync.

The DB must also store **all agent conversation history** — LLM messages, tool calls, tool results, user answers, subagent spawns — making it the complete operational record for the project.

---

## Design Decisions (Locked)

| Decision | Choice |
|---|---|
| Node identity | Stable UUID per node (survives renames) |
| References | Node-to-node by UUID (replaces `depends_on` metadata) |
| Content storage | Full markdown content stored in DB per node |
| Sync direction | Bidirectional — DB is ground truth, markdown is regenerated |
| Write-back timing | Debounced (500ms) |
| Startup behavior | Full parse when no DB or stale DB |
| Respec scope | Full subtree from changed file |
| DB location | OS-dependent cache dir via `platformdirs` |
| Async library | `aiosqlite` |
| Node types | Separate `files` table + `nodes` table; nodes reference parent file |

---

## Database Schema

### Location

OS-dependent cache directory:
- macOS: `~/Library/Caches/taui/<workspace_hash>/spec.db`
- Linux: `~/.cache/taui/<workspace_hash>/spec.db`
- Windows: `~\AppData\Local\taui\Cache\<workspace_hash>\spec.db`

`workspace_hash` is a short hash of the absolute workspace path, ensuring one DB per project.

### Tables

#### `files` — Tracks all .md files in the spec tree

```sql
CREATE TABLE files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    rel_path      TEXT    NOT NULL UNIQUE,   -- e.g. "specs/server.md"
    content_hash  TEXT    NOT NULL,          -- SHA-256 of file content
    last_seen     REAL    NOT NULL,          -- epoch timestamp of last taui index
    mtime_ns      INTEGER NOT NULL           -- file's os.stat st_mtime_ns at last index
);
```

#### `nodes` — Every heading-level node in the spec tree

```sql
CREATE TABLE nodes (
    id              TEXT    PRIMARY KEY,       -- UUID v4 (stable across renames)
    file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    spec_ref        TEXT    NOT NULL UNIQUE,   -- "specs/server.md#auth-flow" (current)
    anchor          TEXT    NOT NULL,          -- slugified heading title
    title           TEXT    NOT NULL,
    depth           INTEGER NOT NULL,          -- tree depth (1 = root-level child)
    heading_level   INTEGER,                   -- 1-6, NULL for plain-doc nodes
    line_start      INTEGER,                   -- 1-indexed line in source file
    line_end        INTEGER,
    intent          TEXT,                       -- first prose paragraph after heading
    status          TEXT,                       -- draft|ready|in-progress|done|blocked
    content         TEXT    NOT NULL DEFAULT '',-- full markdown section body
    sort_order      INTEGER NOT NULL DEFAULT 0,-- global tree ordering
    created_at      REAL    NOT NULL,
    updated_at      REAL    NOT NULL
);

CREATE INDEX idx_nodes_file_id ON nodes(file_id);
CREATE INDEX idx_nodes_depth   ON nodes(depth);
CREATE INDEX idx_nodes_status  ON nodes(status);
```

#### `edges` — Parent-child relationships

Derived from heading depth within files and cross-file markdown links.

```sql
CREATE TABLE edges (
    parent_id   TEXT    NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    child_id    TEXT    NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (parent_id, child_id)
);

CREATE INDEX idx_edges_child ON edges(child_id);
```

Key queries this enables:

- **All children of a node:** `SELECT * FROM nodes WHERE id IN (SELECT child_id FROM edges WHERE parent_id = ?) ORDER BY sort_order`
- **All ancestors to root:** recursive CTE walking `edges` upward via `parent_id`
- **All siblings:** `SELECT * FROM nodes WHERE id IN (SELECT child_id FROM edges WHERE parent_id = (SELECT parent_id FROM edges WHERE child_id = ?)) ORDER BY sort_order`

```sql
-- Ancestors to root (recursive CTE)
WITH RECURSIVE ancestors(node_id, depth) AS (
    SELECT parent_id, 1 FROM edges WHERE child_id = :start_id
    UNION ALL
    SELECT e.parent_id, a.depth + 1
    FROM edges e JOIN ancestors a ON e.child_id = a.node_id
)
SELECT n.* FROM ancestors a JOIN nodes n ON n.id = a.node_id
ORDER BY a.depth DESC;
```

#### `node_refs` — Node-to-node references

Nodes can reference other heading-nodes. References use UUIDs (stable across renames).

```sql
CREATE TABLE node_refs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    from_node   TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    to_node     TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    UNIQUE(from_node, to_node)
);

CREATE INDEX idx_node_refs_to ON node_refs(to_node);
```

#### `node_metadata` — Key-value metadata per node

Stores `code_ref`, `verification`, and any other `{{key: value}}` metadata.

```sql
CREATE TABLE node_metadata (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id  TEXT    NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    key      TEXT    NOT NULL,    -- "code_ref", "verification", etc.
    value    TEXT    NOT NULL
);

CREATE INDEX idx_node_metadata_node ON node_metadata(node_id);
CREATE INDEX idx_node_metadata_key  ON node_metadata(node_id, key);
```

---

### Agent Conversation Tables

#### `sessions` — Agent execution sessions

```sql
CREATE TABLE sessions (
    id          TEXT PRIMARY KEY,              -- UUID
    spec_ref    TEXT,                          -- which spec node this session targets (nullable for ad-hoc)
    node_id     TEXT REFERENCES nodes(id) ON DELETE SET NULL,
    parent_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL, -- for subagent spawns
    status      TEXT NOT NULL DEFAULT 'active',-- active|completed|failed|cancelled
    model       TEXT,                          -- e.g. "claude-opus-4-20250514", "gemini-2.5-pro"
    provider    TEXT,                          -- e.g. "copilot", "antigravity"
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE INDEX idx_sessions_node    ON sessions(node_id);
CREATE INDEX idx_sessions_parent  ON sessions(parent_session_id);
CREATE INDEX idx_sessions_status  ON sessions(status);
```

#### `messages` — All LLM messages (both directions)

```sql
CREATE TABLE messages (
    id          TEXT PRIMARY KEY,              -- UUID
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,                 -- "system"|"user"|"assistant"|"tool"
    content     TEXT,                          -- text content (nullable for pure tool_call messages)
    name        TEXT,                          -- tool name (for role=tool responses)
    tool_call_id TEXT,                         -- links tool result back to the tool_call
    seq         INTEGER NOT NULL,              -- ordering within session
    created_at  REAL NOT NULL,

    -- token accounting
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL
);

CREATE INDEX idx_messages_session ON messages(session_id, seq);
```

#### `tool_calls` — Tool invocations within assistant messages

```sql
CREATE TABLE tool_calls (
    id          TEXT PRIMARY KEY,              -- tool_call_id from the LLM
    message_id  TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    tool_name   TEXT NOT NULL,
    arguments   TEXT NOT NULL,                 -- JSON string of arguments
    created_at  REAL NOT NULL
);

CREATE INDEX idx_tool_calls_message ON tool_calls(message_id);
```

#### `tool_results` — Results from tool executions

```sql
CREATE TABLE tool_results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_call_id  TEXT NOT NULL REFERENCES tool_calls(id) ON DELETE CASCADE,
    output        TEXT,                        -- tool output (may be large)
    error         TEXT,                        -- error message if tool failed
    duration_ms   INTEGER,                     -- execution time
    created_at    REAL NOT NULL
);

CREATE INDEX idx_tool_results_call ON tool_results(tool_call_id);
```

#### `questions` — Clarification questions from LLM to user

```sql
CREATE TABLE questions (
    id          TEXT PRIMARY KEY,              -- UUID
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    message_id  TEXT REFERENCES messages(id) ON DELETE SET NULL,
    node_id     TEXT REFERENCES nodes(id) ON DELETE SET NULL,
    question    TEXT NOT NULL,
    options     TEXT,                          -- JSON array of option strings
    answer      TEXT,                          -- user's answer (NULL until answered)
    status      TEXT NOT NULL DEFAULT 'pending', -- pending|answered|dismissed
    created_at  REAL NOT NULL,
    answered_at REAL
);

CREATE INDEX idx_questions_session ON questions(session_id);
CREATE INDEX idx_questions_node    ON questions(node_id);
CREATE INDEX idx_questions_status  ON questions(status);
```

#### `subagent_spawns` — Tracks parent-child agent relationships

```sql
CREATE TABLE subagent_spawns (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    child_session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    purpose           TEXT,                    -- brief description of why subagent was spawned
    created_at        REAL NOT NULL,
    UNIQUE(parent_session_id, child_session_id)
);

CREATE INDEX idx_spawns_parent ON subagent_spawns(parent_session_id);
CREATE INDEX idx_spawns_child  ON subagent_spawns(child_session_id);
```

---

## Architecture

### New Modules (under `taui/specs/`)

#### 1. `db.py` — `SpecDB`

Core database manager.

- Opens/creates SQLite via `aiosqlite`
- Schema creation and migration (version table + incremental migrations)
- CRUD for all tables
- Fast query methods:
  - `get_tree() -> list[SpecNode]` — ordered by `sort_order`
  - `get_node(node_id) -> SpecNodeDetail`
  - `get_node_by_ref(spec_ref) -> SpecNodeDetail`
  - `get_children(node_id) -> list[SpecNode]`
  - `get_ancestors(node_id) -> list[SpecNode]` — recursive CTE, root-first
  - `get_siblings(node_id) -> list[SpecNode]`
  - `get_subtree(node_id) -> list[SpecNode]` — recursive CTE, all descendants
  - `get_referencing_nodes(node_id) -> list[SpecNode]` — nodes that reference this one
  - `get_referenced_nodes(node_id) -> list[SpecNode]` — nodes this one references
- Session/message CRUD:
  - `create_session(...)`, `get_session(id)`, `update_session_status(...)`
  - `append_message(...)`, `get_messages(session_id)`
  - `record_tool_call(...)`, `record_tool_result(...)`
  - `record_question(...)`, `record_answer(...)`
  - `record_subagent_spawn(...)`
- DB path resolution: `platformdirs.user_cache_dir("taui") / hash(workspace) / "spec.db"`

#### 2. `sync.py` — `SpecSync`

Bidirectional sync engine.

- **`full_sync()`** — called on startup:
  1. Walk `specs/` for all `.md` files
  2. For each file: check `files` table
     - New file: parse, insert file + nodes
     - Existing file: compare `mtime_ns`
       - Unchanged: skip
       - Changed: compare `content_hash`
         - Same hash: update `mtime_ns`, skip
         - Different hash: re-parse file, diff nodes, update DB, then recurse into all child files linked from it (full subtree respec)
  3. Files in DB but not on disk: cascade-delete file + its nodes + edges
- **`check_for_changes()`** — lightweight scan, can be called periodically or on-demand
- **UUID matching:** on re-parse, match existing nodes by `(file_id, anchor)` pair to preserve UUIDs; new anchors get new UUIDs; missing anchors get their nodes deleted

#### 3. `writer.py` — `SpecMarkdownWriter`

DB-to-markdown serializer.

- `schedule_writeback(file_id)` — debounced (500ms), coalesces multiple rapid mutations
- `write_file(file_id)` — reads all nodes for a file from DB, serializes to markdown:
  - Heading lines from `heading_level` + `title`
  - `{{status: ...}}` metadata
  - `{{code_ref: ...}}`, `{{verification: ...}}` from `node_metadata`
  - Intent text
  - Section content
  - Cross-file links preserved
- After writing, updates `files.content_hash` and `files.mtime_ns` to prevent the sync engine from re-triggering respec on its own writes

### Modified Modules

#### 4. `service.py` — `SpecService` (refactored)

- Constructor opens `SpecDB`, runs `SpecSync.full_sync()` on first call
- All public methods become **async**:
  - `async get_tree()` — queries DB
  - `async get_node(spec_ref)` — queries DB
  - `async update_node(spec_ref, patch)` — writes DB, schedules markdown writeback
- Keeps the same public API shape (methods, params, return types) — only async wrapper changes
- File-based helpers (`_read_lines`, `_write_lines`, `_index_file`) become internal to `SpecSync`

#### 5. `models.py` — Updated models

- `SpecNode` gains `id: str` (UUID)
- `SpecNodeDetail` gains `id: str`
- `to_dict()` includes UUID
- New: `SpecFile` dataclass for the `files` table row

#### 6. `handlers.py` — Async dispatch

- `dispatch()` awaits async `SpecService` methods
- No API shape changes from the client perspective (same JSON-RPC methods)

#### 7. `__main__.py` / `app.py` — Startup wiring

- Trigger `full_sync()` during server startup (lifespan event)
- Optionally start a background task for periodic file-change polling

---

## Startup Flow

```
1. Server starts
2. SpecService.__init__: opens SpecDB at cache dir
3. SpecSync.full_sync():
   a. Walk specs/ directory for all .md files
   b. For each file:
      - Not in DB? → parse, insert file row + all nodes + edges
      - In DB, mtime unchanged? → skip
      - In DB, mtime changed?
        - Hash unchanged? → update mtime, skip
        - Hash changed? → re-parse, diff, update nodes/edges
          → recurse into child files (full subtree respec)
   c. Files in DB not on disk? → cascade-delete
4. Server ready — all reads come from DB
```

## Mutation Flow (API Write)

```
1. Client sends spec/updateNode {spec_ref, patch}
2. SpecService.update_node():
   a. Find node in DB by spec_ref
   b. Apply patch to DB (title, intent, content, status)
   c. If title changed: update spec_ref, anchor; update edges if needed
   d. Return updated SpecNodeDetail immediately from DB
3. Schedule debounced markdown writeback (500ms)
4. Push spec/nodeChanged notification (and spec/treeChanged if title changed)
5. After debounce: SpecMarkdownWriter regenerates affected .md file(s)
6. Update files.content_hash + files.mtime_ns to suppress respec
```

## Respec Flow (External File Edit)

```
1. Periodic check or on-demand: scan files table
2. For each file: os.stat() → compare mtime_ns
3. If mtime changed: read file content → SHA-256 → compare with stored hash
4. If hash truly different:
   a. Re-parse the changed file's nodes
   b. Match existing nodes by (file_id, anchor) to preserve UUIDs
   c. Update/insert/delete nodes in DB
   d. Rebuild edges for affected nodes
   e. Find all child files linked from this file
   f. Recursively respec those child files
5. Push spec/treeChanged notification over WebSocket
```

---

## Implementation Order

| Step | Task | Files |
|------|------|-------|
| 1 | Add `aiosqlite` + `platformdirs` deps | `pyproject.toml` |
| 2 | Create `SpecDB` — schema, connection, CRUD | `taui/specs/db.py` |
| 3 | Update models with UUID + `SpecFile` | `taui/specs/models.py` |
| 4 | Create `SpecSync` — markdown-to-DB ingestion | `taui/specs/sync.py` |
| 5 | Create `SpecMarkdownWriter` — DB-to-markdown | `taui/specs/writer.py` |
| 6 | Refactor `SpecService` to use DB | `taui/specs/service.py` |
| 7 | Update handlers to await async service | `taui/server/handlers.py` |
| 8 | Wire startup sync + optional background poller | `taui/__main__.py`, `taui/server/app.py` |
| 9 | Update `__init__.py` exports | `taui/specs/__init__.py` |
| 10 | Tests for DB, sync, writer, service | `tests/` |

---

## Key Queries the DB Must Support Fast

| Query | Use case |
|---|---|
| All children of node X | Tree expand in UI, agent scoping |
| All ancestors of node X to root | Breadcrumb, context gathering |
| All siblings of node X | Navigation, sibling status checks |
| Full subtree under node X | Respec scope, agent delegation |
| Nodes referencing node X | Impact analysis |
| Nodes referenced by node X | Dependency resolution |
| All nodes with status Y | Dashboard, work queue |
| All messages in session S | Conversation replay |
| All sessions targeting node X | History of agent work on a spec |
| All pending questions | User attention queue |
| All tool calls in session S | Debugging, audit |
| Full conversation thread (messages + tool calls + results) | UI display, context rebuild |
