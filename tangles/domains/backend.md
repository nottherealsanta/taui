---
title: Backend
last_updated: 2026-04-10
---

# Backend

The Python backend — FastAPI server, WebSocket JSON-RPC, SQLite persistence, and all core business logic.

## Responsibility

Owns all persistent state, business logic, and agent orchestration. The backend is the single source of truth — the frontend is a stateless renderer that receives state from the backend.

The FastAPI application is assembled by `taui/server/app.py:create_app`, which wires together the WebSocket endpoint, the RPC dispatch layer in `taui/server/handlers.py:MethodHandlers`, and all middleware. Active WebSocket connections are tracked by `taui/server/app.py:_ConnectionManager`, which holds the registry of open sockets and is responsible for broadcasting state updates.

Specifically:

- Tangle file indexing, parsing, and CRUD operations
- Agent session management and LLM orchestration
- WebSocket JSON-RPC server for frontend communication — dispatched through `taui/server/handlers.py:MethodHandlers` (124–347 for the dispatch router)
- UI state management (tabs, layout, theme) via `settings.json`, persisted and merged by `taui/config/project_settings.py:ProjectSettingsStore`
- System prompt storage and retrieval — see `taui/config/project_settings.py:default_prompt_content` for defaults
- LSP integration for code symbol resolution via `taui/lsp/manager.py:LSPManager`
- Authentication with LLM providers (Copilot, Gemini, Antigravity, Codex) — PKCE flow in `taui/auth/pkce.py`, credentials persisted by `taui/config/auth_config.py:save_provider_config`

## Invariants

- All persistent state lives in the backend — never in the frontend.
- The backend reads/writes two project-local stores: `tangles/.taui.db` (SQLite) and `.taui/settings.json` (JSON). Settings are loaded/saved through `taui/config/project_settings.py:ProjectSettingsStore`.
- Global config (auth tokens) lives in `~/.taui/` only — read by `taui/config/auth_config.py:load_config`.
- WebSocket JSON-RPC is the only communication channel with the frontend. Every message is parsed by `taui/server/protocol.py:parse_request` and responses are built with `taui/server/protocol.py:result_message` or `taui/server/protocol.py:error_message`.
- All file paths in the tangle system are relative to the project root.
- Policy enforcement for tool use is evaluated through `taui/config/policies.py:Policy`, which returns a `taui/config/policies.py:ToolDecision`.

## Interfaces

- WebSocket JSON-RPC endpoint at `/ws` → `taui/server/app.py:create_app` (assembles the app) / `taui/server/app.py:_ConnectionManager` (manages connections)
- RPC method namespaces: `tangle.*`, `ui.*`, `agent.*`, `prompts.*`, `symbols.*` — all routed through `taui/server/handlers.py:MethodHandlers`
- HTTP health endpoint at `/health` → `taui/server/app.py:health_check`
- Incoming RPC wire format defined by `taui/server/protocol.py:JsonRpcRequest`
- Runtime agent/process state tracked in `taui/server/state.py:RunProcess` and `taui/server/state.py:RunState`

## Key Components

- **Server** (`taui/server/`) — FastAPI app factory `taui/server/app.py:create_app`, connection tracking `taui/server/app.py:_ConnectionManager`, full RPC handler surface `taui/server/handlers.py:MethodHandlers`
- **JSON-RPC Protocol** (`taui/server/protocol.py`) — wire format dataclass `taui/server/protocol.py:JsonRpcRequest`, parsing `taui/server/protocol.py:parse_request`, response helpers `taui/server/protocol.py:result_message` / `taui/server/protocol.py:error_message`
- **Server State** (`taui/server/state.py`) — in-flight process record `taui/server/state.py:RunProcess`, aggregate run state `taui/server/state.py:RunState`
- **Tangle Module** (`taui/tangle/`) — Core tangle subsystem → [Tangle Module](tangle-module.md)
- **Agent System** (`taui/agent/`) — Prime, root, sub agents → [Agent System](agent-system.md)
- **LLM Providers** (`taui/llms/`) — Copilot, Gemini, Antigravity, Codex adapters; all implement `taui/llms/base.py:BaseLLM`
- **LSP** (`taui/lsp/`) — Language server protocol client for symbol resolution via `taui/lsp/manager.py:LSPManager`
- **Symbols** (`taui/symbols/`) — Code symbol indexing and resolution via `taui/symbols/indexer.py:SymbolIndexer`
- **Auth** (`taui/auth/`) — Provider authentication (PKCE flow in `taui/auth/pkce.py`); token persistence via `taui/config/auth_config.py:save_provider_config` / `taui/config/auth_config.py:load_config`
- **Config** (`taui/config/`) — Global settings `taui/config/settings.py:Settings` loaded by `taui/config/settings.py:load_settings`; per-project store `taui/config/project_settings.py:ProjectSettingsStore`; policy evaluation `taui/config/policies.py:Policy`
- **Commands** (`taui/commands/`) — Built-in slash commands in `taui/commands/builtins.py`
- **Skills** (`taui/skills/`) — Skill loading and registry via `taui/skills/registry.py`
- **Plugins** (`taui/plugins/`) — Plugin models and registry via `taui/plugins/registry.py`

## Code References

### Server

- `taui/server/app.py:create_app` (45–195) — FastAPI app factory; registers all routes and middleware
- `taui/server/app.py:_ConnectionManager` (19–43) — WebSocket connection registry; tracks open sockets and broadcasts state
- `taui/server/app.py:health_check` — HTTP `/health` route handler
- `taui/server/handlers.py:MethodHandlers` (77–2003) — all RPC method implementations
- `taui/server/handlers.py:MethodHandlers` dispatch router (124–347) — maps incoming method strings to handler functions
- `taui/server/handlers.py:_handle_ui_snapshot` (1366–1383) — serialises full UI state for the frontend
- `taui/server/handlers.py:_handle_ui_open_tab` (1385–1397) — opens a new tab in the UI
- `taui/server/handlers.py:_handle_prompts_list` (1456–1459) — returns available system prompts
- `taui/server/handlers.py:_handle_prompts_update` (1468–1472) — persists an edited system prompt
- `taui/server/handlers.py:_handle_spec_get_tree` (350–370) — returns the full tangle file tree
- `taui/server/handlers.py:_handle_spec_get_node` (372–400) — returns a single tangle node by path
- `taui/server/protocol.py:JsonRpcRequest` (21–29) — wire format dataclass for incoming RPC messages
- `taui/server/protocol.py:parse_request` (48–74) — validates and deserialises a raw JSON-RPC request
- `taui/server/protocol.py:result_message` (77–82) — builds a successful JSON-RPC response envelope
- `taui/server/protocol.py:error_message` (85–99) — builds an error JSON-RPC response envelope
- `taui/server/state.py:RunProcess` (12–36) — dataclass for a single in-flight agent process
- `taui/server/state.py:RunState` (39–54) — aggregate state of all active runs

### Config

- `taui/config/settings.py:Settings` (56–66) — top-level settings dataclass
- `taui/config/settings.py:load_settings` (69–77) — reads and merges settings from disk
- `taui/config/settings.py:PolicySettings` (24–28) — policy configuration block
- `taui/config/settings.py:BashPolicySettings` (31–37) — bash-specific policy overrides
- `taui/config/project_settings.py:ProjectSettingsStore` (53–131) — load/save/merge per-project settings
- `taui/config/project_settings.py:default_prompt_content` (13–36) — default system prompt template
- `taui/config/project_settings.py:default_settings` (39–50) — factory defaults for a new project
- `taui/config/policies.py:Policy` (17–48) — evaluates tool-use decisions against configured rules
- `taui/config/policies.py:ToolDecision` (11–14) — enum: `allow`, `deny`, `ask`
- `taui/config/auth_config.py:load_config` (15–22) — reads provider credentials from `~/.taui/`
- `taui/config/auth_config.py:save_provider_config` (25–32) — persists updated provider credentials

### Other modules

- `taui/__init__.py`
- `taui/__main__.py`
- `taui/log_config.py`
- `taui/server/server.py`
- `taui/llms/base.py:BaseLLM` — abstract base class all LLM provider adapters implement
- `taui/lsp/manager.py:LSPManager` — manages LSP server lifecycle and symbol queries
- `taui/symbols/indexer.py:SymbolIndexer` — builds and queries the in-process symbol index
- `taui/auth/pkce.py` — PKCE OAuth2 flow used for Copilot and similar providers
- `taui/commands/builtins.py` — built-in slash command definitions
- `taui/skills/registry.py` — discovers and loads skill definitions
- `taui/plugins/registry.py` — discovers and loads plugin definitions

## Verification

- `tests/test_server_app.py` — server RPC method integration tests
- `tests/test_server_startup.py` — server lifecycle tests
- `tests/test_server_protocol.py` — JSON-RPC protocol tests

```
pytest tests/test_server_app.py tests/test_server_startup.py tests/test_server_protocol.py -q
```

## Related Features

- [Stateless UI](../features/stateless-ui.md)
- [Editable Prompts](../features/editable-prompts.md)

## Related Decisions

- [Minimal Frontmatter](../decisions/0001-minimal-frontmatter.md)
