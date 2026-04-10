---
title: Server
last_updated: 2026-04-10
---

# Server

The WebSocket JSON-RPC server — request dispatch, connection lifecycle, and state management.

Depends on: [Backend](backend.md), [Tangle Module](tangle-module.md), [Agent System](agent-system.md)

## Responsibility

Owns the communication layer between frontend and backend. Receives JSON-RPC requests over WebSocket,
dispatches to appropriate handlers, and pushes state updates and streaming events back to the frontend.

The entry point is `taui/server/app.py:create_app`, a FastAPI app factory that wires together all
subsystems under a shared lifespan. Active WebSocket connections are tracked by
`taui/server/app.py:_ConnectionManager`. Every incoming message is parsed by
`taui/server/protocol.py:parse_request` into a `taui/server/protocol.py:JsonRpcRequest` and then
routed through `taui/server/handlers.py:MethodHandlers.dispatch` to the correct handler method.

Specifically:

- WebSocket connection management (connect, disconnect, reconnect) via `taui/server/app.py:_ConnectionManager`
- JSON-RPC request/response protocol via `taui/server/protocol.py:parse_request`, `taui/server/protocol.py:result_message`, and `taui/server/protocol.py:error_message`
- RPC method routing to tangle, UI, agent, prompts, and symbol handlers inside `taui/server/handlers.py:MethodHandlers`
- State snapshot construction and delivery on connect via `taui/server/handlers.py:_handle_ui_snapshot`
- Agent event streaming (subscribe/unsubscribe) via `taui/server/handlers.py:_handle_agent_subscribe` and `taui/server/handlers.py:_handle_agent_unsubscribe`
- UI state management (tabs, layout, theme) via `taui/server/handlers.py:_handle_ui_open_tab`, `taui/server/handlers.py:_handle_ui_close_tab`, `taui/server/handlers.py:_handle_ui_set_active_tab`, `taui/server/handlers.py:_handle_ui_update_layout`, and `taui/server/handlers.py:_handle_ui_set_theme`, all backed by `settings.json` read/write
- Active agent run tracking via `taui/server/state.py:RunProcess` and `taui/server/state.py:RunState`

## Invariants

- All RPC methods use the `namespace/method` convention (e.g., `tangle/getTree`, `ui/snapshot`).
- The `ui/snapshot` RPC (handled by `taui/server/handlers.py:_handle_ui_snapshot`) returns the full UI state on connect — the frontend renders from this.
- UI state changes go through RPC → backend updates `settings.json` → pushes update. Never direct frontend mutation.
- Agent streaming uses subscribe/unsubscribe pattern — frontend subscribes to a session via `taui/server/handlers.py:_handle_agent_subscribe`, backend pushes events, frontend unsubscribes via `taui/server/handlers.py:_handle_agent_unsubscribe`.

## Interfaces

RPC method namespaces and their handler implementations:

| Namespace | Method | Handler |
|---|---|---|
| `tangle/*` | `getTree` | `taui/server/handlers.py:_handle_spec_get_tree` |
| `tangle/*` | `getNode` | `taui/server/handlers.py:_handle_spec_get_node` |
| `tangle/*` | `updateNode` | `taui/server/handlers.py:_handle_spec_update_node` |
| `tangle/*` | `createSiblingNode` | `taui/server/handlers.py:_handle_spec_create_sibling` |
| `tangle/*` | `indentNode` | `taui/server/handlers.py:_handle_spec_indent_node` |
| `tangle/*` | `outdentNode` | `taui/server/handlers.py:_handle_spec_outdent_node` |
| `tangle/*` | `getNodeSourceRange`, `getNodeCodeRefs`, `setNodeCollapsed`, `getBacklinks` | `taui/server/handlers.py:MethodHandlers` (dispatch router) |
| `ui/*` | `snapshot` | `taui/server/handlers.py:_handle_ui_snapshot` |
| `ui/*` | `openTab` | `taui/server/handlers.py:_handle_ui_open_tab` |
| `ui/*` | `closeTab` | `taui/server/handlers.py:_handle_ui_close_tab` |
| `ui/*` | `setActiveTab` | `taui/server/handlers.py:_handle_ui_set_active_tab` |
| `ui/*` | `updateLayout` | `taui/server/handlers.py:_handle_ui_update_layout` |
| `ui/*` | `setTheme` | `taui/server/handlers.py:_handle_ui_set_theme` |
| `ui/*` | `saveTab`, `nodeEdited` | `taui/server/handlers.py:MethodHandlers` (dispatch router) |
| `agent/*` | `subscribe` | `taui/server/handlers.py:_handle_agent_subscribe` |
| `agent/*` | `unsubscribe` | `taui/server/handlers.py:_handle_agent_unsubscribe` |
| `agent/*` | `send` | `taui/server/handlers.py:_handle_agent_send` |
| `agent/*` | `cancel` | `taui/server/handlers.py:_handle_agent_cancel` |
| `agent/*` | `listSessions` | `taui/server/handlers.py:MethodHandlers` (dispatch router) |
| `prompts/*` | `list` | `taui/server/handlers.py:_handle_prompts_list` |
| `prompts/*` | `get` | `taui/server/handlers.py:_handle_prompts_get` |
| `prompts/*` | `update` | `taui/server/handlers.py:_handle_prompts_update` |
| `prompts/*` | `reset` | `taui/server/handlers.py:_handle_prompts_reset` |
| `symbols/*` | `resolve`, `search` | `taui/server/handlers.py:MethodHandlers` (dispatch router) |

The dispatch router dict at `taui/server/handlers.py:MethodHandlers` (lines 124–347) maps every
`"namespace/method"` string to its handler callable. Adding a new RPC method means adding an entry
there and implementing the corresponding `_handle_*` method on `taui/server/handlers.py:MethodHandlers`.

## Key Components

### App — `taui/server/app.py:create_app`

FastAPI app factory with lifespan management. Constructs the application, registers the WebSocket
route, and starts/stops subsystems (database, service layer, settings store) inside an `asynccontextmanager`
lifespan. Active connections are tracked by `taui/server/app.py:_ConnectionManager`, which exposes
connect/disconnect helpers and lets the server broadcast to all clients. The health check HTTP endpoint
(`taui/server/app.py:health_check`) is also registered here.

### Handlers — `taui/server/handlers.py:MethodHandlers`

All RPC method handlers live on this single class (77–2003). `taui/server/handlers.py:MethodHandlers.__init__`
(77–122) accepts `db`, `service`, `settings_store`, `manager`, and other collaborators injected by
`taui/server/app.py:create_app`. The `dispatch` method is the single entry point called per message;
it looks up the method string in the router dict (124–347) and delegates.

Handler groups by namespace:

- **Tangle CRUD**: `taui/server/handlers.py:_handle_spec_get_tree` (350–370), `taui/server/handlers.py:_handle_spec_get_node` (372–400), `taui/server/handlers.py:_handle_spec_update_node` (402–450), `taui/server/handlers.py:_handle_spec_create_sibling` (452–500), `taui/server/handlers.py:_handle_spec_indent_node` (502–530), `taui/server/handlers.py:_handle_spec_outdent_node` (532–560)
- **UI state**: `taui/server/handlers.py:_handle_ui_snapshot` (1366–1383), `taui/server/handlers.py:_handle_ui_open_tab` (1385–1397), `taui/server/handlers.py:_handle_ui_close_tab` (1399–1415), `taui/server/handlers.py:_handle_ui_set_active_tab` (1417–1430), `taui/server/handlers.py:_handle_ui_update_layout` (1432–1450), `taui/server/handlers.py:_handle_ui_set_theme` (1452–1454)
- **Prompts**: `taui/server/handlers.py:_handle_prompts_list` (1456–1459), `taui/server/handlers.py:_handle_prompts_get` (1461–1466), `taui/server/handlers.py:_handle_prompts_update` (1468–1472), `taui/server/handlers.py:_handle_prompts_reset` (1474–1480)
- **Agent streaming**: `taui/server/handlers.py:_handle_agent_subscribe` (1482–1520), `taui/server/handlers.py:_handle_agent_unsubscribe` (1522–1540), `taui/server/handlers.py:_handle_agent_send` (1542–1600), `taui/server/handlers.py:_handle_agent_cancel` (1602–1620)

### Protocol — `taui/server/protocol.py`

JSON-RPC message parsing and serialization. `taui/server/protocol.py:JsonRpcRequest` (21–29) is the
parsed request dataclass carrying `id`, `method`, and `params`. `taui/server/protocol.py:parse_request`
(48–74) validates raw JSON and raises on malformed input. Responses are built by
`taui/server/protocol.py:result_message` (77–82) for success and `taui/server/protocol.py:error_message`
(85–99) for error conditions.

### State — `taui/server/state.py`

Agent run tracking. `taui/server/state.py:RunProcess` (12–36) is a dataclass that captures everything
about an active agent run (process handle, session id, etc.). `taui/server/state.py:RunState` (39–54)
manages the set of active runs and per-session subscriber sets, coordinating between
`taui/server/handlers.py:_handle_agent_subscribe` and `taui/server/handlers.py:_handle_agent_cancel`.

### Server — `taui/server/server.py`

Server startup and uvicorn configuration. Calls `taui/server/app.py:create_app` and passes the resulting
ASGI app to uvicorn with the configured host, port, and reload settings.

### Rename Status

The `spec → tangle` rename is substantially complete in the server:

- All public RPC method names use `tangle/*` (not `spec/*`) — enforced in the dispatch router at `taui/server/handlers.py:MethodHandlers` (lines 124–347)
- `taui/server/state.py:RunProcess` uses `tangle_ref` as primary field (with `spec_ref` alias)
- Internal handler methods on `taui/server/handlers.py:MethodHandlers` still named `_handle_spec_*` (cosmetic inconsistency)
- `taui/server/handlers.py:MethodHandlers.__init__` still accepts both `tangles_path` and `specs_path` for backward compat
- Exception handling uses `SpecServiceError` / `SpecNotFoundError` (aliased from `Tangle*`)

## Code References

- `taui/server/__init__.py`
- `taui/server/app.py:create_app` — FastAPI app factory (lines 45–195)
- `taui/server/app.py:_ConnectionManager` — active WebSocket connection tracker (lines 19–43)
- `taui/server/app.py:health_check` — HTTP health endpoint
- `taui/server/handlers.py:MethodHandlers` — all RPC method handlers (lines 77–2003)
- `taui/server/handlers.py:MethodHandlers.__init__` — dependency injection (lines 77–122)
- `taui/server/handlers.py:MethodHandlers` dispatch router dict (lines 124–347)
- `taui/server/protocol.py:JsonRpcRequest` — parsed request dataclass (lines 21–29)
- `taui/server/protocol.py:parse_request` — raw JSON validation (lines 48–74)
- `taui/server/protocol.py:result_message` — success response builder (lines 77–82)
- `taui/server/protocol.py:error_message` — error response builder (lines 85–99)
- `taui/server/state.py:RunProcess` — active agent run dataclass (lines 12–36)
- `taui/server/state.py:RunState` — active run + subscription manager (lines 39–54)
- `taui/server/server.py` — uvicorn startup and configuration
- `taui/server/__main__.py`

## Verification

- `tests/test_server_app.py` — RPC method integration tests
- `tests/test_server_protocol.py` — JSON-RPC protocol parsing tests (exercises `taui/server/protocol.py:parse_request`, `taui/server/protocol.py:result_message`, `taui/server/protocol.py:error_message`)
- `tests/test_server_startup.py` — Server lifecycle tests (exercises `taui/server/app.py:create_app` lifespan)

```
pytest tests/test_server_app.py tests/test_server_protocol.py tests/test_server_startup.py -q
```

## Open Questions

- Should internal handler methods on `taui/server/handlers.py:MethodHandlers` be renamed from `_handle_spec_*` to `_handle_tangle_*`?
- Should the backward-compat `specs_path` constructor param in `taui/server/handlers.py:MethodHandlers.__init__` be removed?

## Related Features

- [Stateless UI](../features/stateless-ui.md)
- [Editable Prompts](../features/editable-prompts.md)

## Related Decisions

No decisions recorded yet.
