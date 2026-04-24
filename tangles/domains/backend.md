---
title: Backend
last_updated: 2026-04-11
---

# Backend

The Python backend — FastAPI server, WebSocket JSON-RPC, SQLite persistence, and all core business logic.

## Responsibility

Owns all persistent state, business logic, and agent orchestration. The backend is the single source of truth — the frontend is a stateless renderer that receives state from the backend.

- **App assembly** — FastAPI app factory `taui/server/app.py:create_app` wires together the WebSocket endpoint, RPC dispatch, and all middleware
  - Active WebSocket connections tracked by `taui/server/app.py:_ConnectionManager`, which broadcasts state updates
- **Tangle operations** — file indexing, parsing, and CRUD → [Tangle Module](tangle-module.md)
- **Agent orchestration** — session management and LLM coordination → [Agent System](agent-system.md)
- **RPC dispatch** — all methods routed through `taui/server/handlers.py:MethodHandlers` (lines 124–347)
- **UI state management** — tabs, layout, theme via `settings.json`, persisted by `taui/config/project_settings.py:ProjectSettingsStore`
  - Default system prompt in `taui/config/project_settings.py:default_prompt_content`
- **LSP integration** — code symbol resolution via `taui/lsp/manager.py:LSPManager`
- **Auth** — PKCE flow in `taui/auth/pkce.py`; credentials persisted by `taui/config/auth_config.py:save_provider_config`
  - Supported providers: Copilot, Gemini, Antigravity, Codex

## Invariants

- All persistent state lives in the backend — never in the frontend
- Two project-local stores:
  - `tangles/.taui.db` (SQLite) — tangle data
  - `.taui/settings.json` (JSON) — UI and project settings, loaded/saved by `taui/config/project_settings.py:ProjectSettingsStore`
- Global config (auth tokens) lives in `~/.taui/` only — read by `taui/config/auth_config.py:load_config`
- WebSocket JSON-RPC is the only communication channel with the frontend
  - Every message parsed by `taui/server/protocol.py:parse_request`
  - Responses built with `taui/server/protocol.py:result_message` or `taui/server/protocol.py:error_message`
- All file paths in the tangle system are relative to the project root
- Policy enforcement evaluated through `taui/config/policies.py:Policy`, returning a `taui/config/policies.py:ToolDecision`

## Interfaces

- **WebSocket JSON-RPC** at `/ws`
  - App assembled by `taui/server/app.py:create_app`
  - Connections managed by `taui/server/app.py:_ConnectionManager`
  - Wire format defined by `taui/server/protocol.py:JsonRpcRequest`
- **RPC namespaces** — `tangle.*`, `ui.*`, `agent.*`, `prompts.*`, `symbols.*` — all routed through `taui/server/handlers.py:MethodHandlers`
- **HTTP health endpoint** at `/health` — `taui/server/app.py:health_check`
- **Runtime state** — active agent/process state in `taui/server/state.py:RunProcess` and `taui/server/state.py:RunState`

## Key Components

- **Server** (`taui/server/`) — communication layer
  - App factory: `taui/server/app.py:create_app` (lines 45–195)
  - Connection registry: `taui/server/app.py:_ConnectionManager` (lines 19–43)
  - Full RPC handler surface: `taui/server/handlers.py:MethodHandlers` (lines 77–2003)
    - Dispatch router (lines 124–347) maps method strings to handler callables
    - `_handle_ui_snapshot` (lines 1366–1383) serialises full UI state for the frontend
    - `_handle_ui_open_tab` (lines 1385–1397) opens a new tab
    - `_handle_prompts_list` (lines 1456–1459), `_handle_prompts_update` (1468–1472)
    - `_handle_spec_get_tree` (lines 350–370), `_handle_spec_get_node` (372–400)
- **JSON-RPC Protocol** (`taui/server/protocol.py`) — wire format and parsing
  - `taui/server/protocol.py:JsonRpcRequest` (lines 21–29) — parsed request dataclass (`id`, `method`, `params`)
  - `taui/server/protocol.py:parse_request` (lines 48–74) — validates and deserialises raw JSON
  - `taui/server/protocol.py:result_message` (lines 77–82) — success response builder
  - `taui/server/protocol.py:error_message` (lines 85–99) — error response builder
- **Server State** (`taui/server/state.py`) — in-flight run tracking
  - `taui/server/state.py:RunProcess` (lines 12–36) — active agent run dataclass
  - `taui/server/state.py:RunState` (lines 39–54) — aggregate state of all active runs
- **Tangle Module** (`taui/tangle/`) → [Tangle Module](tangle-module.md)
- **Agent System** (`taui/agent/`) → [Agent System](agent-system.md)
- **LLM Providers** (`taui/llms/`) — Copilot, Gemini, Antigravity, Codex; all implement `taui/llms/base.py:BaseLLM`
- **LSP** (`taui/lsp/`) — `taui/lsp/manager.py:LSPManager` manages server lifecycle and symbol queries
- **Symbols** (`taui/symbols/`) — `taui/symbols/indexer.py:SymbolIndexer` builds and queries the in-process symbol index
- **Auth** (`taui/auth/`) — `taui/auth/pkce.py` PKCE flow; tokens via `taui/config/auth_config.py:save_provider_config` / `load_config`
- **Config** (`taui/config/`) — settings and policy
  - Global: `taui/config/settings.py:Settings` (lines 56–66) loaded by `taui/config/settings.py:load_settings` (lines 69–77)
  - Policy blocks: `taui/config/settings.py:PolicySettings` (lines 24–28), `taui/config/settings.py:BashPolicySettings` (lines 31–37)
  - Per-project: `taui/config/project_settings.py:ProjectSettingsStore` (lines 53–131); defaults at `default_settings` (39–50)
  - Policy evaluation: `taui/config/policies.py:Policy` (lines 17–48); `taui/config/policies.py:ToolDecision` (lines 11–14)
- **Commands** (`taui/commands/`) — built-in slash commands in `taui/commands/builtins.py`
- **Skills** (`taui/skills/`) — skill loading and registry via `taui/skills/registry.py`
- **Plugins** (`taui/plugins/`) — plugin models and registry via `taui/plugins/registry.py`

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
