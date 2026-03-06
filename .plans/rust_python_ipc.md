# Rust-Python IPC Plan — WebSocket Bridge

**Goal:** Establish a reliable, bidirectional communication layer between the GPUI/Rust frontend and the Python backend, so the UI can display live state (spec tree, agent events, Box results) and the user can drive agent execution from the native UI.

**Preconditions:** The `ui/` Rust crate exists with GPUI shell scaffolding. The `taui/` Python package has the tool system (Phase 3a), agent loop primitives, and spec tree model. The two are currently unconnected.

**Reference:** `.plans/ui_plan.md` §6.9 (backend integration), `.plans/main_plan.md` §5 (core interface).

---

## 1. Architecture Overview

Rust owns the process lifecycle. Python runs as a managed child process serving a WebSocket API.

```
┌──────────────────────────────────────────────────────────────┐
│  Rust (GPUI) Process                                         │
│                                                              │
│  1. Spawns Python child process                              │
│  2. Python starts WebSocket server, prints port to stdout    │
│  3. Rust reads port from stdout                              │
│  4. Rust connects to ws://127.0.0.1:{port}                  │
│  5. Bidirectional JSON-RPC 2.0 messages over WebSocket       │
│                                                              │
│  Responsibilities:                                           │
│  - UI rendering (GPUI)                                       │
│  - User input handling                                       │
│  - Cached/projected state for rendering                      │
│  - Process lifecycle management                              │
│  - Reconnection on crash                                     │
└──────────┬───────────────────────────────────────────────────┘
           │  ws://127.0.0.1:{port}
           ▼
┌──────────────────────────────────────────────────────────────┐
│  Python Process (child of Rust)                              │
│                                                              │
│  Responsibilities:                                           │
│  - Agent logic (root + minion orchestration)                 │
│  - LLM provider calls                                        │
│  - Spec tree management (canonical state owner)              │
│  - Tool execution                                            │
│  - Session persistence                                       │
└──────────────────────────────────────────────────────────────┘
```

### 1.1 Key Design Decisions

| Decision | Rationale |
|---|---|
| Rust spawns Python (not independent processes) | Rust owns lifecycle; clean shutdown; no orphan processes |
| WebSocket (not stdio JSON-RPC) | Native bidirectional push; streaming LLM tokens without custom framing; easier debugging |
| Python picks a free port | No hardcoded ports; no conflicts; port communicated via stdout |
| JSON-RPC 2.0 over WebSocket | Well-specified request/response + notification pattern; no custom protocol needed |
| Python owns canonical state | Single source of truth for spec tree, agent state, sessions; Rust holds a projected cache |
| Granular updates (not full-state sync) | Efficient; only diffs/events flow after initial sync |

---

## 2. Startup Sequence

### 2.1 Rust Side

```
1. Resolve Python binary path (from config or `python3` / `.venv/bin/python`)
2. Spawn: `python -m taui.bridge serve`
   - Capture stdout (for port), stderr (for logs)
   - Set working directory to project workspace
3. Read first line from stdout: `PORT:{port}\n`
4. Connect WebSocket client to ws://127.0.0.1:{port}
5. Send `initialize` request (workspace path, UI capabilities)
6. Receive `initialized` response (server capabilities, protocol version)
7. Request full state snapshot (`get_spec_tree`, `get_session_state`)
8. Begin event subscription (notifications flow from Python → Rust)
```

### 2.2 Python Side

```
1. `taui.bridge.serve` entry point
2. Find a free port: `sock.bind(("127.0.0.1", 0))` → extract port
3. Print `PORT:{port}\n` to stdout, flush
4. Start asyncio WebSocket server on 127.0.0.1:{port}
5. Accept single connection from Rust
6. Enter message dispatch loop
```

### 2.3 Port Discovery Protocol

Python prints exactly one line to stdout before any other output:

```
PORT:8765
```

Rust reads stdout line-by-line. The first line matching `PORT:\d+` is the port. All subsequent stdout from Python is treated as log output (forwarded to Rust's log system).

If Rust does not receive a `PORT:` line within a configurable timeout (default: 10s), it kills the child and reports a startup failure.

---

## 3. Message Protocol — JSON-RPC 2.0 over WebSocket

All messages are JSON-RPC 2.0. Each WebSocket text frame contains exactly one JSON-RPC message.

### 3.1 Message Types

**Request** (expects a response):
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "update_spec_node",
  "params": { "node_id": "abc", "title": "New Title" }
}
```

**Response** (to a request):
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": { "ok": true }
}
```

**Error response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": { "code": -32600, "message": "Invalid request", "data": null }
}
```

**Notification** (no `id`, no response expected):
```json
{
  "jsonrpc": "2.0",
  "method": "agent/event",
  "params": { "type": "tool_start", "tool_name": "read_file", "spec_ref": "specs/auth.md#behavior" }
}
```

### 3.2 Direction Convention

- **Rust → Python:** Requests (user actions) and notifications (steering messages)
- **Python → Rust:** Responses, and notifications (state changes, streaming events)

Both sides can send requests. For example, Python sends `approval/request` when a tool needs user confirmation, and Rust responds with the user's decision.

---

## 4. Method Catalog

### 4.1 Lifecycle Methods

| Method | Direction | Purpose |
|---|---|---|
| `initialize` | Rust → Python | Handshake: send workspace path, UI capabilities |
| `initialized` | Python → Rust | Response: server capabilities, protocol version |
| `shutdown` | Rust → Python | Graceful shutdown request |
| `exit` | Rust → Python | Notification: process should terminate |

### 4.2 Spec Tree Methods

| Method | Direction | Purpose |
|---|---|---|
| `spec/getTree` | Rust → Python | Request full spec tree snapshot |
| `spec/getNode` | Rust → Python | Request single node details by `spec_ref` |
| `spec/updateNode` | Rust → Python | User edited a node (title, intent, criteria) |
| `spec/nodeChanged` | Python → Rust | Notification: node state changed (status, content) |
| `spec/treeChanged` | Python → Rust | Notification: structural change (node added/removed/moved) |

### 4.3 Execution Methods

| Method | Direction | Purpose |
|---|---|---|
| `run/start` | Rust → Python | Start execution from a `spec_ref` |
| `run/stop` | Rust → Python | Halt current execution |
| `run/status` | Rust → Python | Request current run status |

### 4.4 Agent Event Notifications (Python → Rust)

These are **notifications** (no `id`), streamed in real time:

| Method | Params | Purpose |
|---|---|---|
| `agent/event` | `AgentEvent` payload | Any agent event (tool start/end, thinking, error) |
| `agent/token` | `{ text, spec_ref }` | Streaming LLM token (high frequency) |
| `agent/boxCompleted` | `Box` payload | Minion completed, Box ready for inspection |
| `agent/taskStatusChanged` | `{ task_id, status, spec_ref }` | TaskGraph node status update |
| `agent/clarificationRequired` | `Clarification` payload | Blocking question for user |
| `agent/amendmentProposed` | `Amendment` payload | Spec amendment needs approval |

### 4.5 Approval Methods (Python → Rust → Python)

| Method | Direction | Purpose |
|---|---|---|
| `approval/request` | Python → Rust | Tool needs user confirmation |
| `approval/respond` | Rust → Python | User's decision (approve/deny) |
| `clarification/respond` | Rust → Python | User's answer to a clarification |
| `amendment/respond` | Rust → Python | User accepts/rejects amendment |

### 4.6 Steering

| Method | Direction | Purpose |
|---|---|---|
| `steering/message` | Rust → Python | User injects a steering message |

Params:
```json
{
  "text": "Focus on the error handling path",
  "target": "root" | "minion:<id>"
}
```

---

## 5. State Sync Strategy

### 5.1 Canonical State Ownership

**Python owns:**
- Spec tree (structure, content, status)
- Agent state (running/idle, active minions)
- Session data (messages, usage, read tracking)
- TaskGraph (plan, execution order, task status)
- Box history

**Rust holds (projected cache):**
- Rendered spec tree (for UI display)
- Current run status and event log
- Pending approvals and clarifications
- Last-known TaskGraph state

### 5.2 Initial Sync (on connect / reconnect)

1. Rust sends `spec/getTree` → receives full tree snapshot
2. Rust sends `run/status` → receives current execution state (if any)
3. Rust subscribes to all notifications (implicit; Python pushes after handshake)

### 5.3 Incremental Sync (steady state)

- Python pushes `spec/nodeChanged` and `spec/treeChanged` notifications as state changes
- Rust applies changes to its local cache and triggers GPUI re-renders
- For user edits, Rust applies **optimistic updates** to the UI immediately, then sends the change to Python. If Python rejects, Rust rolls back.

### 5.4 Streaming LLM Tokens

`agent/token` notifications are high-frequency (one per token). To avoid overwhelming the UI:

- Python batches tokens into small chunks (e.g., every 50ms or 10 tokens, whichever comes first)
- Rust renders token chunks, not individual tokens
- Rust maintains a text buffer per active agent stream and appends on each notification

### 5.5 Reconnection Protocol

If the WebSocket disconnects (Python crash, network issue):

1. Rust detects disconnect (WebSocket `close` or `error`)
2. Rust shows "Reconnecting..." in UI status bar
3. If the Python child process has exited:
   a. Restart the Python process (same startup sequence)
   b. Reconnect and perform full state sync
4. If the Python process is still alive:
   a. Attempt WebSocket reconnect with exponential backoff (100ms, 200ms, 400ms, ..., max 5s)
   b. On reconnect, perform full state sync
5. After 30s of failed reconnects, show error state and offer manual retry

---

## 6. Implementation Plan

### 6.1 Python Side — `taui/bridge/`

New module: `taui/bridge/`

| File | Purpose |
|---|---|
| `taui/bridge/__init__.py` | Re-exports |
| `taui/bridge/server.py` | WebSocket server: port discovery, connection accept, message dispatch |
| `taui/bridge/protocol.py` | JSON-RPC 2.0 message types, serialization, validation |
| `taui/bridge/handlers.py` | Method handlers: maps method names to handler functions |
| `taui/bridge/state.py` | State snapshot builders (spec tree → JSON, run status → JSON) |
| `taui/bridge/__main__.py` | `python -m taui.bridge` entry point |

**Dependencies:**
- `websockets` — lightweight async WebSocket server (add to `pyproject.toml`)
- `pydantic` — message validation (already likely available, or use dataclasses)

**Server skeleton:**

```python
# taui/bridge/server.py
import asyncio
import json
import socket
import sys
from websockets.asyncio.server import serve

async def handle_connection(websocket):
    async for raw in websocket:
        msg = json.loads(raw)
        response = await dispatch(msg)
        if response is not None:  # requests get responses; notifications don't
            await websocket.send(json.dumps(response))

async def run_server():
    # Find free port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    # Announce port
    print(f"PORT:{port}", flush=True)

    # Start server
    async with serve(handle_connection, "127.0.0.1", port) as server:
        await server.serve_forever()
```

### 6.2 Rust Side — `ui/src/services/`

| File | Purpose |
|---|---|
| `ui/src/services/process_manager.rs` | Spawn Python, read port from stdout, manage lifecycle |
| `ui/src/services/ws_client.rs` | WebSocket client: connect, send, receive, reconnect |
| `ui/src/services/rpc.rs` | JSON-RPC 2.0 framing: request/response correlation, notification dispatch |
| `ui/src/services/backend_client.rs` | High-level API: typed methods wrapping RPC calls |
| `ui/src/services/event_stream.rs` | Notification consumer: routes agent events to GPUI models |
| `ui/src/services/state_cache.rs` | Local state cache: spec tree, run status, pending approvals |

**Crate dependencies (add to `ui/Cargo.toml`):**
- `tokio-tungstenite` — async WebSocket client
- `serde_json` — JSON serialization
- `serde` (with derive) — struct serialization
- `tokio` (with `process`, `io`, `time` features) — async runtime, child process

**Process manager skeleton:**

```rust
// ui/src/services/process_manager.rs
use tokio::process::Command;
use tokio::io::{AsyncBufReadExt, BufReader};

pub struct PythonProcess {
    child: tokio::process::Child,
    port: u16,
}

impl PythonProcess {
    pub async fn spawn(workspace: &Path) -> Result<Self, BridgeError> {
        let mut child = Command::new("python3")
            .args(["-m", "taui.bridge", "serve"])
            .current_dir(workspace)
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()?;

        let stdout = child.stdout.take().unwrap();
        let mut reader = BufReader::new(stdout).lines();

        // Read port with timeout
        let port = tokio::time::timeout(Duration::from_secs(10), async {
            while let Some(line) = reader.next_line().await? {
                if let Some(port_str) = line.strip_prefix("PORT:") {
                    return Ok(port_str.parse::<u16>()?);
                }
            }
            Err(BridgeError::NoPortReceived)
        }).await??;

        Ok(Self { child, port })
    }

    pub fn port(&self) -> u16 { self.port }

    pub async fn shutdown(&mut self) -> Result<(), BridgeError> {
        // Send SIGTERM, wait, then SIGKILL if needed
        self.child.kill().await?;
        Ok(())
    }
}
```

### 6.3 GPUI Integration Pattern

The bridge runs on a background async task. State updates are pushed into GPUI via `cx.update_model()` from the async context.

```rust
// Conceptual wiring in app startup
fn start_backend(cx: &mut AppContext, state: Model<AppState>) {
    cx.spawn(|mut cx| async move {
        // 1. Spawn Python
        let process = PythonProcess::spawn(&workspace).await?;

        // 2. Connect WebSocket
        let ws = WsClient::connect(process.port()).await?;

        // 3. Initialize handshake
        ws.request("initialize", json!({ "workspace": workspace })).await?;

        // 4. Full state sync
        let tree = ws.request("spec/getTree", json!({})).await?;
        cx.update_model(&state, |state, cx| {
            state.spec_tree = parse_spec_tree(tree);
            cx.notify();
        })?;

        // 5. Listen for notifications
        loop {
            match ws.recv().await? {
                Message::Notification { method, params } => {
                    cx.update_model(&state, |state, cx| {
                        state.apply_notification(&method, params);
                        cx.notify(); // triggers GPUI re-render
                    })?;
                }
                Message::Request { id, method, params } => {
                    // Handle Python → Rust requests (e.g., approval)
                    let response = handle_server_request(&method, params, &state, &mut cx).await;
                    ws.respond(id, response).await?;
                }
            }
        }
    }).detach();
}
```

---

## 7. Data Types (Shared Contract)

These types are defined in both Rust (serde structs) and Python (dataclasses/pydantic). They form the wire contract.

### 7.1 Spec Tree

```json
{
  "nodes": [
    {
      "spec_ref": "specs/_main.md#project-structure",
      "title": "Project Structure",
      "intent": "Define overall project layout",
      "status": "ready",
      "depth": 1,
      "parent_ref": null,
      "children": ["specs/_main.md#auth", "specs/_main.md#agent"],
      "depends_on": [],
      "has_acceptance_criteria": true
    }
  ]
}
```

### 7.2 Agent Event

```json
{
  "type": "tool_end",
  "timestamp": "2026-03-06T12:00:00Z",
  "spec_ref": "specs/auth.md#behavior",
  "agent_id": "root",
  "data": {
    "tool_name": "edit_file",
    "result": { "content": "File updated", "error": false },
    "duration_ms": 42
  }
}
```

### 7.3 Approval Request

```json
{
  "request_id": "apr_001",
  "tool_name": "bash",
  "arguments": { "command": "npm install" },
  "spec_ref": "specs/setup.md#dependencies",
  "agent_id": "minion_3",
  "preview": "Run: npm install"
}
```

---

## 8. Error Handling

### 8.1 JSON-RPC Error Codes

| Code | Meaning |
|---|---|
| -32700 | Parse error (malformed JSON) |
| -32600 | Invalid request (missing required fields) |
| -32601 | Method not found |
| -32602 | Invalid params |
| -32603 | Internal error |
| -32000 | Server error: agent not running |
| -32001 | Server error: spec node not found |
| -32002 | Server error: execution in progress |

### 8.2 Rust-Side Error Handling

- WebSocket disconnect → trigger reconnection protocol (§5.5)
- Request timeout (default 30s) → return error to caller, log warning
- Malformed response → log error, drop message
- Python process exit → detect via child handle, trigger restart

### 8.3 Python-Side Error Handling

- Malformed request → send JSON-RPC error response
- Handler exception → catch, send internal error response, log traceback
- WebSocket disconnect → clean up resources, shut down (Rust will restart)

---

## 9. Security Considerations

- WebSocket binds to `127.0.0.1` only (no network exposure)
- No authentication on the WebSocket (localhost-only, single client)
- Python process inherits Rust's environment (workspace-confined)
- Tool execution still goes through the Policy system (unchanged)
- Port is ephemeral and not predictable

---

## 10. Files to Create

### Python Side

| # | File | Purpose |
|---|---|---|
| 1 | `taui/bridge/__init__.py` | Re-exports |
| 2 | `taui/bridge/__main__.py` | `python -m taui.bridge` entry point |
| 3 | `taui/bridge/server.py` | WebSocket server, port discovery, connection management |
| 4 | `taui/bridge/protocol.py` | JSON-RPC 2.0 message types and helpers |
| 5 | `taui/bridge/handlers.py` | Method dispatch table and handler implementations |
| 6 | `taui/bridge/state.py` | State snapshot serialization (spec tree, run status) |
| 7 | `tests/test_bridge_protocol.py` | Protocol serialization and dispatch tests |
| 8 | `tests/test_bridge_server.py` | Server startup, port discovery, basic round-trip |

### Rust Side

| # | File | Purpose |
|---|---|---|
| 9 | `ui/src/services/mod.rs` | Module declarations |
| 10 | `ui/src/services/process_manager.rs` | Python child process lifecycle |
| 11 | `ui/src/services/ws_client.rs` | WebSocket client with reconnection |
| 12 | `ui/src/services/rpc.rs` | JSON-RPC 2.0 framing and correlation |
| 13 | `ui/src/services/backend_client.rs` | Typed high-level API over RPC |
| 14 | `ui/src/services/event_stream.rs` | Notification → GPUI model updater |
| 15 | `ui/src/services/state_cache.rs` | Local projected state cache |
| 16 | `ui/src/services/types.rs` | Shared wire types (serde structs) |
| 17 | `ui/tests/bridge_smoke.rs` | Spawn Python, connect, round-trip test |

### Modified Files

| File | Change |
|---|---|
| `pyproject.toml` | Add `websockets` dependency |
| `ui/Cargo.toml` | Add `tokio-tungstenite`, `serde_json`, `tokio` dependencies |
| `ui/src/main.rs` | Wire up backend spawn on app start |
| `ui/src/app/state.rs` | Add spec tree cache, notification application |

---

## 11. Build Order

```
Phase 1: Protocol Foundation
  1. taui/bridge/protocol.py          — JSON-RPC types
  2. ui/src/services/rpc.rs           — JSON-RPC types (Rust mirror)
  3. tests/test_bridge_protocol.py    — protocol round-trip tests

Phase 2: Server + Client
  4. taui/bridge/server.py            — WebSocket server + port discovery
  5. taui/bridge/__main__.py          — entry point
  6. ui/src/services/process_manager.rs — spawn Python, read port
  7. ui/src/services/ws_client.rs     — WebSocket connect + reconnect

Phase 3: Method Handlers
  8. taui/bridge/handlers.py          — initialize, spec/getTree, run/start
  9. taui/bridge/state.py             — state snapshot builders
  10. ui/src/services/backend_client.rs — typed request wrappers
  11. ui/src/services/types.rs         — shared wire types

Phase 4: Event Streaming
  12. ui/src/services/event_stream.rs  — notification → GPUI
  13. ui/src/services/state_cache.rs   — local state projection

Phase 5: Integration
  14. ui/src/main.rs                   — wire backend into app startup
  15. ui/tests/bridge_smoke.rs         — end-to-end test
  16. tests/test_bridge_server.py      — Python server tests
```

---

## 12. Verification Criteria

This plan is complete when:

1. `python -m taui.bridge serve` starts a WebSocket server and prints `PORT:{port}` to stdout
2. Rust can spawn the Python process, read the port, and connect via WebSocket
3. `initialize` handshake completes successfully
4. `spec/getTree` returns a valid spec tree snapshot
5. `agent/event` notifications stream to Rust in real time during execution
6. `approval/request` from Python surfaces in the UI; user response flows back
7. Reconnection works: kill Python, Rust restarts it and re-syncs state
8. Token streaming (`agent/token`) renders in the UI without visible lag
9. All protocol tests pass (`tests/test_bridge_protocol.py`)
10. Smoke test passes: spawn → connect → request → notification → shutdown

---

## 13. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Token streaming overwhelms UI | Batch tokens on Python side (50ms / 10 tokens); Rust buffers before render |
| Python crash loses in-flight state | Session persistence (SQLite) survives crashes; Rust re-syncs on reconnect |
| Port collision on startup | `sock.bind(("127.0.0.1", 0))` lets OS pick a free port; no hardcoded ports |
| WebSocket library mismatch | Pin `websockets` version in `pyproject.toml`; use `tokio-tungstenite` (mature, well-maintained) |
| Latency for approval round-trips | Approval requests block the agent; UI renders them with high priority; no queuing delay |
| GPUI thread safety | All `cx.update_model()` calls happen from `cx.spawn()` async tasks; GPUI handles the dispatch |
| Multiple UI clients (future) | Current design is single-client. If needed later, Python server can accept multiple connections with session isolation |

---

## 14. Open Considerations

1. **Binary protocol (future):** JSON-RPC is sufficient for now. If profiling shows serialization overhead, consider MessagePack or Protobuf for high-frequency messages (`agent/token`).
2. **Multiple workspaces:** Current design is one Python process per workspace. Multi-workspace support would require either multiple bridge processes or workspace multiplexing in the protocol.
3. **Remote backend:** The localhost WebSocket can be extended to support remote Python backends (e.g., for cloud-hosted agent execution) by adding auth and TLS. Not in scope now.
4. **Health checks:** Consider adding a periodic `ping`/`pong` at the application level (on top of WebSocket pings) to detect stale connections faster.
