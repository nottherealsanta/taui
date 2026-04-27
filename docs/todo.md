# Todo

## Done

- [x] Auth — Copilot device flow, Codex PKCE OAuth, credential persistence, auto-refresh
- [x] LLM Provider — BaseLLMProvider ABC, CopilotProvider, CodexProvider, unified StreamEvent/ProviderTurnResult types
- [x] Package setup — pyproject.toml, uv, hatchling, entry point
- [x] Store — SQLite append-only event log (WAL, event types, idempotent append, live-tail)
- [x] Streams — StreamClient with ensure_stream(), append(), tail(), read(from_offset=)
- [x] Agent Loop — think→tool→observe cycle, turn counter, callbacks, event emission
- [x] Context Manager — token budget (180K), compaction (soft/hard ratio), message preservation
- [x] Tool Executor — policy gate (auto/confirm/deny), timeout, error handling
- [x] File Ops — ReadTool (paging, dir listing), WriteTool (atomic), GlobTool, GrepTool
- [x] Bash — sandboxed shell (filtered env, process group isolation, SIGTERM→SIGKILL)
- [x] Questions — QuestionTool with async callback, options support
- [x] Memory — MemoryTool (save/read/list/delete in .taui/memory/*.md)
- [x] Git — GitTool with 13 operations (8 read, 5 write)
- [x] Edit — EditTool with fuzzy matching chain, per-file locking, atomic writes
- [x] CLI — asyncio REPL with colored output, multi-line input, tool display callbacks
- [x] Config — Config dataclass, layered loading (defaults → config.toml → CLI overrides)
- [x] Commands — slash command registry (/help, /cost, /compact, /clear, /model) with aliases
- [x] System Prompt — template-based with {variables}, adaptive guidelines, instruction discovery
- [x] Cost Tracking — per-turn token accounting, pricing table, session summary
- [x] Architecture Docs — full docs for tools, agent loop, store, session, CLI, prompt builder

## Next Up

- [x] Sub-agents — SubAgentTool spawns child AgentLoop with scoped tool subsets and turn budgets
- [x] Skills — SkillRegistry discovers SKILL.md packages from .taui/skills/ and .agents/skills/ (Agent Skills standard), SkillsTool (list/load/unload/status) injects into conversation
- [x] MCP — McpClient (stdio JSON-RPC), McpManager (multi-server, TOML config), McpTool (servers/connect/disconnect/tools/call)
- [x] Extension system — ExtensionRegistry (.taui/extensions/ + global), convention-based loader, /extensions command, isolation

## Frontends

- [x] TUI — Textual terminal UI (opt-in `--tui`), split-pane layout, message/tool logs, keybindings
- [x] Web Server — FastAPI + WebSocket JSON-RPC server (opt-in `--web`), protocol layer, session-backed dispatch

## Shared Services

- [x] LSP Manager — LspClient (stdio JSON-RPC), LspManager (per-language lifecycle), go-to-def, references, hover, document/workspace symbols, diagnostics, call hierarchy
- [x] Symbols — SymbolIndexer (AST-based, Python), SymbolEntry model, project scanning with skip dirs and size limits

## Specs to Write

- [x] Sub-agent contract — docs/architecture_docs/sub-agents.md
- [x] Extension system spec — docs/architecture_docs/extensions.md (+ self-edit.md updated)
- [x] LSP Manager — docs/architecture_docs/lsp.md
- [x] Symbols — docs/architecture_docs/symbols.md
- [x] Web Server — docs/architecture_docs/web-server.md
- [x] TUI — docs/architecture_docs/tui.md
