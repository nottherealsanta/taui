# DESIGN.md — Taui Architecture & Design

Taui is a customizable agentic coding interface built as a full-screen terminal application. Users control the agent, tools, prompts, and storage. This document describes the system architecture, design patterns, data flow, and the rationale behind key decisions.

## Table of Contents

- [System Overview](#system-overview)
- [Architecture Layers](#architecture-layers)
- [TUI Layer](#tui-layer)
- [Agent Layer](#agent-layer)
- [Tool Layer](#tool-layer)
- [Store Layer](#store-layer)
- [LLM Provider Layer](#llm-provider-layer)
- [Extensibility](#extensibility)
- [Data Flow](#data-flow)
- [Key Design Decisions](#key-design-decisions)
- [Textual Patterns](#textual-patterns)

---

## System Overview

Taui is a **layered, event-driven** system. Every state change flows through an append-only SQLite event store. There is no shared mutable state between layers — the store _is_ the source of truth.

```
┌──────────────────────────────────────────────────────┐
│                   TUI (Textual)                      │
│         Widgets, Messages, CSS, Key Bindings         │
├──────────────────────────────────────────────────────┤
│                     Session                          │
│       Factory: wires provider, tools, loop, store    │
├──────────────────────────────────────────────────────┤
│                   Agent Loop                         │
│          think → tool → observe cycle                │
├──────────────────────────────────────────────────────┤
│                  Tool Executor                       │
│           Policy-gated tool dispatch                 │
├──────────────────────────────────────────────────────┤
│                    Store                             │
│        SQLite append-only event log (WAL mode)       │
└──────────────────────────────────────────────────────┘
```

**Python 3.13+**. All I/O is `async`/`await`. SQLite uses `aiosqlite`. LLM providers use streaming SSE with retry and exponential backoff.

---

## Architecture Layers

### Session — The Wiring Point

`Session` is the factory that assembles all dependencies into a running agent session. It creates the LLM provider, tool registry, executor, agent loop, and store, then wires them together via callbacks.

```python
Session.create(config)
  ├─ LLM provider (authenticated)
  ├─ ToolRegistry + built-in tools
  ├─ SystemPromptBuilder (project context, tool guidelines)
  ├─ Store + StreamClient
  ├─ ToolExecutor (policy gates)
  ├─ AgentLoop (system prompt, callbacks)
  ├─ HookRegistry (extensions)
  ├─ CostTracker (per-turn accounting)
  └─ MCP servers (if configured)
```

Key `Session` responsibilities:
- **`send(message)`** — preprocess via hooks, run agent loop, postprocess result
- **`new_session()`** — fresh agent loop, same store
- **`toggle_extensions_mode()`** — sandbox file writes to `.taui/` only
- **`resume_session(id)`** — replay messages from the event store
- **`reload_extensions()`** — hot-reload without restart

---

## TUI Layer

The interface is a Textual TUI — a full-screen terminal application with a CSS-driven layout, custom widgets, reactive state, and asynchronous message handling. Textual runs each widget in its own asyncio task and uses a DOM model similar to the web.

### Widget Hierarchy

```
TauiApp (App[None])
└── Horizontal (#main-layout)
    ├── Sidebar (Ctrl+B toggle)
    │   ├── Static (.sidebar-header)
    │   └── DirectoryTree
    └── Vertical (#chat-area)
        ├── VerticalScroll (#chat-log)
        │   ├── Static (.user-message)           ← user input echo
        │   ├── AgentResponse (Markdown)          ← streamed LLM response
        │   ├── Vertical (.tool-section)          ← tool status group
        │   │   └── ToolStatusWidget              ← animated spinner per tool
        │   ├── ApprovalPrompt                    ← Allow/Deny buttons
        │   ├── QuestionsPanel                    ← multi-question flow
        │   └── Static (.steer-indicator|.queue-indicator)
        ├── CompletionDropdown (layer: overlay)   ← slash command completion
        ├── ChatInput (TextArea)                  ← multiline input
        └── InfoBar                               ← model, tokens, cost, spinner
```

### Custom Messages

Textual's event system drives all TUI state changes. Custom messages decouple the agent loop from the interface:

| Message | Direction | Purpose |
|---------|-----------|---------|
| `ToolStarted` | Agent → TUI | Mount a `ToolStatusWidget` with spinner |
| `ToolEnded` | Agent → TUI | Update widget to success/failure state |
| `StreamTextDelta` | Agent → TUI | Append text fragment to `AgentResponse` |
| `StreamReasoningDelta` | Agent → TUI | Accumulate reasoning text (dim) |
| `AgentBusy` | Agent → TUI | Switch key legend, enable steer/queue |
| `AgentIdle` | Agent → TUI | Restore key legend, drain queued messages |
| `ChatInput.Submitted` | TUI → App | User submitted input (with queue flag) |
| `QuestionsPanel.Confirmed` | TUI → App | User completed multi-question flow |

### Streaming Architecture

LLM responses stream token-by-token into the TUI:

```
LLM Provider (SSE stream)
  ↓ on_text_delta callback
AgentLoop
  ↓ post_message(StreamTextDelta)
TauiApp.handle_stream_text()
  ↓ creates AgentResponse (Markdown subclass) on first delta
AgentResponse.append_text(fragment)
  ↓ accumulates in _buffer, calls update(_buffer)
Textual re-renders Markdown incrementally
```

`AgentResponse` extends Textual's `Markdown` widget. It accumulates the full response in a `_buffer` string and calls `update()` on each delta. When the turn ends, `finalize()` marks the response complete. If no streaming occurred (edge case), the final text is rendered as a static `Markdown` widget.

### Key Bindings — Context-Sensitive

The same keys behave differently depending on agent state:

| Key | Agent Idle | Agent Busy |
|-----|-----------|------------|
| Enter | Send message | **Steer** — inject text between tool calls |
| Shift+Enter / Ctrl+J | Insert newline | Insert newline |
| Alt+Enter | Insert newline | **Queue** — schedule follow-up after turn |
| Ctrl+C | — | Cancel agent + clear queues |
| Ctrl+Q | Quit | Quit |
| Ctrl+N | New session | New session |
| Ctrl+B | Toggle sidebar | Toggle sidebar |
| Ctrl+X | Context breakdown | Context breakdown |

The `CustomFooter` widget dynamically renders the correct key legend based on the `_busy` flag.

### Steering & Queue

Two mechanisms let users interact _during_ an agent turn:

**Steering** injects a user message between tool calls. The agent sees it before making its next LLM call. Displayed as `s> text` in dim.

**Queue** schedules messages for after the current turn completes. They execute sequentially. Displayed as `q> text` in orange.

```
User presses Enter while busy:
  → AgentLoop.steer(text)
  → _drain_steering() converts to Message(role="user") between tool calls
  → Agent sees the steer on its next think step

User presses Alt+Enter while busy:
  → _queued.append(text)
  → After turn completes, pop and send sequentially
```

### Tool Status — FIFO Tracking

Tools can run concurrently and the same tool name may appear multiple times. A FIFO pattern tracks which `ToolStarted` matches which `ToolEnded`:

```python
_tool_counter: int                         # sequential ID
_pending_tool_keys: dict[str, list[str]]   # per-name FIFO
_active_tool_widgets: dict[str, ToolStatusWidget]

# On ToolStarted: push key, mount widget
# On ToolEnded:   pop oldest key for that name, update widget
```

Each `ToolStatusWidget` shows an animated braille spinner while running (`⣾ ⣽ ⣻ ⢿ ⡿ ⣟ ⣯ ⣷`), then switches to a success/failure icon with a 150-char output preview.

### Approval & Question Prompts

Both use `asyncio.Future` to block the agent loop until the user responds:

**ApprovalPrompt**: Inline Allow/Deny buttons. Returns `bool`. Used when a tool's policy is `confirm`.

**QuestionsPanel**: Multi-question wizard with pagination. Shows one question per page with `OptionList` choices or freeform `Input`. Final page shows a review of all answers before confirming. Returns `list[str | None]`.

### Modal Screens

**ContextBreakdownScreen** (Ctrl+X): Categorizes messages by role (system/user/assistant/tool), estimates tokens (~4 chars/token), and renders colored progress bars. Green < 15%, yellow < 30%, red ≥ 30%.

**DiffViewScreen**: Unified diff with color-coded lines. Green for additions, red for deletions, cyan for hunk headers.

### CSS Architecture

Taui uses Textual CSS defined as inline `CSS` class variables (no external `.tcss` files). This bundles code and style together for distribution simplicity.

Key styling patterns:
- `$surface-darken-1` background for the screen
- Hidden scrollbars (`scrollbar-size: 0 0`) in the chat log
- `.visible` class toggle for Sidebar and CompletionDropdown
- `layer: overlay` for the CompletionDropdown to float above content
- Semantic CSS classes: `.user-message`, `.tool-section`, `.steer-indicator`, `.queue-indicator`, `.reasoning-text`

### ChatInput — History & Completion

`ChatInput` extends Textual's `TextArea`:

- **History**: Up/Down arrows navigate prompt history. History persisted to `~/.cache/taui/prompt_history` with newlines escaped.
- **Tab completion**: Triggers slash command dropdown. `CompletionDropdown` floats on the overlay layer.
- **@file expansion**: `@path` syntax reads a file and injects it as a markdown code block into the message.
- **Multiline**: Shift+Enter / Ctrl+J inserts newlines. Auto-sizing from 3 to 8 lines.

---

## Agent Layer

### The Think → Tool → Observe Cycle

The agent loop is the core runtime. It alternates between LLM inference and tool execution:

```
AgentLoop.run(user_message)
  ├─ Append system prompt + user message
  └─ for turn in range(max_turns):
       ├─ THINK: call LLM (streaming, with tools schema)
       ├─ OBSERVE: record assistant message + emit event
       ├─ ACT: for each tool_call in response:
       │    ├─ Check policy → auto | confirm | deny
       │    ├─ If confirm: await user approval
       │    ├─ Execute tool with timeout (120s default)
       │    ├─ Record tool result + emit event
       │    └─ Drain steering queue
       └─ If no tool calls: return final text
```

The loop terminates when:
1. The LLM produces a text response with no tool calls (natural completion)
2. `max_turns` is reached (safety limit, default 50)
3. The user cancels (Ctrl+C)

### Context Compaction

When the message history approaches the LLM's token budget, old messages are dropped to free space:

```
Trigger: estimated tokens > 80% of max_input_tokens

Preservation rules (never dropped):
  1. Latest system message
  2. Latest user message
  3. Unresolved tool calls + their partial results

Algorithm:
  Phase 1 (soft): drop oldest droppable messages until < 80%
  Phase 2 (aggressive): if still > 90%, drop more aggressively
  Insert compaction marker so the agent knows context was trimmed
```

Token estimation uses ~4 characters per token as a fast approximation.

### Sub-Agents

Child agent loops with restricted tool sets, their own context budgets, and their own event streams. Used via the `SubAgentTool` for delegation.

---

## Tool Layer

### Tool Protocol

All tools implement a simple protocol:

```python
class Tool(Protocol):
    name: str
    description: str
    schema: dict[str, Any]    # OpenAI function-calling JSON schema
    category: ToolCategory    # FILE_READ | FILE_WRITE | SHELL | GIT | AGENT | MEMORY | QUESTION

    async def execute(self, arguments: dict) -> ToolResult
```

`ToolResult` is a dataclass with `content: str`, `error: bool`, and `metadata: dict`. Tools never raise — they return `ToolResult.fail(msg)` on error.

### Built-In Tools

| Tool | Category | Purpose |
|------|----------|---------|
| `read` | FILE_READ | Read file contents |
| `write` | FILE_WRITE | Create new files |
| `edit` | FILE_WRITE | Targeted edits with search/replace |
| `glob` | FILE_READ | Find files by pattern |
| `grep` | FILE_READ | Search file contents |
| `bash` | SHELL | Execute shell commands |
| `git` | GIT | Git operations |
| `question` | QUESTION | Ask the user a question |
| `memory` | MEMORY | Persistent agent memory |
| `skills` | AGENT | Load and inject skill files |
| `sub_agent` | AGENT | Spawn child agent loops |
| `mcp` | AGENT | Call MCP server tools |

### Policy Gates

The `ToolExecutor` applies a three-tier policy before running any tool:

```
PolicyDecision.AUTO     → execute immediately
PolicyDecision.CONFIRM  → prompt user, wait for approval
PolicyDecision.DENY     → block with error message
```

Policies cascade: **per-agent → per-project → global → tool default**. Read tools default to `auto`. Write and shell tools default to `confirm`.

### Execution Outcomes

```python
Outcome = Completed | NeedsApproval | Denied

Completed(result)     # Success or graceful failure
NeedsApproval(...)    # Waiting for user
Denied(result)        # Policy blocked it
```

---

## Store Layer

### SQLite Event Store

All state changes are immutable events appended to streams in a SQLite database (WAL mode for crash safety):

```sql
streams (stream_id, parent_id, created_at, closed, closed_at)
events  (id, stream_id, offset, type, data, created_at)
         -- UNIQUE(stream_id, offset)
sessions (session_id, description, mode, created_at, last_active, message_count)
```

### Event Types

```
stream_start | stream_end | state_change
user_message | assistant_message | system_message
tool_call | tool_result
token | question | answer
usage | error
```

### Stream Operations

```python
Store.create_stream(stream_id) → bool
Store.append(stream_id, event_type, data, offset?) → int
Store.read(stream_id, from_offset?, limit?) → list[Event]
Store.wait_for_new(stream_id, timeout?) → bool       # blocking tail
Store.close_stream(stream_id) → None
```

### Live-Tail Pattern

The `StreamClient.tail()` method yields events as they arrive, blocking when caught up:

```python
async for event in client.tail("agents/abc-123"):
    # Process event in real-time
    # Blocks on EOF until new data or stream closes
```

This enables real-time consumers without polling.

### Why Append-Only?

1. **Crash safety**: WAL mode + immutable events means no data loss on crash
2. **Replay**: Any session can be replayed from its event stream
3. **Audit**: Full history of every action the agent took
4. **Simplicity**: No update/delete logic, no race conditions
5. **Sub-agents**: Child loops write to their own streams with parent references

---

## LLM Provider Layer

### Provider Abstraction

```python
class BaseLLMProvider(ABC):
    api_format: ApiFormat    # chat_completions | responses

    def build_request(...) → LLMRequest
    def parse_stream_event(data) → StreamEvent | None
    def convert_tools(tools) → list[dict]
    def convert_messages(messages) → list[dict]
    async def create_turn(messages, model, tools?, temperature?) → ProviderTurnResult
    async def stream_text(...) → AsyncIterator[StreamEvent]
```

### Provider Capabilities

Providers declare their capabilities so the agent loop can adapt:

```python
ProviderCapabilities(
    supports_tools: bool,
    supports_streaming: bool,
    supports_reasoning: bool,          # extended thinking
    supports_images: bool,
    supports_cache_control: bool,
    supports_parallel_tool_calls: bool,
    reasoning_format: ReasoningFormat,  # NONE | OPAQUE | ENCRYPTED
    tool_call_id_format: ToolIdFormat,
    ...
)
```

### Streaming & Retry

- **SSE streaming** with `async for` over the response body
- **Max 3 retries** with exponential backoff for transient errors
- **Context overflow** → fail immediately (no retry)
- **Rate limiting** → retry with backoff + reset info
- **Server errors** → retry

### Concrete Providers

| Provider | API | Reasoning | Auth |
|----------|-----|-----------|------|
| **Copilot** | GitHub proxy → OpenAI Chat Completions | Opaque reasoning_text | GitHub token |
| **Codex** | OpenAI Responses API | Encrypted reasoning | OpenAI token |

---

## Extensibility

### Hooks

The `HookRegistry` provides named callback points throughout the system:

```python
# UI hooks (sync)
hooks.prompt(fn)              # Customize the prompt display
hooks.banner(fn)              # Add startup banner text
hooks.status(fn)              # Custom status bar text
hooks.turn_summary(fn)        # Post-turn summary

# Pipeline hooks (async, transform data)
hooks.before_send(fn)         # Transform user message before sending
hooks.after_result(fn)        # Transform agent result
hooks.system_prompt(fn)       # Modify system prompt

# Observer hooks (async, side-effects)
hooks.on_tool_call(fn)        # React to tool execution
hooks.on_tool_result(fn)      # React to tool completion
hooks.on_session_start(fn)    # React to new session

# Override hooks (first non-None wins)
hooks.on_approval(fn)         # Auto-approve/deny tools
```

### Extensions

Python files in `.taui/extensions/` or `~/.taui/extensions/` with a `register(tools, commands, hooks)` function:

```python
# .taui/extensions/my_ext.py
def register(tools, commands, hooks):
    tools.register(MyCustomTool())
    commands.register(MySlashCommand())
    hooks.before_send(my_preprocessor)
```

Extension failures are isolated — broken extensions log warnings but never crash the agent.

### Skills

Markdown files (`SKILL.md`) in `.agents/skills/<name>/` or `.taui/skills/<name>/`. Injected into the agent's system message as context. Max 8000 chars per skill, truncated if larger.

### MCP Servers

External tool servers via the Model Context Protocol. Configured in `.taui/mcp.toml`:

```toml
[servers.filesystem]
command = ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
```

Connected via JSON-RPC over subprocess stdin/stdout.

### Slash Commands

Registered via `CommandRegistry` with `register()` / `get()` / `alias()`. Built-in: `/help`, `/cost`, `/compact`, `/clear`.

---

## Data Flow

### User Message → Agent Response

```
User types in ChatInput, presses Enter
  ↓
TauiApp._do_send(text)
  ├─ Expand @file references
  ├─ Display user message in chat log
  ├─ Post AgentBusy message (switch UI state)
  └─ session.send(text)
       ├─ hooks.before_send(text)
       ├─ AgentLoop.run(text)
       │    ├─ Emit USER_MESSAGE event
       │    ├─ LLM call (streaming → StreamTextDelta messages)
       │    ├─ Emit ASSISTANT_MESSAGE event
       │    ├─ For each tool call:
       │    │    ├─ Emit TOOL_CALL event
       │    │    ├─ Post ToolStarted message
       │    │    ├─ ToolExecutor.run() → policy → execute
       │    │    ├─ Post ToolEnded message
       │    │    ├─ Emit TOOL_RESULT event
       │    │    └─ Drain steering queue
       │    └─ Repeat until no tool calls or max_turns
       ├─ hooks.after_result(result)
       ├─ Record cost in CostTracker
       └─ Update session metadata
  ↓
Post AgentIdle message (restore UI state)
Drain queued messages
```

### Tool Approval Flow

```
ToolExecutor detects CONFIRM policy
  ↓ return NeedsApproval
AgentLoop calls on_approval callback
  ↓
TauiApp mounts ApprovalPrompt to chat-log
  ↓
User clicks Allow or Deny
  ↓ Future resolves with bool
AgentLoop re-calls executor with approved=True|False
  ↓
Completed or Denied outcome
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Textual (not curses/prompt_toolkit)** | CSS-driven layouts, widget composition, built-in Markdown/TextArea/Tree, async-native, themes |
| **SQLite append-only store** | Crash-safe (WAL), replayable, no shared mutable state, simple concurrency |
| **Callbacks not bus** | Direct wiring via `Session` factory — no event bus indirection, clear dependency graph |
| **Policy gates on tools** | Users must opt-in to dangerous operations. Cascading policies allow per-project overrides |
| **ToolResult.fail() never raise** | Errors are data, not exceptions. The agent sees errors and can adapt |
| **Hooks for extensibility** | Pipeline hooks transform data, observer hooks add side-effects — all without forking code |
| **Inline CSS (no .tcss files)** | Bundled distribution — widgets carry their own styles, app is a single `pip install` |
| **Messages up, attributes down** | Textual's recommended data flow pattern — children post messages, parents set attributes |
| **Streaming via post_message** | Decouples LLM streaming from TUI rendering. Works across async task boundaries |
| **FIFO tool tracking** | Same tool name can run multiple times concurrently. FIFO ensures correct start→end matching |
| **Context compaction** | Preserve critical messages while staying in token budget. Two-phase: soft (80%) then aggressive (90%) |
| **Sub-agents with scoped tools** | Delegation without exposing the full tool set. Own streams for clean event separation |
| **Extensions mode sandboxing** | Restrict file writes to `.taui/` when developing extensions — defense in depth |

---

## Textual Patterns

Taui follows Textual's recommended patterns throughout:

### Messages Up, Attributes Down (Uni-Directional Data Flow)

Widgets communicate with parents exclusively through messages (`post_message`). Parents modify children by setting attributes directly. This prevents tangled dependencies and keeps widgets reusable.

```
TauiApp (parent)
  ├─ sets ChatInput.agent_busy = True       ← attributes down
  ├─ handles ChatInput.Submitted            ← messages up
  ├─ sets InfoBar.update_info(...)          ← attributes down
  └─ handles ToolStarted, ToolEnded         ← messages up
```

### Compound Widgets

Complex UI elements are built by composing simpler widgets:

- `QuestionsPanel` composes `_QuestionCard` widgets, each containing `Label` + `OptionList` + `Input`
- `ApprovalPrompt` composes `Label` + `Horizontal` + `Button` pair
- `InfoBar` composes model info + token display + spinner animation
- `Sidebar` composes `Static` header + `DirectoryTree`

### CSS Class Toggle for Visibility

Instead of mounting/unmounting widgets, Taui toggles CSS classes to show/hide:

```python
# Sidebar
self.toggle_class("visible")   # .visible { display: block; }

# CompletionDropdown
self.add_class("visible")      # default: display: none
self.remove_class("visible")
```

This avoids DOM churn and preserves widget state.

### Reactive Properties

Textual reactives drive automatic UI updates:

- `CompletionDropdown.selected_index` → triggers `_update_highlight()` watcher
- `ChatInput.can_submit` and `ChatInput.agent_busy` → control key behavior
- InfoBar spinner frame → animated via `set_interval`

### Layers for Overlays

The `CompletionDropdown` uses Textual's layer system to float above the chat area:

```python
LAYERS = ("default", "overlay")

class CompletionDropdown(Widget):
    # Rendered in the "overlay" layer, above all "default" layer widgets
```

### Async Event Handlers

All event handlers that perform I/O are `async`:

```python
async def handle_tool_started(self, message: ToolStarted) -> None:
    widget = ToolStatusWidget(message.tool_name, message.args_str)
    await self.mount(widget)  # await ensures widget is ready
```

### Widget Isolation

Each widget bundles its own `DEFAULT_CSS` and manages its own state. Widgets don't reach into siblings — they communicate through their parent. This makes widgets independently testable and reusable.

---

## System Prompt Construction

The `SystemPromptBuilder` uses template-based rendering with adaptive content:

```python
builder = SystemPromptBuilder(template)
builder.with_project_context(ctx)    # cwd, git status, platform, date
builder.with_tools(registry)         # tool list + guidelines
builder.render()                     # final prompt string
```

**Adaptive guidelines** vary based on which tools are available:
- If `edit` + `write`: "Prefer edit for targeted changes, write for new files"
- If `bash` + `grep`: "Prefer grep/glob over bash (faster, respects .gitignore)"

**Priority-based truncation** keeps the prompt within budget by dropping low-priority sections first (OPTIONAL → LOW → NORMAL → HIGH → CRITICAL).

---

## Configuration

Layered configuration with cascading precedence:

```
CLI args → environment variables → project .taui/config.toml → global ~/.config/taui/config.toml
```

Key settings:

| Setting | Default | Purpose |
|---------|---------|---------|
| `provider` | `"copilot"` | LLM provider |
| `model` | auto | Model selection |
| `max_turns` | 50 | Safety limit per interaction |
| `auto_approve_reads` | `true` | Skip approval for read-only tools |
| `verbose_tools` | `true` | Show tool output previews |

---

## Testing

```bash
uv run python -m pytest tests/ -q
```

- **pytest** with `asyncio_mode = "auto"`
- **MockLLMProvider** instead of real HTTP
- **Test tools** (`EchoTool`, `FailTool`) for isolated tool testing
- **TUI tests**: Widget rendering, message handling, FIFO tracking, history, @file expansion
- **No external dependencies** in tests — everything is mocked or in-memory

---

## Build & Tooling

| Tool | Purpose |
|------|---------|
| `uv` | Package installer and project manager |
| `hatchling` | Build backend |
| `ruff` | Linter — rules: E, F, I, UP; 100-char line limit; target py313 |
| `pytest` | Test runner |
