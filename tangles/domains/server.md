---
title: Server
last_updated: 2026-04-10
---

# Server

The WebSocket JSON-RPC server — request dispatch, connection lifecycle, and state management.

Depends on: [Backend](backend.md), [Tangle Module](tangle-module.md), [Agent System](agent-system.md)

## Responsibility

Owns the communication layer between frontend and backend. Receives JSON-RPC requests over WebSocket, dispatches to appropriate handlers, and pushes state updates and streaming events back to the frontend.

Specifically:

- WebSocket connection management (connect, disconnect, reconnect)
- JSON-RPC request/response protocol
- RPC method routing to tangle, UI, agent, prompts, and symbol handlers
- State snapshot construction and delivery on connect
- Agent event streaming (subscribe/unsubscribe)
- UI state management (tabs, layout, theme) via `settings.json` read/write

## Invariants

- All RPC methods use the `namespace/method` convention (e.g., `tangle/getTree`, `ui/snapshot`).
- The `ui.snapshot` RPC returns the full UI state on connect — the frontend renders from this.
- UI state changes go through RPC -> backend updates `settings.json` -> pushes update. Never direct frontend mutation.
- Agent streaming uses subscribe/unsubscribe pattern — frontend subscribes to a session, backend pushes events.

## Interfaces

RPC method namespaces:

| Namespace | Methods | Purpose |
|---|---|---|
| `tangle/*` | `getTree`, `getNode`, `updateNode`, `createSiblingNode`, `indentNode`, `outdentNode`, `getNodeSourceRange`, `getNodeCodeRefs`, `setNodeCollapsed`, `getBacklinks` | Tangle CRUD |
| `ui/*` | `snapshot`, `openTab`, `closeTab`, `setActiveTab`, `updateLayout`, `setTheme`, `saveTab`, `nodeEdited` | UI state |
| `agent/*` | `subscribe`, `unsubscribe`, `send`, `cancel`, `listSessions` | Agent interaction |
| `prompts/*` | `list`, `get`, `update`, `reset` | Prompt management |
| `symbols/*` | `resolve`, `search` | Code symbol resolution |

## Key Components

- **App** (`taui/server/app.py`) — FastAPI app factory with lifespan management -> `taui/server/app.py:create_app`
- **Handlers** (`taui/server/handlers.py`) — RPC method dispatch (all namespaces) -> `taui/server/handlers.py:MethodHandlers`
- **Protocol** (`taui/server/protocol.py`) — JSON-RPC message parsing and serialization -> `taui/server/protocol.py`
- **State** (`taui/server/state.py`) — `RunState` and `RunProcess` for tracking active agent runs -> `taui/server/state.py:RunState`
- **Server** (`taui/server/server.py`) — Server startup and configuration -> `taui/server/server.py`

### Rename Status

The `spec -> tangle` rename is substantially complete in the server:

- All public RPC method names use `tangle/*` (not `spec/*`)
- `state.py` uses `tangle_ref` as primary field (with `spec_ref` alias)
- `handlers.py` internal methods still named `_handle_spec_*` (cosmetic inconsistency)
- Constructor still accepts both `tangles_path` and `specs_path` for backward compat
- Exception handling uses `SpecServiceError` / `SpecNotFoundError` (aliased from `Tangle*`)

## Code References

- `taui/server/__init__.py`
- `taui/server/app.py`
- `taui/server/handlers.py`
- `taui/server/protocol.py`
- `taui/server/state.py`
- `taui/server/server.py`
- `taui/server/__main__.py`

## Verification

- `tests/test_server_app.py` — RPC method integration tests
- `tests/test_server_protocol.py` — JSON-RPC protocol parsing tests
- `tests/test_server_startup.py` — Server lifecycle tests

```
pytest tests/test_server_app.py tests/test_server_protocol.py tests/test_server_startup.py -q
```

## Open Questions

- Should internal handler methods be renamed from `_handle_spec_*` to `_handle_tangle_*`?
- Should the backward-compat `specs_path` constructor param be removed?

## Related Features

- [Stateless UI](../features/stateless-ui.md)
- [Editable Prompts](../features/editable-prompts.md)

## Related Decisions

No decisions recorded yet.
