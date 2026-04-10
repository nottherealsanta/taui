---
title: Backend
last_updated: 2026-04-10
---

# Backend

The Python backend — FastAPI server, WebSocket JSON-RPC, SQLite persistence, and all core business logic.

## Responsibility

Owns all persistent state, business logic, and agent orchestration. The backend is the single source of truth — the frontend is a stateless renderer that receives state from the backend.

Specifically:

- Tangle file indexing, parsing, and CRUD operations
- Agent session management and LLM orchestration
- WebSocket JSON-RPC server for frontend communication
- UI state management (tabs, layout, theme) via `settings.json`
- System prompt storage and retrieval
- LSP integration for code symbol resolution
- Authentication with LLM providers (Copilot, Gemini, Antigravity, Codex)

## Invariants

- All persistent state lives in the backend — never in the frontend.
- The backend reads/writes two project-local stores: `tangles/.taui.db` (SQLite) and `.taui/settings.json` (JSON).
- Global config (auth tokens) lives in `~/.taui/` only.
- WebSocket JSON-RPC is the only communication channel with the frontend.
- All file paths in the tangle system are relative to the project root.

## Interfaces

- WebSocket JSON-RPC endpoint at `/ws` -> `taui/server/app.py:app`
- RPC method namespaces: `tangle.*`, `ui.*`, `agent.*`, `prompts.*`, `symbols.*`
- HTTP health endpoint at `/health` -> `taui/server/app.py:health_check`

## Key Components

- **Server** (`taui/server/`) — FastAPI app, WebSocket handler, JSON-RPC dispatch -> `taui/server/app.py:create_app`
- **Tangle Module** (`taui/tangle/`) — Core tangle subsystem -> [Tangle Module](tangle-module.md)
- **Agent System** (`taui/agent/`) — Prime, root, sub agents -> [Agent System](agent-system.md)
- **LLM Providers** (`taui/llms/`) — Copilot, Gemini, Antigravity, Codex adapters -> `taui/llms/base.py:BaseLLM`
- **LSP** (`taui/lsp/`) — Language server protocol client for symbol resolution -> `taui/lsp/manager.py:LSPManager`
- **Symbols** (`taui/symbols/`) — Code symbol indexing and resolution -> `taui/symbols/indexer.py:SymbolIndexer`
- **Auth** (`taui/auth/`) — Provider authentication (PKCE, token management) -> `taui/auth/pkce.py`
- **Config** (`taui/config/`) — Settings, policies, auth config -> `taui/config/settings.py`
- **Commands** (`taui/commands/`) — Built-in slash commands -> `taui/commands/builtins.py`
- **Skills** (`taui/skills/`) — Skill loading and registry -> `taui/skills/registry.py`
- **Plugins** (`taui/plugins/`) — Plugin models and registry -> `taui/plugins/registry.py`

## Code References

- `taui/__init__.py`
- `taui/__main__.py`
- `taui/log_config.py`
- `taui/server/app.py`
- `taui/server/handlers.py`
- `taui/server/protocol.py`
- `taui/server/state.py`
- `taui/server/server.py`

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
