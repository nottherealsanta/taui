# Taui - Technical Deep Dive

**taui** (v0.9) is a customizable agentic coding interface - a full-screen Textual TUI for AI-assisted development. It's an event-sourced, extensible agent harness with built-in tools for file operations, bash execution, git workflows, code editing, web fetching, and more.

## Project Stats
- **~154 Python source files**
- **~3,700 LOC in root taui/ module**
- **~4,460 LOC just in the TUI app (app.py)**
- **Requires Python 3.13+**
- **Alpha status (v0.9)** with active development

---

## Architecture Overview

### Core Components

#### 1. Main Entry Point (`taui/main.py:104, :180`)
- CLI arg parsing for provider, model, directory, session resumption, debug mode, debug socket
- Logging setup to `~/.taui/.logs`
- Launches `TauiApp` (the Textual TUI)

#### 2. Session (`taui/session.py:66`) - Composition Root
The wiring point that brings everything together:
- **Owns:** provider, tool registry, executor, agent loop, event store
- **Key Methods:**
  - `Session.create()` - factory that builds the full runtime
  - `Session.send()` - entry point for user messages
  - `Session.switch_variant()` - apply agent profile changes
  - `Session.resume_session()` - restore from event stream
- **Modes:** normal, self-edit, extensions-mode
- **Tracks:** costs with `CostTracker`

#### 3. AgentLoop (`taui/agent/loop.py:99`) - Core Agent Logic
The **think → tool → observe cycle**:
- **States:** IDLE, THINKING, TOOL_EXECUTION, DONE, ERROR
- **Async streaming** with callbacks for live output
- **Handles:**
  - Provider calls with streaming events
  - Tool call extraction and execution
  - Context compaction when token budget exceeded
  - Rate limiting per provider
  - Turn-by-turn event recording
- **Results:** `TurnResult` + `RunResult` with usage/cost tracking
- **Configurable:** max turn limit (default 50)

#### 4. TUI App (`taui/tui/app.py:65`)
Textual-based full-screen interface (~4,460 LOC):
- **Key Widgets:**
  - `ChatInput` - message input with history
  - `AgentResponse` - streaming response display
  - `Sidebar` - file browser, sessions, attachments
  - `Info2` - metadata/costs display
  - `TurnContainer` - collapsible turn blocks
  - `BashToolStatusWidget`, `ToolStatusWidget` - live tool execution
  - `ApprovalController` - permission gates UI
  - `QuestionsPanel` - structured Q&A
- **Multi-Session Support:** via `SessionManager` (new in recent commits)
- **Theming:** CSS-based with multiple color schemes (`app.tcss`)

#### 5. Event Store (`taui/store/store.py:113`)
**SQLite append-only event log** (default: `.taui/store.db`):
- **Schema:** `streams`, `events`, `sessions` tables
- **Event Types:** STREAM_START, STREAM_END, STATE_CHANGE, USER_MESSAGE, ASSISTANT_MESSAGE, SYSTEM_MESSAGE, TOOL_CALL, TOOL_RESULT, TOKEN, QUESTION, ANSWER, USAGE, ERROR, COMPACTION, WORKTREE, TASK
- **Stream Model:** per session with parent_id for sub-agents
- **Immutable:** append-only with offset uniqueness
- **Replay:** `StreamClient` projects events back into conversations
- **Features:** Turn grouping, live tailing, session persistence

#### 6. Tool System (`taui/tools/`)
- **Base Protocol:** `Tool` interface in `base.py:72`
- **Categories:** FILE_READ, FILE_WRITE, SEARCH, SHELL, GIT, AGENT, MEMORY, QUESTION
- **Registry:** `ToolRegistry` with grouping support
- **Executor:** `ToolExecutor` with policy-based approval gate (`taui/tools/executor.py:152`)
- **Streaming:** Context var for live output callbacks

### Data Flow

```
User Input (TUI)
    ↓
TauiApp.ChatInput → Session.send(message)
    ↓
AgentLoop.run() starts new stream
    ↓
LLM Provider (Copilot/Codex) streamed response
    ↓
Provider parser converts StreamEvents:
    - text_delta: model thinking/response
    - reasoning_delta: reasoning token stream
    - tool_call_done: function call from model
    - usage: token counts + costs
    ↓
ToolExecutor.execute()
    - Policy decision (AUTO/CONFIRM/DENY)
    - Approval callback to UI if needed
    - Tool runs with output delta callback
    ↓
TOOL_RESULT event written to store
    ↓
Loop continues (max_turns) until final ASSISTANT_MESSAGE
    ↓
Results displayed in UI + stored
    ↓
UI callbacks: on_text_delta, on_tool_call, on_tool_result, on_approval
```

---

## Core Modules

### `taui/agent/` - Agent Logic
- **loop.py** - main agent loop with streaming, tool execution, context compaction
- **context.py** - token estimation, message compaction strategy
- **context_strategy.py** - pluggable context management protocol
- **tokenizer.py** - token counting with provider-specific models
- **types.py** - Message dataclass (role + content)
- **variants.py** - AgentVariant profiles (model, prompt, tool restrictions, read-only mode)

### `taui/llm_provider/` - LLM Integration
- **base.py** - BaseLLMProvider abstract class with streaming, auth refresh
- **types.py** - ProviderToolCall, ProviderTurnResult, StreamEvent, ProviderCapabilities
- **providers/copilot.py** - GitHub Copilot implementation
- **providers/codex.py** - OpenAI Codex implementation
- **auth/** - Device flow, PKCE browser flow handlers
- **models.py** - Model catalog and caching
- **rate_limit.py** - Per-provider rate limiting
- **errors.py** - ContextOverflowError, QuotaExceededError

### `taui/tools/` - Tool Execution
- **base.py** - ToolResult, Tool protocol, output delta callbacks
- **registry.py** - ToolRegistry with grouping
- **executor.py** - ToolExecutor with PolicyDecision (AUTO/CONFIRM/DENY)
- **builtins/** - 20+ built-in tools:
  - **files.py** - read, write, glob, grep
  - **edit.py** - structured code editing
  - **apply_patch.py** - unified diff patching
  - **bash.py** - shell execution with live output (BashTool, BashStatusTool, BashKillTool)
  - **git.py** - git operations
  - **question.py** - ask user with structured options
  - **memory.py** - persistent key-value store
  - **peek.py** - retrieve windows from truncated tool outputs
  - **sub_agent.py** - spawn scoped agent instances
  - **task.py** and **tasks/** - background task management (TaskTool, TaskCreateTool, TaskGetTool, TaskListTool, TaskOutputTool, TaskStopTool, TaskUpdateTool)
  - **webfetch.py** - fetch URL content
  - **worktree.py** - git worktree management
  - **lsp.py** - Language Server Protocol integration
  - **mcp.py** - Model Context Protocol client (with inspect and search operations)
  - **skills.py** - load, unload, and trigger Markdown workflows
  - **repo_overview.py** - project structure summary
  - **session_name.py** - name current session

### `taui/store/` - Persistence
- **store.py** - SQLite store, stream/event/session management
- **stream.py** - StreamClient for event projection and replay
- **events.py** - EventType enum and Event dataclass

### `taui/extensions/` - Plugin System
- **__init__.py** - ExtensionContext, ExtensionRegistry, and loading machinery
- **builtins.py** - built-in extension hooks
- **Extension Points:**
  - `ctx.tools` - register custom tools
  - `ctx.commands` - register slash commands
  - `ctx.hooks` - add event handlers
  - `ctx.policy` - set tool policies
  - `ctx.skills` - add Markdown workflow files
  - `ctx.agents` - register agent variants
  - `ctx.context` - register context strategies
  - `ctx.providers` - register provider metadata

### `taui/commands/` - Slash Commands
**30+ command implementations** including:
- `/help`, `/model`, `/variant`, `/provider`, `/agents`, `/sessions`, `/new`
- `/compact`, `/context`, `/clear` - context management
- `/extensions`, `/reload`, `/ext-mode` - extension management
- `/i` (`/self-edit`) - self-edit mode
- `/skills`, `/prompts` - skill and prompt workflows
- `/copy`, `/export` - session export
- `/cost` - token cost display
- `/tasks` - background task listing
- `/mcp` - MCP server management
- `/login`, `/logout` - provider authentication
- `/theme`, `/debug`, `/hotkeys`, etc.

### `taui/tui/` - User Interface
- **app.py** - Main TauiApp (4,460+ LOC)
- **widgets/** - Reusable UI components
- **screens/** - Modal overlays (context, theme, variant selection)
- **session_state.py** - SessionManager for multi-session support
- **tool_controller.py** - Bridges loop to tool UI
- **approval_controller.py** - Approval workflow

### `taui/self_edit/` - Self-Editing Mode
- Creates specialist agent for editing extensions/skills
- Constrains writes to `.taui/` paths
- Enables agents to customize themselves

### `taui/permissions.py` - Permission DSL
- **PermissionRule** dataclass with (tool, pattern) → (allow/ask/deny)
- **PermissionRuleset** with pattern matching and specificity ordering
- Evaluation layers: agent → project → global
- Subjects extracted per-tool (file_path, bash command, etc.)
- TOML config support

### `taui/config.py` - Configuration
- **Config** dataclass with:
  - provider, model, model_variant, max_turns, sub_agent_max_turns, verbose_tools
  - tool_policy (per-tool defaults)
  - permission (pattern rules)
  - working_dir, session_id
  - theme, keybindings, extension_dirs, prefixes, notifications
  - self_edit_confirm_edits
- All file config — credentials, last-used state, and `[taui]` settings — loads from
  the single `~/.config/taui/config.toml`; CLI/env overrides win at `Config.load()`

### `taui/prompt_builder.py` - System Prompt
- Discovers project context from:
  - `AGENTS.md`, `.taui/instructions.md`, `.taui/AGENTS.md`
  - Walks from root toward working dir
- Injects tool metadata (name, description, schema)
- Custom override via `.taui/system_prompt.md`
- Applies `system_prompt` hook for extensions

### `taui/hooks.py` - Event Hooks
- **HookRegistry** - isolated handler storage
- **Common hooks:**
  - `system_prompt` - modify AI prompt
  - `on_tool_call` - observe requests
  - `on_tool_result` - observe results
  - `on_approval` - intercept decisions
- Failures are logged and isolated

### `taui/mcp/` - Model Context Protocol
- **McpClient** - stdio JSON-RPC to subprocess
- **McpHttpClient** - HTTP/SSE transport alternative
- **McpManager** - manages multiple servers
- Config via `.taui/mcp.toml` (project), `~/.taui/mcp.toml` (global), or `~/.config/taui/mcp.toml` (legacy)
- Tools prefixed with `mcp__<server>__<name>`

### `taui/lsp/` - Language Server Integration
- Provides goto_definition, find_references, hover, symbols
- Per-language server management

### `taui/tasks/` - Background Task Management
- **TaskManager** - async task queue
- **TaskRecord** - task metadata and state
- Persistence in task store
- `/tasks` command for visibility

### `taui/worktree.py` - Git Worktree Support
- Sandboxed git branches
- Safe experimentation without main branch mutation
- `worktree` tool for enter/exit/status operations

### `taui/skills/` - Markdown Workflows
- `SKILL.md` files with agent prompts
- Discovered from `.taui/skills/`, `~/.taui/skills/`, `.agents/skills/`, `~/.config/agents/skills/`
- Lazy loading and caching via `SkillRegistry`
- Skills tool supports load, unload (with message removal), and status operations

---

## Key Design Patterns

### Event Sourcing
- All state changes → immutable events in SQLite
- Streams are append-only event logs
- Replay by reading events in order
- No separate event bus (use EventType directly)

### Composition Root
- `Session.create()` wires all dependencies
- All dependencies injected; easy to test with mocks

### Policy Pattern
- `ToolPolicy` + `PermissionRuleset` for tool execution gates
- Decisions made before execution, not after
- Patterns support fine-grained matching

### Plugin Architecture
- Extension registration via `register(ctx)` function
- Extensions are isolated (failures logged, not propagated)
- Hooks for observation/transformation without modifying core
- Tools/commands/strategies/agents all extensible

### Streaming Callbacks
- Context vars for live output deltas
- Decouples tool execution from UI rendering
- Used by bash tool for live tail during execution

### Context Strategies
- Pluggable token management
- Default: estimate → drop old messages when budget exceeded
- Custom strategies can override compaction logic

### Multi-Session Management (Recent)
- `SessionManager` tracks multiple session states
- UI can switch between sessions
- Session persistence and resumption

---

## Configuration

### TOML Config File
- Single file: `~/.config/taui/config.toml` — provider credentials under
  `[providers.<name>]`, last-used model/variant state, and settings under `[taui]`

### Config Example
```toml
[taui]
provider = "copilot"
model = "claude-sonnet-4.5"
max_turns = 50
verbose_tools = true

[taui.tool_policy]
bash = "confirm"
write = "confirm"
edit = "confirm"

[taui.permission]
read = { "*" = "allow" }
bash = { "git status" = "allow", "*" = "ask" }
edit = { "src/*" = "allow", "*" = "ask" }
```

### Agent Variants (`.taui/agents/<name>.toml`)
```toml
name = "review"
description = "Read-only code review"
read_only = true
max_turns = 20
system_prompt = "Review the code. Do not edit files."

[permission]
read = { "*" = "allow" }
grep = { "*" = "allow" }
```

### MCP Servers (`.taui/mcp.toml` or `~/.taui/mcp.toml`)
```toml
[servers.filesystem]
command = ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

[servers.github]
command = ["npx", "-y", "@modelcontextprotocol/server-github"]
env = { GITHUB_TOKEN = "..." }
```

### Extensions (`.taui/extensions/*.py`)
```python
def register(ctx):
    ctx.tools.register(MyTool())
    ctx.hooks.add("system_prompt", modify_prompt)
    ctx.agents.register(AgentVariant(name="review", read_only=True))
```

---

## Testing Infrastructure

### Test Organization
| Change Area | Tests |
|------|-------|
| Tools & policy | `tests/test_tools.py`, `tests/test_builtins.py` |
| Agent & context | `tests/test_agent.py`, `tests/test_context.py` |
| TUI behavior | `tests/test_tui.py`, `tests/test_tui_visual.py` |
| Config/session/store | `tests/test_config.py`, `tests/test_session.py` |
| Extensions/skills | `tests/test_extensions.py`, `tests/test_skills.py` |
| Provider scenarios | `tests/test_provider_scenarios.py` |

### Scripted Provider Harness
- **ScriptedProvider** - deterministic mock for testing without network
- **Scenario factories** - reusable test scenarios
- **Visual snapshots** - render TUI with snapshot comparison
- All tests offline and deterministic

### Running Tests
```bash
uv run ruff check .              # Linting
uv run python -m pytest tests/ -q  # Run all tests
uv run python -m pytest tests/test_tui_visual.py --snapshot-update  # Update snapshots
```

---

## Notable Advanced Features

### Context Compaction
- **Automatic:** Token estimation before each provider call
- Preserves essential messages (user request, system prompt)
- Drops oldest non-essential messages when over budget
- `COMPACTION` event records when it happens
- Manual `/compact` command
- User can see what was compacted

### Sub-Agents
- `sub_agent` tool spawns independent agent instances
- Scoped tool access (read-only by default)
- Parallel execution in agent loop
- Useful for code review, analysis, multi-stage workflows

### Background Tasks
- `task` tool creates async queues
- `TaskManager` tracks running, queued, completed tasks
- `/tasks` command lists all background work
- Agents can spawn, monitor, and wait on tasks

### Worktrees
- `worktree` tool creates sandboxed git branches
- Safe experimentation without main branch mutation
- Enter/exit worktree contexts
- Auto-cleanup on exit

### Self-Edit Mode (`/i`)
- Agent edits extension/skill files directly
- Specialist executor constrains writes to `.taui/`
- Enables agents to customize themselves

### Extensions Mode
- `/ext-mode` for working on extensions/skills
- Path guards for safety
- Separate permissions layer

### MCP Integration
- Connect to external MCP servers (stdio or HTTP)
- Tools, resources, and prompt templates from servers
- Sampling support (server can request model calls)
- Named tool prefixing to avoid collisions

### LSP Integration
- Full language server support
- Go-to-definition, find references, hover, symbols
- Per-language server management
- Used by agents for code navigation

### Cost Tracking
- `CostTracker` estimates USD cost per turn
- Token counts: input, output, cache_read, cache_write, reasoning
- Per-model pricing (Claude models, etc.)
- `/cost` command shows aggregate costs

### Hot Reload
- `/reload` reloads extensions without restarting
- Extension changes take effect immediately
- Skill files are lazy-loaded

### Structured Questions
- `question` tool with:
  - Structured options (label, description)
  - Recommended option marker
  - User can provide custom answers
  - Parsed responses back to agent

---

## Technology Stack

### Core Dependencies
- **Python 3.13+** - primary language
- **Textual 3.0+** - TUI framework
- **aiosqlite 0.20+** - async SQLite
- **httpx 0.28+** - async HTTP client
- **rich 13.0+** - terminal rendering
- **textual-diff-view 0.1.2+** - diff widget

### Development
- **pytest-asyncio** - async test runner
- **pytest-textual-snapshot** - visual snapshot testing
- **textual-dev** - dev server for TUI debugging

### Linting
- **Ruff** - Python linter (100 char lines, Python 3.13 target)

### Build
- **Hatchling** - build backend

---

## Key Invariants & Safety Rules

1. **Session history is store-backed** - use EventType and stream projections, not a separate event bus
2. **Tools return ToolResult.ok() or ToolResult.fail()** - only raise for truly unexpected bugs
3. **Permissions decided before tool execution** - policy gates before invocation
4. **Provider-specific logic stays in `taui/llm_provider/providers/`**
5. **UI behavior belongs in `taui/tui/app.py`** - not in Session or AgentLoop
6. **Extensions are isolated** - failures logged and skipped without crashing
7. **Schemas must be JSON-serializable** - provider conversion happens downstream
8. **Keep extensions small and import-light**
9. **Use permission rules for auto-approval** - don't bypass policy

---

## CLI Usage

```bash
taui                                    # Start with default config
taui -p copilot -m claude-sonnet-4.5    # Pick provider/model
taui -d /path/to/project                # Set working directory
taui --session <session_id>             # Resume prior session
taui --login                            # Authenticate providers
taui --debug                            # Start with embedded MCP debug server
taui --debug-socket /tmp/taui.sock      # Custom Unix socket for debug server
taui --version                          # Show version
```

---

## Summary

**taui** is a sophisticated **event-sourced agent harness** with these hallmarks:

✅ **Composable** - all components are injectable  
✅ **Extensible** - hooks, tools, commands, skills, agents, strategies all pluggable  
✅ **Safe** - policies before execution, permissions DSL, isolated extensions  
✅ **Durable** - SQLite append-only streams, full replay capability  
✅ **Streaming-aware** - designed for live output and long-running operations  
✅ **Production-grade** - comprehensive testing, logging, error handling  
✅ **Context-aware** - automatic token compaction, multi-session, cost tracking  
✅ **Provider-agnostic** - pluggable LLM backends (Copilot, Codex, custom)

It's not just a TUI—it's a **framework for building AI-assisted coding workflows** with full programmatic control over every step.
