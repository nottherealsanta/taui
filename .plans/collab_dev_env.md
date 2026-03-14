# Collaborative Dev Environment — Full Redesign Plan

## Overview

Taui is a collaborative spec-authoring environment where humans and agents co-edit a spec tree in real time. The primary communication surface is the tree itself — agents edit nodes, ask questions via ephemeral UI elements (not actual tree nodes), and show their status inline. A persistent WebSocket replaces the current per-call connection model. The backend buffers all agent detail events and streams them to the frontend on demand.

This plan covers: protocol redesign, agent session architecture, spec-tree abstraction, UI interaction model, persistence schema, and phased implementation.

---

## 1. Connection Model

### Current (broken)
- New WebSocket per RPC call → notifications sent to nobody
- Frontend polls `getTreeDetailed` after every mutation

### New: Single persistent WebSocket
- One WebSocket connection per UI session, kept alive for the entire app lifetime
- All JSON-RPC requests, responses, and server-initiated notifications multiplex over this single connection
- Reconnect logic with exponential backoff on disconnect
- Server still enforces single-client (code 1013 reject for second client)

### Message types on the wire
```
→ Request:      {"jsonrpc":"2.0","id":N,"method":"...","params":{}}
← Response:     {"jsonrpc":"2.0","id":N,"result":{}}
← Error:        {"jsonrpc":"2.0","id":N,"error":{"code":N,"message":"..."}}
← Notification: {"jsonrpc":"2.0","method":"...","params":{}}
→ Notification: {"jsonrpc":"2.0","method":"...","params":{}}  (client→server, e.g. steer)
```

No new transport — same JSON-RPC 2.0, just over a persistent connection.

---

## 2. Agent Architecture

### Hierarchy
```
User
 └─ Root Agent (1 per branch the user launches a task on)
     ├─ SubAgent A (spawned by root for a sub-task)
     ├─ SubAgent B
     └─ (max 2 sub-agents per root, configurable)
```

- **Root Agent**: bound to a spec-tree branch. Locks the branch exclusively. Receives steer/queue messages from user. Orchestrates sub-agents.
- **SubAgent**: spawned autonomously by a root agent via the `spawn_subagent` tool. The root gives the sub-agent a **context box** (mandate: task description + relevant spec content + constraints). The sub-agent works independently and returns a **result context box** (findings, proposed edits, research results) back to the root. The root is responsible for integrating sub-agent results and preventing conflicts — sub-agents do **not** acquire branch locks. The user can steer sub-agents via the detail panel.
- Sub-agent cap: **2 per root agent** (user-configurable in settings).
- Multiple root agents can be active simultaneously on **non-overlapping** branches.

### Agent State Machine
```
Idle → Running → Thinking → ToolExecution → Thinking → ...
                     ↓                          ↓
               AskingQuestion              Done → Idle
                     ↓
              WaitingForAnswer → Thinking
```

Additional states:
- `Stopping` — safe shutdown requested, finishing current tool call
- `Paused` — future (worktree phase)

### Branch Locking
- When a root agent starts a task on a branch, it acquires an **exclusive lock** on that branch (the node + all descendants). Only root agents acquire locks — sub-agents operate under the root's authority via the context box pattern.
- **Exclusive among root agents**: if another root agent tries to lock an overlapping branch, it must wait. The UI shows a "waiting for lock" indicator on the blocked agent. First-come-first-served.
- **User override**: the user can **nudge** a waiting agent to start anyway (e.g., if the user is just asking a general question about the project, the agent should be able to proceed). Nudged agents get read-only access to the locked branch.
- **Read-only access always allowed**: `spec_get_tree`, `spec_get_node`, and `spec_get_branch` are never blocked by locks. Any agent can read the full tree at any time. Locks only gate write operations.
- **User can still edit**: the lock is only enforced between agents, not against the user. When the user edits a locked node, two things happen:
  1. The tree updates visually (user sees their edit immediately)
  2. The edit is automatically sent to the root agent as a **steer message** (so the agent knows the user changed something)
- Before writing to a node, the agent always fetches the latest version to avoid overwriting user edits.
- Lock metadata: `{agent_id, locked_at}` stored per node in the DB (root agents only).
- Lock contention is surfaced in the UI: blocked agents show a "waiting" badge on their branch, with a "Start anyway" button for user override.

### Agent Tools (spec-tree abstraction)
The agent operates on the spec-tree abstraction only. It is **not allowed** to modify spec markdown files directly. Available tools:

**Spec-tree tools (agent-facing):**
- `spec_get_tree` — read full tree or subtree
- `spec_get_node(spec_ref)` — read a single node
- `spec_create_node(parent_ref, title, content)` — add child node
- `spec_create_sibling(spec_ref, title, content)` — add sibling after
- `spec_update_node(spec_ref, patch)` — edit node content
- `spec_delete_node(spec_ref)` — remove a node (with confirmation policy)
- `spec_move_node(spec_ref, new_parent_ref)` — reparent
- `spec_ask_question(spec_ref, question, options?)` — ask user a question (rendered as ephemeral UI overlay on spec_ref, not a real tree node)
- `spec_get_branch(spec_ref)` — get the full subtree rooted at spec_ref

**Code/execution tools (existing, unchanged):**
- `read_file`, `write_file`, `edit_file` — code files only
- `bash` — shell execution
- `glob`, `grep` — search

**Sub-agent spawning tool:**
- `spawn_subagent(task, context_box)` — root agent spawns a sub-agent with a context box (task description + relevant spec content + constraints). Sub-agent returns a result context box when done. Respects sub-agent cap.

**MCP tools:**
- All MCP server tools (`mcp:<server>`) are available to agents, subject to the same policy system (auto-approve / confirm / deny)

All spec-tree mutations go through the `SpecService` which handles:
1. Updating the SQLite-backed tree (source of truth)
2. Writing the tree back to markdown files on task completion (automatic, not per-mutation)

### Spec-Tree to File Mapping (revised)
```
specs/
  _main.md     ← contains root node + all L1 nodes as list items
  <l1-slug>.md ← each L1 node gets its own file with its children (L2+)
```
- No nested folders, just flat files
- `_main.md` holds the top-level structure
- Each L1 node title becomes a file (`<slugified-title>.md`)
- L2+ nodes are list items inside their L1 file
- This is handled entirely by the system's writeback logic, invisible to agents

---

## 3. Protocol — New RPC Methods & Notifications

### Agent Lifecycle (client → server)
| Method | Params | Returns | Description |
|--------|--------|---------|-------------|
| `agent/launch` | `{spec_ref, task, tier}` | `{agent_id, session_id}` | Launch a root agent on a branch. `tier` is `"senior"`, `"mid"`, or `"junior"` — maps to model/provider via user config |
| `agent/stop` | `{agent_id}` | `{ok}` | Safely stop agent (finishes current tool) |
| `agent/steer` | `{agent_id, message}` | `{ok}` | Send steer message to running agent |
| `agent/queue` | `{agent_id, message}` | `{ok}` | Queue a follow-up task |
| `agent/answerQuestion` | `{question_node_ref, answer}` | `{ok}` | Answer a question node |
| `agent/subscribe` | `{agent_id}` | `{backlog: AgentEvent[]}` | Subscribe to detail stream, get buffered backlog |
| `agent/unsubscribe` | `{agent_id}` | `{ok}` | Stop streaming details |
| `agent/list` | `{}` | `{agents: AgentInfo[]}` | List all active agents |
| `agent/history` | `{spec_ref?, limit?}` | `{sessions: SessionSummary[]}` | List past completed sessions (filterable by branch) |
| `agent/getSession` | `{agent_id}` | `{session: SessionDetail}` | Get full session detail for a past or active agent (messages, tool calls, events) |
| `agent/resume` | `{agent_id, task}` | `{new_agent_id, session_id}` | Start a **new** session that loads context (summary of messages, tool calls, outcomes) from a previous session. `task` is the user's query explaining why they're resuming. Returns a new agent_id — the old session is not mutated. |
| `agent/forceStart` | `{agent_id}` | `{ok}` | Override lock contention — allow a waiting agent to start with read-only access to the locked branch |

### Server → Client Notifications

**Always pushed (regardless of subscription):**
| Notification | Params | Description |
|-------------|--------|-------------|
| `spec/nodeCreated` | `{node, agent_id?}` | New node appeared in tree |
| `spec/nodeChanged` | `{node, agent_id?}` | Node content/status changed |
| `spec/nodeDeleted` | `{spec_ref, agent_id?}` | Node removed |
| `spec/treeChanged` | `{subtree_root?}` | Structural change (reparenting) |
| `agent/stateChanged` | `{agent_id, state, spec_ref}` | Agent entered new state |
| `agent/questionAsked` | `{agent_id, question_node}` | Agent created a question node |
| `agent/lockChanged` | `{spec_ref, agent_id?, locked}` | Branch lock acquired/released |
| `agent/lockContention` | `{agent_id, waiting_for_agent_id, spec_ref}` | Agent blocked waiting for a branch lock. UI shows "Start anyway" button for user override |
| `agent/toolBrief` | `{agent_id, tool_name}` | Brief ephemeral tool indicator (agent name + tool name, shown above message bar) |

**Pushed only when subscribed (detail stream):**
| Notification | Params | Description |
|-------------|--------|-------------|
| `agent/token` | `{agent_id, text, seq}` | Streaming LLM token |
| `agent/message` | `{agent_id, message}` | Complete assistant/tool message |
| `agent/toolCall` | `{agent_id, tool_name, arguments, call_id}` | Tool invocation started |
| `agent/toolResult` | `{agent_id, call_id, output, error?, duration_ms}` | Tool completed |

### Client → Server Notifications (fire-and-forget)
| Notification | Params | Description |
|-------------|--------|-------------|
| `ui/nodeEdited` | `{spec_ref, old_markdown, new_markdown}` | User edited a locked node (becomes steer) |

---

## 4. Backend Implementation

### 4.1 Agent Manager (new: `taui/agent/manager.py`)
Central coordinator for all agent sessions:

```python
class AgentManager:
    """Manages root agents and their sub-agents."""
    
    active_agents: dict[str, AgentRunner]      # agent_id → runner
    root_agents: dict[str, str]                 # spec_ref → root agent_id
    subscriptions: dict[str, set[str]]          # agent_id → set of subscriber IDs
    event_buffers: dict[str, list[AgentEvent]]  # agent_id → buffered events
    
    async def launch(spec_ref, task, model) -> AgentRunner
    async def stop(agent_id) -> None
    async def steer(agent_id, message) -> None
    async def queue(agent_id, message) -> None
    async def answer_question(question_node_ref, answer) -> None
    async def subscribe(agent_id) -> list[AgentEvent]  # returns backlog
    async def unsubscribe(agent_id) -> None
```

### 4.2 Agent Runner (new: `taui/agent/runner.py`)
Runs a single agent (root or sub) in an async task:

```python
class AgentRunner:
    """Async loop: think → act → observe → repeat."""
    
    agent_id: str
    session: Session                    # existing session.py
    spec_ref: str                       # branch this agent is working on
    parent_agent_id: str | None         # None for root agents
    state: AgentState                   # enum
    tier: str                           # "senior" | "mid" | "junior"
    steer_queue: asyncio.Queue          # incoming steer messages (delivered with next tool result)
    task_queue: asyncio.Queue           # queued follow-up tasks
    sub_agents: list[AgentRunner]       # spawned sub-agents (max from config)
    context_box: dict | None            # for sub-agents: mandate from root
    result_box: dict | None             # for sub-agents: findings returned to root
    event_callback: Callable            # emit events to manager
    llm: BaseLLM                        # resolved from tier → model config
    tools: ToolRegistry                 # builtins + MCP tools
    
    async def run(task: str) -> None    # main loop
    async def stop_safely() -> None     # finish current tool, then stop, cleanup questions
    async def spawn_subagent(task, context_box) -> AgentRunner  # respects cap, returns result_box
```

The runner emits `AgentEvent` objects for every action (token, tool call, tool result, state change, question). The manager buffers these and forwards to subscribers.

### 4.3 Spec-Tree Agent Tools (new: `taui/tools/builtins/spec_tree.py`)
Agent-facing tools that call `SpecService` methods:

- `spec_get_tree`, `spec_get_node`, `spec_get_branch` — read-only, never blocked by locks
- `spec_create_node`, `spec_create_sibling`, `spec_update_node`, `spec_delete_node`, `spec_move_node`
- `spec_ask_question` — sends a question to the user as an ephemeral UI element (overlay on the relevant node). Not a tree node. The question only exists while the root agent is alive. On answer: response is injected into the agent's conversation. On dismiss: agent proceeds without an answer.
- `spawn_subagent(task, context_box)` — root agent only, creates a sub-agent with a context box (mandate). Sub-agent returns a result context box. Respects configurable cap (default 2).

All are auto-approve policy except `spec_delete_node` (confirm).

### 4.4 Revised SpecService
- Add lock tracking: `lock_branch(spec_ref, agent_id)`, `unlock_branch(spec_ref, agent_id)` — root agents only
- Lock is **exclusive among root agents**: `lock_branch` blocks (async wait) if another root agent holds an overlapping lock. First-come-first-served. User can override via `agent/forceStart`.
- Read-only operations (`spec_get_tree`, `spec_get_node`, `spec_get_branch`) are never blocked by locks.
- Questions: handled as ephemeral agent-process state (stored in `agent_questions` table), rendered as UI overlays on the tree. Not stored as tree nodes. Cleaned up when root agent stops.
- **File writeback**: triggered automatically when a root agent finishes a task (state → Done). Not debounced per-mutation — the tree is the source of truth in SQLite, files are written out as a batch on task completion.
- After every mutation, emit notification via callback (not returned in DispatchResult — pushed directly on the WebSocket)

### 4.5 Revised WebSocket Server (`taui/server/app.py`)
- Single persistent connection
- `on_connect`: store the WebSocket reference
- `on_message`: parse JSON-RPC, dispatch, send response, then send any notifications
- Notification push: `AgentManager` and `SpecService` push notifications via a shared callback that writes to the stored WebSocket
- No more "new WS per call" pattern

---

## 5. UI Implementation

### 5.1 Spec Tree Pane (revised)

**Agent indicators (right side of each node row):**
- Small colored dot or icon on the rightmost side of a node row when an agent is working on it
- Different indicators for: root agent active, sub-agent active, question pending
- **Sub-agent current task**: each active sub-agent's current task description is shown in real time next to the relevant node. Updates live as the sub-agent progresses.
- Tooltip on hover showing agent name/task

**Real-time tree updates:**
- `spec/nodeCreated` → insert new node in arena, fade-in animation
- `spec/nodeChanged` → update node in arena, subtle fade-in on changed content
- `spec/nodeDeleted` → remove from arena, fade-out
- `spec/treeChanged` → rebuild affected subtree in arena
- No full-tree re-fetch. Incremental patching only.

**Question overlays (ephemeral, not tree nodes):**
- Rendered as a floating overlay / inline card attached to the relevant node (distinct from actual tree nodes)
- Shows the question text, optional answer buttons (for suggested options)
- Text input for free-form answer
- On answer: calls `agent/answerQuestion`, overlay vanishes, answer is injected into agent's conversation as context
- If dismissed: overlay vanishes, agent proceeds without an answer
- **Questions only exist while their root agent is alive** — when the root agent stops or completes, all pending questions are automatically cleaned up

**Locked branch visual:**
- Subtle background tint or left-border on locked nodes
- User can still type/edit — edits automatically become steer messages

### 5.2 Message Bar (new, below-tree)

Appears below the branch where a root agent is active:
```
┌─────────────────────────────────────────────────────┐
│  🔧 reading src/api.py  ›                           │   ← ephemeral tool indicator
├─────────────────────────────────────────────────────┤
│  Type a message...                    [Steer] [Queue]│   ← input bar
└─────────────────────────────────────────────────────┘
```

- **Ephemeral tool indicators**: appear above the input bar when agent runs tools. Shows agent name + tool name. Right chevron `›` opens the agent detail panel. Auto-dismiss after a few seconds.
- **Input bar**: text field with two send modes:
  - `Enter` → steer (default, configurable)
  - `Ctrl+Enter` → queue (configurable, can be swapped)
  - Two buttons for explicit choice: `[Steer]` `[Queue]`
- **Interrupt button**: appears when agent is running, sends `agent/stop`

### 5.3 Agent Detail Side Panel (new)

Slides in from the right when user clicks the `›` chevron on a tool indicator, or clicks an agent indicator on a node.

**Content:**
- **Header**: agent name, state badge (with tier: senior/mid/junior), branch it's working on
- **Event timeline**: scrollable list of:
  - LLM messages (streaming tokens when subscribed)
  - Tool calls with arguments (expandable)
  - Tool results (collapsible)
  - State transitions
  - Questions asked and answers received
- **Sub-agent list**: if root agent, shows active sub-agents with their **current task in real time**. Clicking one switches the detail view to that sub-agent's full history and live updates.
- **Session history**: user can browse past completed sessions for a root agent and view their full event timelines. Option to resume with a new task (creates a new session with context loaded from the old one).
- **Message bar at bottom**: 
  - For sub-agents: steer only
  - For root agents: steer and queue (same Enter/Ctrl+Enter pattern)

**Subscription lifecycle:**
1. Panel opens → sends `agent/subscribe(agent_id)`
2. Receives backlog (all buffered events) → renders history
3. Receives real-time `agent/token`, `agent/toolCall`, `agent/toolResult`, `agent/message` notifications → appends live
4. Panel closes → sends `agent/unsubscribe(agent_id)`

### 5.4 No Streaming for Tree, Streaming for Details
- **Spec tree**: changes arrive as discrete notifications (`nodeCreated`, `nodeChanged`). No token streaming in the tree. Nodes appear/update with fade-in animation.
- **Detail panel**: full streaming. LLM tokens arrive one by one. Tool outputs stream line by line. This is the "full transparency" view.

---

## 6. Persistence — New SQLite Tables

Added to the existing spec DB (or a separate `agents.db`):

```sql
-- Root and sub-agent sessions
CREATE TABLE agent_sessions (
    agent_id        TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,           -- links to Session object
    parent_agent_id TEXT,                     -- NULL for root agents
    spec_ref        TEXT NOT NULL,            -- branch being worked on
    task            TEXT NOT NULL,            -- the task description
    state           TEXT NOT NULL DEFAULT 'idle',  -- idle/running/thinking/tool_execution/asking_question/stopping/waiting_for_lock/done
    tier            TEXT NOT NULL DEFAULT 'mid',   -- senior/mid/junior
    model           TEXT,                          -- resolved from tier config
    provider        TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY (parent_agent_id) REFERENCES agent_sessions(agent_id)
);

-- LLM messages in a session
CREATE TABLE agent_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL,
    role            TEXT NOT NULL,            -- system/user/assistant/tool
    content         TEXT,
    tool_call_id    TEXT,
    name            TEXT,
    seq             INTEGER NOT NULL,         -- ordering within session
    created_at      TEXT NOT NULL,
    FOREIGN KEY (agent_id) REFERENCES agent_sessions(agent_id)
);

-- Tool calls made by agents
CREATE TABLE agent_tool_calls (
    call_id         TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL,
    message_id      INTEGER,
    tool_name       TEXT NOT NULL,
    arguments       TEXT NOT NULL,            -- JSON
    created_at      TEXT NOT NULL,
    FOREIGN KEY (agent_id) REFERENCES agent_sessions(agent_id),
    FOREIGN KEY (message_id) REFERENCES agent_messages(id)
);

-- Tool results
CREATE TABLE agent_tool_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id         TEXT NOT NULL,
    output          TEXT,
    error           TEXT,
    duration_ms     INTEGER,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (call_id) REFERENCES agent_tool_calls(call_id)
);

-- Questions asked by agents (also exist as tree nodes)
CREATE TABLE agent_questions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL,
    question_node_ref TEXT NOT NULL,          -- spec_ref of the question node
    question        TEXT NOT NULL,
    options         TEXT,                      -- JSON array of suggested answers, nullable
    answer          TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending/answered/dismissed
    created_at      TEXT NOT NULL,
    answered_at     TEXT,
    FOREIGN KEY (agent_id) REFERENCES agent_sessions(agent_id)
);

-- Buffered events for detail panel subscriptions
CREATE TABLE agent_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL,
    event_type      TEXT NOT NULL,            -- token/message/tool_call/tool_result/state_change/question
    payload         TEXT NOT NULL,            -- JSON
    seq             INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (agent_id) REFERENCES agent_sessions(agent_id)
);

-- Branch locks (root agents only, sub-agents use context box pattern)
CREATE TABLE branch_locks (
    spec_ref        TEXT NOT NULL,
    agent_id        TEXT NOT NULL,            -- always a root agent
    locked_at       TEXT NOT NULL,
    PRIMARY KEY (spec_ref, agent_id),
    FOREIGN KEY (agent_id) REFERENCES agent_sessions(agent_id)
);

-- Queued tasks for root agents
CREATE TABLE agent_task_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL,
    message         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending/started/done
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    FOREIGN KEY (agent_id) REFERENCES agent_sessions(agent_id)
);
```

### Spec nodes table — additions
```sql
ALTER TABLE nodes ADD COLUMN agent_id TEXT;  -- which agent created/owns this node, nullable
```

Note: Questions are **not** stored as tree nodes. They are ephemeral agent-process state stored in the `agent_questions` table and rendered as UI overlays. They are cleaned up when the root agent stops.

---

## 7. Steer & Queue Flow

### Steer (immediate context injection)
```
User types "focus on error handling" + hits Enter
  → client sends agent/steer {agent_id, message: "focus on error handling"}
  → server pushes message into runner's steer_queue
  → runner waits for current operation to complete (LLM response or tool execution)
  → steer message is delivered alongside the next tool call results
  → injected as a user message: "<<STEER>> focus on error handling"
  → LLM sees it as a priority instruction in the next think cycle
```

### Queue (deferred task)
```
User types "then add auth module" + hits Ctrl+Enter
  → client sends agent/queue {agent_id, message: "then add auth module"}
  → server inserts into agent_task_queue table
  → when current task finishes (state → Done), runner checks queue
  → picks next task, transitions back to Running
```

### User edits on locked branch → auto-steer
```
User edits node "API Design" while agent has it locked
  → frontend detects edit on locked node
  → sends ui/nodeEdited {spec_ref, old_markdown, new_markdown}
  → server applies the edit to the tree
  → server injects steer message to root agent:
    "<<USER_EDIT>> Node 'API Design' was edited by user. 
     Previous: <old content>
     New: <new content>
     Adjust your work accordingly."
```

---

## 8. Interruption / Safe Stop

```
User clicks interrupt (or sends agent/stop)
  → server sets agent state to "stopping"
  → runner checks stop flag after each tool call completes
  → if in LLM streaming: cancel the stream, keep partial response
  → if in tool execution: let current tool finish, then stop
  → for sub-agents: propagate stop to all children, wait for them
  → clean up all pending questions (dismiss ephemeral question overlays)
  → trigger file writeback (write current tree state to markdown files)
  → once all stopped: state → Idle, release branch locks
  → emit agent/stateChanged notification
```

The agent does NOT discard work done so far — all completed edits remain in the tree.

---

## 9. Implementation Phases

### Phase 1: Foundation — Persistent WebSocket + Incremental Tree Updates ✅
**Goal**: Real-time tree collaboration without agents

- [x] Refactor `app.py` to maintain a single persistent WebSocket
- [x] Frontend: persistent WS connection with reconnect logic
- [x] Frontend: listen for `spec/nodeChanged`, `spec/nodeCreated`, `spec/nodeDeleted`, `spec/treeChanged` — apply incremental patches to arena (no full re-fetch)
- [x] Backend: emit notifications directly on the WebSocket (not just returned in DispatchResult)
- [x] Add fade-in/fade-out animations for node changes
- [x] Tests: verify notification delivery, reconnect behavior

### Phase 2: Agent Core — Runner, Manager, Persistence ✅
**Goal**: Agents can run and be observed

- [x] Create `agent_sessions`, `agent_messages`, `agent_tool_calls`, `agent_tool_results`, `agent_events` tables
- [x] Implement `AgentRunner` — async loop with LLM + tool execution
- [x] Implement `AgentManager` — launch, stop, event buffering
- [x] Wire agent RPC methods: `agent/launch`, `agent/stop`, `agent/list`
- [x] Implement spec-tree agent tools (`spec_tree.py`)
- [x] Agent events buffered to `agent_events` table
- [x] Tests: agent lifecycle, tool execution, persistence

### Phase 3: User ↔ Agent Interaction ✅
**Goal**: Steer, queue, questions, and detail streaming

- [x] Implement `agent/steer`, `agent/queue` RPC methods
- [x] Implement steer/task queues in `AgentRunner`
- [x] Questions are ephemeral overlays (not tree nodes) — stored in `agent_questions` table, cleaned up on agent stop
- [x] Implement `spec_ask_question` tool + `agent/answerQuestion` RPC
- [x] Implement `agent/subscribe` / `agent/unsubscribe` with backlog
- [x] Implement detail streaming: `agent/toolCall`, `agent/toolResult`, `agent/message` (gated by subscription)
- [x] Branch locking: `branch_locks` table, `agent/lockChanged` notification, `acquire_branch_lock`/`release_branch_lock` in `AgentManager`
- [x] Auto-steer on user edits to locked nodes (`ui/nodeEdited`)
- [x] Tests: steer injection, queue ordering, question flow, subscription lifecycle (`tests/test_phase3.py`, `tests/test_phase3_rpc.py`)

### Phase 4: UI — Message Bar, Detail Panel, Indicators ✅
**Goal**: Full interactive UI

- [x] Agent indicators on tree node rows (right side) — blue dot (active), amber dot (question), tool brief text
- [x] Locked branch visual treatment — amber left border on locked nodes
- [x] Question node rendering with answer options + dismiss button (inline card overlay)
- [x] Message bar below tree (steer/queue input, tool brief indicator, stop button) — visible when any root agent is active
- [x] Agent detail side panel (event timeline: messages, tool calls, tool results, state changes) — 320px right panel, opens on blue dot click
- [x] Detail panel subscribe/unsubscribe lifecycle (agent_subscribe on open, agent_unsubscribe on close, backlog replay)
- [x] Interrupt (⏹ Stop) button in message bar
- [x] Enter → steer (default), Queue button for explicit queue

### Phase 5: Persistence & Recovery ✅
**Goal**: Survive restarts

- [x] On startup: reload active agent sessions from DB
- [x] Resume or mark-as-stopped agents that were running when app closed
- [x] Restore event buffers from `agent_events` table
- [x] Restore question states, branch locks
- [x] Test: kill server mid-task, restart, verify state recovery

### Phase 6: Revised Spec-Tree ↔ File Writeback ✅
**Goal**: Clean file mapping

- [x] `_main.md` contains root + all L1 nodes
- [x] Each L1 node gets `<slug>.md` with its L2+ descendants
- [x] No folders, flat structure
- [x] Writeback triggered automatically when root agent finishes a task (state → Done), not on every mutation
- [x] Also triggered on agent stop (safe stop writes current state before releasing locks)
- [x] Agent never touches files directly — only the spec-tree abstraction

### Future: Worktree Phase
- Git worktree-like branching for agents: agent works on a "spec branch" that can be reviewed and merged back into the main tree
- Enables parallel exploration without polluting the main spec
- Related to git worktree concepts — full design deferred to a later plan
- Current exclusive branch locking is the stepping stone: worktrees would allow overlapping work on the same branch via isolated copies

### Future: Token & Cost Tracking
- Per-session token usage tracking (input tokens, output tokens, total cost)
- Column on `agent_sessions` for cumulative token usage
- Budget/limit mechanism: configurable per-session or per-tier token caps
- UI indicator showing token burn rate and remaining budget
- Alerts when approaching limits; auto-stop when budget exceeded
- Deferred until core agent loop is stable

### Future: Git Integration
- Auto-commit after root agent completes a task (spec writeback + code changes)
- Configurable commit message templates
- Branch-per-agent-session option
- Deferred to a later plan

---

## 10. Workflow Modes

The same agent infrastructure supports multiple usage patterns:

| Workflow | Trigger | Agent does |
|----------|---------|------------|
| **Spec → Code sync** | User edits spec, triggers agent | Agent reads spec changes, updates codebase to reflect them |
| **Q&A / Exploration** | User selects node, asks a question | Agent researches and answers (may create child notes with findings) |
| **Spec ideation** | User asks agent to help write spec | Agent and user co-author spec nodes collaboratively (agent suggests, user steers) |
| **Full auto** | User describes desired change | Agent modifies spec, then implements code changes to match |

All workflows use the same `agent/launch` → steer/queue → `agent/stop` lifecycle. The difference is the system prompt and tool selection, which are determined by the task description and tier.

---

## 11. Model Tier Configuration

Users configure three tiers in settings, mapping each to a model/provider:

```toml
[agent.tiers]
senior = { provider = "codex", model = "o3-pro" }
mid    = { provider = "copilot", model = "gpt-4.1" }
junior = { provider = "gemini", model = "gemini-2.5-flash" }
```

- When launching an agent, user picks a tier (senior / mid / junior)
- The tier resolves to a concrete model + provider
- Sub-agents inherit the parent's tier by default (root can override when spawning)
- Sub-agent cap is also configurable: `agent.max_subagents = 2`

---

## 12. Key Design Decisions Summary

| Decision | Rationale |
|----------|----------|
| Single persistent WebSocket | Required for server-push (notifications, streaming) |
| Incremental tree updates (no full re-fetch) | Performance at scale, smooth animations |
| Agent operates on spec-tree abstraction, not files | Clean separation; file layout is a system concern |
| Exclusive locks among root agents, user can still edit | Prevents agent conflicts; user edits become steer |
| Sub-agents use context box, not locks | Root manages conflicts; sub-agents are stateless workers that receive mandates and return results |
| User can override lock contention | Read-only tasks (e.g., Q&A) shouldn't be blocked by write locks |
| Sub-agent spawning is autonomous (root decides) | Root agent manages complexity; user sets cap |
| Events buffered, streamed on demand | Multiple agents generate lots of data; don't flood UI |
| Questions are ephemeral overlays, not tree nodes | Part of agent process, not spec content. Cleaned up with agent. |
| Steer waits for current op, delivered with next tool result | No mid-stream interruption; clean injection point |
| Steer = Enter, Queue = Ctrl+Enter (configurable) | Steer is the common case during active agent work |
| File writeback on task completion, not per-mutation | Tree in SQLite is source of truth; files are a batch export |
| Safe stop (finish current tool, propagate to subs) | Prevents corrupted state from partial tool execution |
| Model tiers (senior/mid/junior) | Simple UX; user doesn't pick models, picks capability level |
| Resume creates new session with old context loaded | Clean separation; old sessions are immutable audit trail |
| Session history persists, resumable | User can review and continue past agent work |
| MCP tools available to agents | Extensibility via existing MCP server ecosystem |
| Everything persists in SQLite | Survive restarts, full audit trail |