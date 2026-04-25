# Todo

## Done

- [x] Auth — Copilot device flow, Codex PKCE OAuth, credential persistence, auto-refresh
- [x] LLM Provider — BaseLLMProvider ABC, CopilotProvider, CodexProvider, unified StreamEvent/ProviderTurnResult types
- [x] Package setup — pyproject.toml, uv, hatchling, entry point

## Core Runtime

- [ ] Store — SQLite append-only event log (table DDL, event types, read/write interface)
- [ ] Streams — StreamClient with append_auto(), tail(), read(from_offset=) on top of Store
- [ ] Agent Loop — think→tool→observe cycle, turn counter, sub-agent spawning
- [ ] Context Manager — token budget, chunk tagging, compaction, skill budget estimation
- [ ] Tool Executor — policy gate (auto/confirm/deny), per-agent scoping, tool dispatch

## Tools

- [ ] File Ops — read, write, list, search
- [ ] Bash — sandboxed shell execution
- [ ] Questions — clarification/approval requests via Store
- [ ] Return to Parent — sub-agent completion handoff with required context
- [ ] Memory — cross-session knowledge persistence
- [ ] Git — branch, commit, diff, PR
- [ ] Skills — discover, load, invoke skill packages
- [ ] MCP — external server connections, scoped resources + tools

## Frontends

- [ ] CLI — prompt-toolkit REPL (default `taui` entry point)
- [ ] TUI — Textual terminal UI (opt-in `--tui`)
- [ ] Web Server — FastAPI + WebSocket + Svelte (opt-in `--web`)

## Shared Services

- [ ] Config — global/project settings, tool policies, project overrides (beyond provider creds)
- [ ] Commands — slash command registry (/compact, /cost, /help, /memory)
- [ ] LSP Manager — per-language server lifecycle, go-to-def, references, hover
- [ ] Symbols — workspace code index, cross-ref queries

## Specs to Write

- [ ] Store schema — table DDL, event types enum, stream_id + offset keying
- [ ] Config schema — what config.toml looks like beyond [providers.*], tool policy format
- [ ] Sub-agent contract — how parent configures child budget, completion contract details
- [ ] Compaction strategy — algorithm for what gets summarized vs dropped vs kept
- [ ] Extension system — /i self-edit mode format, lifecycle, isolation mechanism
- [ ] Module layout — where each component lives on disk, import conventions
