---
title: Server
last_updated: 2026-04-11
---

# Server

The WebSocket JSON-RPC server — request dispatch, connection lifecycle, and state management.

Depends on: [Backend](backend.md), [Tangle Module](tangle-module.md), [Agent System](agent-system.md)

## Responsibility

Owns the communication layer between frontend and backend. Receives JSON-RPC requests over WebSocket, dispatches to appropriate handlers, and pushes state updates and streaming events back to the frontend.

- **Entry point** — `taui/server/app.py:create_app`, a FastAPI app factory that wires all subsystems under a shared lifespan
- **Connection management** — connect, disconnect, reconnect via `taui/server/app.py:_ConnectionManager`
- **Request routing** — every message parsed by `taui/server/protocol.py:parse_request` into a `taui/server/protocol.py:JsonRpcRequest`, then routed through `taui/server/handlers.py:MethodHandlers.dispatch`
  - Namespaces covered: tangle, UI, agent, prompts, symbols
- **Snapshot delivery** — full UI state delivered on connect via `taui/server/handlers.py:_handle_ui_snapshot`
- **Agent event streaming** — subscribe/unsubscribe via `taui/server/handlers.py:_handle_agent_subscribe` and `_handle_agent_unsubscribe`
- **UI state persistence** — tabs, layout, theme changes written to `settings.json`
  - Handlers: `_handle_ui_open_tab`, `_handle_ui_close_tab`, `_handle_ui_set_active_tab`, `_handle_ui_update_layout`, `_handle_ui_set_theme`
- **Active run tracking** — via `taui/server/state.py:RunProcess` and `taui/server/state.py:RunState`

## Invariants

- All RPC methods use the `namespace/method` convention (e.g., `tangle/getTree`, `ui/snapshot`)
- `ui/snapshot` (handled by `taui/server/handlers.py:_handle_ui_snapshot`) returns full UI state on connect — the frontend renders from this
- UI state changes go through RPC → backend updates `settings.json` → pushes update; never direct frontend mutation
- Agent streaming uses subscribe/unsubscribe pattern
  - Frontend subscribes via `_handle_agent_subscribe`, backend pushes events, frontend unsubscribes via `_handle_agent_unsubscribe`

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

Adding a new RPC method: add an entry in the dispatch router dict at `taui/server/handlers.py:MethodHandlers` (lines 124–347) and implement the corresponding `_handle_*` method.

## Key Components

- **App** (`taui/server/app.py:create_app`, lines 45–195) — FastAPI app factory with lifespan management
  - Constructs the app, registers the WebSocket route, starts/stops subsystems inside an `asynccontextmanager` lifespan
  - `taui/server/app.py:_ConnectionManager` (lines 19–43) — tracks open sockets and broadcasts to all clients
  - `taui/server/app.py:health_check` — HTTP `/health` route handler
- **Handlers** (`taui/server/handlers.py:MethodHandlers`, lines 77–2003) — all RPC method implementations
  - `__init__` (lines 77–122) accepts `db`, `service`, `settings_store`, `manager`, and other collaborators injected by `create_app`
  - Dispatch router (lines 124–347) maps `"namespace/method"` strings to handler callables
  - Tangle CRUD: `_handle_spec_get_tree` (350–370), `_handle_spec_get_node` (372–400), `_handle_spec_update_node` (402–450), `_handle_spec_create_sibling` (452–500), `_handle_spec_indent_node` (502–530), `_handle_spec_outdent_node` (532–560)
  - UI state: `_handle_ui_snapshot` (1366–1383), `_handle_ui_open_tab` (1385–1397), `_handle_ui_close_tab` (1399–1415), `_handle_ui_set_active_tab` (1417–1430), `_handle_ui_update_layout` (1432–1450), `_handle_ui_set_theme` (1452–1454)
  - Prompts: `_handle_prompts_list` (1456–1459), `_handle_prompts_get` (1461–1466), `_handle_prompts_update` (1468–1472), `_handle_prompts_reset` (1474–1480)
  - Agent streaming: `_handle_agent_subscribe` (1482–1520), `_handle_agent_unsubscribe` (1522–1540), `_handle_agent_send` (1542–1600), `_handle_agent_cancel` (1602–1620)
- **Protocol** (`taui/server/protocol.py`) — JSON-RPC message parsing and serialisation
  - `taui/server/protocol.py:JsonRpcRequest` (lines 21–29) — parsed request dataclass: `id`, `method`, `params`
  - `taui/server/protocol.py:parse_request` (lines 48–74) — validates raw JSON; raises on malformed input
  - `taui/server/protocol.py:result_message` (lines 77–82) — success response builder
  - `taui/server/protocol.py:error_message` (lines 85–99) — error response builder
- **State** (`taui/server/state.py`) — agent run tracking
  - `taui/server/state.py:RunProcess` (lines 12–36) — dataclass capturing everything about an active agent run
  - `taui/server/state.py:RunState` (lines 39–54) — manages the set of active runs and per-session subscriber sets
- **Server startup** (`taui/server/server.py`) — uvicorn configuration; calls `create_app` and passes the ASGI app with configured host, port, and reload settings

### Rename Status

The `spec → tangle` rename is substantially complete in the server:

- All public RPC method names use `tangle/*` — enforced in the dispatch router at `taui/server/handlers.py:MethodHandlers` (lines 124–347)
- `taui/server/state.py:RunProcess` uses `tangle_ref` as primary field (with `spec_ref` alias)
- Internal handler methods on `taui/server/handlers.py:MethodHandlers` still named `_handle_spec_*` (cosmetic inconsistency)
- `taui/server/handlers.py:MethodHandlers.__init__` still accepts both `tangles_path` and `specs_path` for backward compat
- Exception handling uses `SpecServiceError` / `SpecNotFoundError` (aliased from `Tangle*`)

## Verification

- `tests/test_server_app.py` — RPC method integration tests
- `tests/test_server_protocol.py` — JSON-RPC protocol parsing tests
  - Exercises `taui/server/protocol.py:parse_request`, `result_message`, `error_message`
- `tests/test_server_startup.py` — server lifecycle tests
  - Exercises `taui/server/app.py:create_app` lifespan

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
