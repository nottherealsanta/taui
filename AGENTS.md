# AGENTS.md

## Project

Taui is a customizable agentic coding interface (v0.2.0, Python 3.13+). Users control the agent, tools, prompts, and storage rather than adapting to a fixed assistant.

## Interfaces

- **CLI** — Full support. Interactive prompt-toolkit REPL. Default when running `taui`. Entry point: `taui/cli.py → main()`.
- **TUI** — In development (future). Textual-based terminal UI with panes and scrollable history. Start with `taui --tui`. Requires `uv pip install taui[tui]`.
- **Web** — In development (future). FastAPI + WebSocket + JSON-RPC 2.0. Start with `taui --web`. Requires `uv pip install taui[web]`.

## Architecture

Everything flows through a SQLite append-only event store (`taui/store/`) — no shared mutable state. Frontends tail event streams via `StreamClient.tail()`.

```
CLI / TUI / Web
      ↓
   Session  (taui/session.py — assembles provider, tools, executor, loop, store)
      ↓
   AgentLoop  (taui/agent/loop.py — think → tool → observe cycle)
      ↓
   ToolExecutor  (taui/tools/executor.py — policy-gated dispatch)
      ↓
   Store  (taui/store/ — SQLite event log, WAL mode)
```

## Source Layout

| Path | Purpose |
|------|---------|
| `taui/cli.py` | CLI REPL (prompt-toolkit), command parsing, color output |
| `taui/session.py` | Session factory — wires provider, registry, executor, loop, store |
| `taui/config.py` | Config dataclass (provider, model, system_prompt, max_turns, tool policies) |
| `taui/agent/` | Agent loop (`loop.py`), context compaction (`context.py`) |
| `taui/tools/` | Tool protocol (`base.py`), registry (`registry.py`), executor (`executor.py`), built-ins (`builtins/`) |
| `taui/store/` | SQLite event store (`store.py`), event types (`events.py`), stream client (`stream.py`) |
| `taui/llm_provider/` | Abstract provider, streaming, retry, token counting; `providers/copilot`, `providers/codex` |
| `taui/commands/` | Slash command registry and built-ins (`/help`, `/cost`, `/compact`, `/clear`) |
| `taui/skills/` | Skill discovery — loads `.md` skill files from known paths |
| `taui/extensions/` | Extension discovery — loads `.py` files with `register(tools, commands, hooks)` |
| `taui/lsp/` | LSP client lifecycle, transport, types |
| `taui/symbols/` | Symbol extraction (functions, classes, imports) from source files |
| `taui/mcp/` | MCP server discovery, connection, tool export |
| `taui/hooks.py` | Extensibility callbacks (prompt, banner, status, on_tool_call, etc.) |
| `taui/prompt_builder.py` | System prompt template rendering with variable substitution |
| `taui/cost.py` | Per-turn token accounting and pricing |
| `taui/tui.py` | Textual TUI (in development) |
| `taui/server/` | FastAPI web server (in development) |

## Key Patterns

### Registry pattern
Tools, commands, extensions, skills, and LLM providers use registries with `register()`, `get()`, `unregister()`.

### Policy gates
`ToolExecutor` checks `ToolPolicy` (auto/confirm/deny) before running any tool. Policies cascade: per-agent → per-project → global → tool default.

### Event streaming
All state changes are events appended to SQLite streams. No separate event bus.

### Sub-agents
Child loops with restricted tool sets, own context budgets, own streams. Completion requires explicit return-to-parent with context payload.

### Context compaction
Triggered at 80% token budget. Preserves system prompt, latest user message, unresolved tool calls; drops oldest non-essential messages.

## Async

All I/O is async/await. SQLite uses `aiosqlite`. Streams use `async for` generators. LLM providers use streaming SSE with retry + exponential backoff.

## Testing

```bash
python -m pytest tests/ -q
```

- pytest with `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed
- Mock providers (`MockLLMProvider`) instead of real HTTP
- Test tools (`EchoTool`, `FailTool`) for isolated tool testing
- Fixtures for Store, StreamClient, ToolRegistry, Session

## Build & Tooling

| Tool | Purpose |
|------|---------|
| `uv` | Package installer and project manager |
| `hatchling` | Build backend |
| `ruff` | Linter — rules: E, F, I, UP; 100-char line limit; target py313 |
| `pytest` | Test runner |

## Conventions

- Dataclasses with `slots=True`
- Type hints on all public APIs
- Private members use `_leading_underscore`
- Tool errors return `ToolResult.fail(msg)` — never raise
- Extension failures log warnings, never crash the agent
- 100-character line limit (ruff enforced)

## LLM Providers

- **copilot** (default): GitHub Copilot API, Chat Completions format
- **codex**: OpenAI Codex/GPT, Responses API format

Both support streaming, OAuth/PKCE auth refresh, reasoning formats, and tool schema conversion.

## Configuration

- Global: `~/.config/taui/config.toml`
- Project: `.taui/config.toml`
- Instructions: `.taui/instructions.md`, `AGENTS.md`
- Skills: `.agents/skills/<name>/SKILL.md` or `.taui/skills/<name>/SKILL.md`
- Extensions: `.taui/extensions/<name>.py`
- Store: `.taui/store.db`
