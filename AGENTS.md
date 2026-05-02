# AGENTS.md

## Project

Taui is a customizable agentic coding interface (v0.2.0, Python 3.13+). Users control the agent, tools, prompts, and storage. The interface is a full-screen Textual TUI.

## Interface

**TUI** — Textual-based terminal UI. Default and only interface. Entry point: `taui/main.py -> main()`.

Launch: `taui` (or `taui -p copilot -m claude-sonnet-4-20250514`)

## Architecture

Everything flows through a SQLite append-only event store (`taui/store/`) — no shared mutable state.

```
TUI  (taui/tui/)
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
| `taui/main.py` | Entry point — arg parsing, launches TUI |
| `taui/tui/` | Textual TUI package |
| `taui/tui/app.py` | Main `TauiApp(App)` — wires session, callbacks, streaming, steering/queue |
| `taui/tui/messages.py` | Custom Textual messages (ToolStarted, ToolEnded, StreamTextDelta) |
| `taui/tui/widgets/` | All TUI widgets |
| `taui/tui/screens/` | Modal screens (context breakdown, diff view) |
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

## TUI Architecture

### Widget Hierarchy

```
TauiApp (App)
├── Header
├── Horizontal (#main-layout)
│   ├── Sidebar (Ctrl+B toggle, DirectoryTree)
│   └── Vertical (#chat-area)
│       ├── VerticalScroll (#chat-log)
│       │   ├── Static (.user-message)
│       │   ├── AgentResponse (MarkdownStream)
│       │   ├── Vertical (.tool-section)
│       │   │   └── ToolStatusWidget (animated braille spinner)
│       │   ├── ApprovalPrompt / QuestionPrompt
│       │   └── Static (steer/queue indicators)
│       └── SpinnerWidget (global thinking indicator)
├── StatusBar (ModelStatus + ContextStatus)
├── ChatInput (TextArea with steer/queue/history)
└── CustomFooter (dynamic key legend)
```

### Key Bindings

| Key | Idle | Agent Busy |
|-----|------|------------|
| Enter | Send message | Steer (inject between tool calls) |
| Shift+Enter / Ctrl+J | Insert newline | Insert newline |
| Alt+Enter | Insert newline | Queue (follow-up after turn) |
| Ctrl+Q | Quit | Quit |
| Ctrl+N | New session | New session |
| Ctrl+B | Toggle sidebar | Toggle sidebar |
| Ctrl+X | Context breakdown | Context breakdown |
| Ctrl+C | — | Cancel + clear queues |

### Steering & Queue

- **Steer** (Enter while busy): Calls `AgentLoop.steer(text)`, injected between tool calls via `_drain_steering()`
- **Queue** (Alt+Enter while busy): Appended to `_queued` list, drained sequentially after turn completes
- Visual indicators: `s> text` (dim) for steer, `q> text` (orange) for queue

### Streaming

Uses Textual's built-in `MarkdownStream` for real-time token rendering. `AgentResponse` widget wraps `Markdown.get_stream()` + `stream.write(fragment)`.

### Tool Status

FIFO queue pattern from archive: `_tool_counter` generates unique keys, `_pending_tool_keys[name]` is a per-tool-name FIFO. On tool end, pop oldest key to match start→end.

### Approval & Questions

- `ApprovalPrompt`: Inline Allow/Deny buttons, returns via `asyncio.Future`
- `QuestionPrompt`: Inline `OptionList`, returns selected option via `asyncio.Future`

### Screens

- `ContextBreakdownScreen`: Modal showing per-role token breakdown with colored bars
- `DiffViewScreen`: Modal with unified diff, color-coded adds/deletes/hunks

## Key Patterns

### Registry pattern
Tools, commands, extensions, skills, and LLM providers use registries with `register()`, `get()`, `unregister()`.

### Policy gates
`ToolExecutor` checks `ToolPolicy` (auto/confirm/deny) before running any tool. Policies cascade: per-agent → per-project → global → tool default.

### Event streaming
All state changes are events appended to SQLite streams. No separate event bus.

### Sub-agents
Child loops with restricted tool sets, own context budgets, own streams.

### Context compaction
Triggered at 80% token budget. Preserves system prompt, latest user message, unresolved tool calls; drops oldest non-essential messages.

## Async

All I/O is async/await. SQLite uses `aiosqlite`. Streams use `async for` generators. LLM providers use streaming SSE with retry + exponential backoff.

## Testing

```bash
uv run python -m pytest tests/ -q
```

- pytest with `asyncio_mode = "auto"`
- Mock providers (`MockLLMProvider`) instead of real HTTP
- Test tools (`EchoTool`, `FailTool`) for isolated tool testing
- TUI tests: 45 unit tests for widgets, messages, FIFO tracking, history, @file expansion

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

## Configuration

- Global: `~/.config/taui/config.toml`
- Project: `.taui/config.toml`
- Instructions: `.taui/instructions.md`, `AGENTS.md`
- Skills: `.agents/skills/<name>/SKILL.md` or `.taui/skills/<name>/SKILL.md`
- Extensions: `.taui/extensions/<name>.py`
- Store: `.taui/store.db`
- History: `~/.cache/taui/prompt_history`
