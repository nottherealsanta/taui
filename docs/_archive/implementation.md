# Taui Implementation Reference

This document describes every module, class, method, and data flow in the
taui runtime as currently built. It is the canonical reference for the agent
to consult before making changes. If you are editing taui, read this first.

---

## Directory Layout

```
taui/
├── __init__.py              # Package marker
├── __main__.py              # `python -m taui` entry → cli.main()
├── cli.py                   # CLI REPL, arg parsing, display callbacks
├── config.py                # Runtime Config dataclass
├── cost.py                  # CostTracker: per-session token/cost accounting
├── prompt_builder.py        # SystemPromptBuilder: structured prompt + instruction discovery
├── session.py               # Session — wires provider + tools + agent loop
├── tui.py                   # Textual terminal UI (opt-in --tui)
│
├── agent/
│   ├── __init__.py           # Re-exports AgentLoop, AgentState
│   ├── context.py            # Compaction: compact_messages(), token estimation
│   └── loop.py               # AgentLoop: think → tool → observe cycle
│
├── commands/
│   ├── __init__.py           # Re-exports CommandRegistry, CommandResult
│   ├── registry.py           # CommandRegistry: slash command dispatch
│   └── builtins.py           # Built-in commands: help, cost, clear, model, compact, extensions
│
├── extensions/
│   └── __init__.py           # ExtensionRegistry: discover + load .py extensions
│
├── lsp/
│   ├── __init__.py           # Re-exports LspManager, LspClient, LspError, types
│   ├── client.py             # LspClient: single LSP server subprocess over stdio JSON-RPC
│   ├── manager.py            # LspManager: per-language lifecycle, high-level operations
│   └── types.py              # Position, Range, Location, Diagnostic, SymbolInfo, HoverResult
│
├── mcp/
│   └── __init__.py           # McpClient, McpManager, McpTool (MCP protocol)
│
├── server/
│   ├── __init__.py           # Re-exports protocol types
│   ├── app.py                # FastAPI app factory, serve() launcher (opt-in --web)
│   └── protocol.py           # JSON-RPC 2.0 parse/format helpers
│
├── skills/
│   └── __init__.py           # SkillRegistry: discover SKILL.md packages
│
├── store/
│   ├── __init__.py           # Re-exports Store, StreamClient, Event, EventType
│   ├── events.py             # EventType enum, Event frozen dataclass
│   ├── store.py              # Store: SQLite append-only event log
│   └── stream.py             # StreamClient: high-level read/write/tail
│
├── symbols/
│   ├── __init__.py           # Re-exports SymbolIndexer, SymbolEntry
│   ├── indexer.py            # AST-based Python symbol indexer
│   └── models.py             # SymbolEntry dataclass
│
├── tools/
│   ├── __init__.py           # Re-exports
│   ├── base.py               # Tool protocol, ToolResult, ToolCategory enum
│   ├── registry.py           # ToolRegistry: named collection + schema export
│   ├── executor.py           # ToolExecutor: policy gate + dispatch
│   └── builtins/
│       ├── __init__.py       # register_builtins() → registers all 12 tools
│       ├── common.py         # Shared: resolve_path, is_binary, suggest_similar, truncate, SKIP_DIRS
│       ├── files.py          # ReadTool, WriteTool, GlobTool, GrepTool
│       ├── edit.py           # EditTool: search-and-replace with fuzzy matching
│       ├── bash.py           # BashTool: sandboxed shell execution
│       ├── git.py            # GitTool: git operations (status, diff, commit, etc.)
│       ├── memory.py         # MemoryTool: persistent cross-session knowledge
│       ├── question.py       # QuestionTool: ask user for clarification
│       ├── sub_agent.py      # SubAgentTool: spawn child agent loops
│       ├── skills.py         # SkillsTool: discover/load/unload skills
│       └── mcp.py            # McpTool: connect/call external MCP servers
│
└── llm_provider/
    ├── __init__.py
    ├── base.py               # BaseLLMProvider ABC: retry, streaming, error classification
    ├── types.py              # ProviderTurnResult, ProviderToolCall, StreamEvent, Usage, etc.
    ├── config.py             # TOML config persistence (~/.config/taui/config.toml)
    ├── provider_probe.py     # Interactive probe script for testing providers
    ├── auth/
    │   ├── __init__.py       # get_credentials(provider) dispatcher
    │   ├── copilot.py        # GitHub Copilot OAuth device flow
    │   ├── codex.py          # OpenAI Codex PKCE OAuth flow
    │   └── pkce.py           # PKCE utilities: generate, callback server
    └── providers/
        ├── __init__.py       # Re-exports CopilotProvider, CodexProvider
        ├── copilot.py        # CopilotProvider: Chat Completions API
        └── codex.py          # CodexProvider: Responses API
```

---

## Data Flow: User Message → Response

```
User types message
        │
        ▼
    cli.Repl._send(message)
        │
        ▼
    session.Session.send(message)
        │
        ├── loop.run(user_message)
        │
        ▼
    agent.AgentLoop.run(user_message)
        │
        ├── Appends Message(role="user") to self._messages
        │
        ▼
    AgentLoop._think_and_act(turn)
        │
        ├── 1. _call_llm()
        │   ├── _build_llm_messages() → list[dict]  (Chat Completions format)
        │   ├── executor.registry.schemas() → tool schemas
        │   └── llm.create_turn(messages, model, tools=schemas)
        │       └── BaseLLMProvider: build_request → _stream_turn_with_retry → _accumulate_turn
        │           └── Returns ProviderTurnResult(text, tool_calls, usage)
        │
        ├── 2. Append Message(role="assistant") to history
        │   └── Fire on_text callback if text present
        │
        ├── 3. If tool_calls: for each ProviderToolCall:
        │   ├── Fire on_tool_call callback
        │   ├── executor.run(call_id, name, arguments)
        │   │   ├── policy.decide(tool_name) → AUTO|CONFIRM|DENY
        │   │   ├── If CONFIRM and no approval: → NeedsApproval
        │   │   │   └── Fire on_approval callback → user answers y/n
        │   │   ├── tool.execute(arguments) with asyncio.timeout
        │   │   └── Returns Completed|NeedsApproval|Denied
        │   ├── Append Message(role="tool") to history
        │   └── Fire on_tool_result callback
        │
        └── 4. If no tool_calls → return RunResult(text, turns)
            Else → repeat from step 1 (next turn)
```

---

## Module Reference

### `taui/config.py` — Runtime Configuration

```python
@dataclass
class Config:
    provider: str = "copilot"              # "copilot" | "codex"
    model: str = "claude-sonnet-4.6"
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    max_turns: int = 50
    working_dir: Path = Path.cwd()
    auto_approve_reads: bool = True

    @classmethod
    def load(cls, **overrides) -> Config
        # Reads ~/.config/taui/config.toml [taui] section
        # Then applies keyword overrides (CLI args)
```

**Config layering**: defaults → TOML file → overrides. Any field can be set at
any layer. `None` overrides are ignored.

**DEFAULT_SYSTEM_PROMPT**: Brief engineer persona with rules about reading
before editing, minimal changes, preferring `edit` over `write`, running tests.
The Session appends tool guidelines to this at runtime.

---

### `taui/session.py` — Session Wiring

The Session is the composition root. It creates and owns every component:

```python
class Session:
    @classmethod
    async def create(cls, config: Config | None = None) -> Session:
        # 1. Create LLM provider (triggers OAuth if needed)
        # 2. Create ToolRegistry, register_builtins(), set working_dir
        # 3. Create ToolPolicy + ToolExecutor
        # 4. Append registry.guidelines() to system prompt
        # 5. Create Store (SQLite at working_dir/.taui/store.db)
        # 6. Create StreamClient
        # 7. Create AgentLoop with all components
        # 8. Return Session wrapping everything

    async def send(self, message: str) -> RunResult
        # Runs loop, records cost from each turn's usage via CostTracker
    async def close(self) -> None
```

**Key design decision**: The Session constructor takes all components as kwargs,
so tests can inject mocks without touching `create()`. The `create()` classmethod
is the production assembly path.

**Provider creation**: `_create_provider(config)` calls `get_credentials(provider)`
which triggers the OAuth flow interactively if no saved credentials exist.

---

### `taui/cli.py` — CLI REPL

```python
class Repl:
    def __init__(self, session: Session)
        # Wires callbacks: on_tool_call, on_tool_result, on_approval
        # Wires question tool's _ask callback
        # Builds slash command registry

    async def run(self) -> None          # Main REPL loop
    def _print_banner(self) -> None      # Provider/model/cwd header
    def _prompt(self) -> str             # Multiline input (trailing \)
    async def _handle_command(cmd) -> bool  # Dispatch to CommandRegistry; /quit handled directly
    async def _send(message) -> None     # Send to agent, display result + cost

    # Agent loop callbacks:
    async def _on_tool_call(call_id, name, arguments)     # "▸ read(src/main.py)"
    async def _on_tool_result(call_id, name, content, is_error)  # Compact result
    async def _on_approval(call_id, name, arguments) -> bool     # "Allow? [y/N]"
    async def _ask_question(question, options) -> str | None     # Interactive question prompt
    @staticmethod
    def _format_args(name, arguments) -> str  # Tool-specific arg summary (read, write, edit, glob, grep, bash, git, question)
```

**Arg parsing**: `parse_args(argv)` returns a dict with optional keys:
`provider`, `model`, `working_dir`, `initial_message`. Used by
`async_main()` which creates Session and either runs REPL or sends one message.

**Entry point chain**: `taui` script → `cli.main()` → `asyncio.run(async_main())`.
Also: `python -m taui` → `__main__.py` → `cli.main()`.

**Color helpers**: `_dim`, `_bold`, `_green`, `_yellow`, `_red`, `_cyan`.
Auto-detect TTY via `_supports_color()`. All return plain text if no TTY.

---

### `taui/agent/context.py` — Context Compaction

```python
DEFAULT_MAX_INPUT_TOKENS = 180_000
COMPACTION_SOFT_RATIO = 0.80
COMPACTION_HARD_RATIO = 0.90

def estimate_message_tokens(msg: Message) -> int
    # ~4 chars per token, includes content + tool_calls + metadata

def estimate_total_tokens(messages: list[Message]) -> int

def compact_messages(messages, max_input_tokens, soft_ratio, hard_ratio) -> int
    # Phase 1: drop oldest droppable until under soft limit
    # Phase 2: if still over hard limit, aggressive dropping
    # Preserves: latest system, latest user, unresolved tool calls
    # Inserts summary marker after compaction
    # Returns: number of messages removed
```

**Integration**: `AgentLoop._maybe_compact()` calls `compact_messages()` before
each LLM turn when estimated tokens exceed 80% of budget.

---

### `taui/agent/loop.py` — Agent Loop

The core think → tool → observe cycle.

```python
class AgentState(str, Enum):
    IDLE, THINKING, TOOL_EXECUTION, DONE, ERROR

@dataclass
class Message:
    role: str                                    # system|user|assistant|tool
    content: str | None
    tool_calls: list[ProviderToolCall] | None    # For assistant messages
    tool_call_id: str | None                     # For tool result messages
    name: str | None                             # Tool name for results

@dataclass
class TurnResult:
    text: str | None
    tool_calls_count: int
    turn_number: int
    usage: dict[str, Any] | None

@dataclass
class RunResult:
    text: str
    turns: int
    state: AgentState
    turn_results: list[TurnResult]

class AgentLoop:
    def __init__(self, *, agent_id, llm, executor, stream, system_prompt,
                 model, max_turns, on_tool_call, on_tool_result, on_approval, on_text)

    async def run(self, user_message: str) -> RunResult
    async def _think_and_act(self, turn: int) -> TurnResult
    async def _call_llm(self) -> ProviderTurnResult
    async def _execute_tool(self, tc: ProviderToolCall) -> None
    def _build_llm_messages(self) -> list[dict[str, Any]]
    async def _emit(self, event_type: EventType, data: dict) -> None
```

**Callback signatures** (all optional, `None` = no-op):
- `on_tool_call(call_id: str, name: str, arguments: dict) -> Awaitable[None]`
- `on_tool_result(call_id: str, name: str, content: str, is_error: bool) -> Awaitable[None]`
- `on_approval(call_id: str, name: str, arguments: dict) -> Awaitable[bool]`
- `on_text(text: str) -> Awaitable[None]`

**Approval flow**: When `ToolExecutor.run()` returns `NeedsApproval`, the loop
calls `on_approval`. If no callback is set, it auto-approves. If the callback
returns `False`, the tool result is `"Tool call denied by user."` with
`is_error=True`.

**Message format**: Internal `Message` objects are converted to Chat Completions
dicts by `_build_llm_messages()`. Tool calls serialize via
`ProviderToolCall.to_chat_completions_format()`.

**Stream emission**: Every state change, message, tool call, and result is
emitted to the Store via `StreamClient.append()`. This is the full audit log.

---

### `taui/store/` — Event Store

#### `events.py`

```python
class EventType(str, Enum):
    STREAM_START, STREAM_END, STATE_CHANGE,
    USER_MESSAGE, ASSISTANT_MESSAGE, SYSTEM_MESSAGE,
    TOOL_CALL, TOOL_RESULT, TOKEN,
    QUESTION, ANSWER, USAGE, ERROR

@dataclass(frozen=True, slots=True)
class Event:
    stream_id: str
    offset: int
    type: EventType
    data: dict[str, Any]
    created_at: float
```

#### `store.py`

```python
class Store:
    def __init__(self, workspace: Path, *, db_path: Path | None = None)
        # Default db_path: workspace/.taui/store.db

    async def connect(self) -> None       # Opens SQLite, creates schema, WAL mode
    async def close(self) -> None         # Closes DB, wakes all waiters

    async def create_stream(stream_id, *, parent_id=None) -> None  # Idempotent
    async def stream_exists(stream_id) -> bool
    async def get_stream_info(stream_id) -> dict
    async def close_stream(stream_id) -> None
    async def is_closed(stream_id) -> bool

    async def append(stream_id, event_type, data, *, offset=None) -> int
        # Auto-increment offset if not specified
        # Explicit offset enables idempotent replay
        # Raises OffsetConflictError on collision with different data

    async def read(stream_id, *, from_offset=0, limit=1000) -> list[Event]
    async def get_length(stream_id) -> int
    async def wait_for_new(stream_id, *, timeout=30.0) -> bool
        # Blocks on asyncio.Event, woken by append() or close()
```

**Schema**: Two tables — `streams` (stream_id PK, parent_id, created_at,
closed, closed_at) and `events` (id autoincrement, stream_id FK, offset,
type TEXT, data TEXT JSON, created_at, UNIQUE(stream_id, offset)).

**Exceptions**: `StreamNotFoundError`, `StreamClosedError`, `OffsetConflictError`.

#### `stream.py`

```python
class StreamClient:
    def __init__(self, store: Store)

    async def ensure_stream(stream_id, *, parent_id=None) -> None
    async def close_stream(stream_id) -> None
    async def append(stream_id, event_type, data) -> int
    async def read(stream_id, *, from_offset=0, limit=1000) -> list[Event]
    async def read_all(stream_id) -> list[Event]
    async def tail(stream_id, *, from_offset=0, poll_timeout=30.0) -> AsyncIterator[Event]
        # Catches up from offset, then blocks on wait_for_new
        # Exits when stream is closed
```

---

### `taui/tools/` — Tool System

#### `base.py`

```python
class ToolCategory(str, Enum):
    FILE_READ, FILE_WRITE, SEARCH, SHELL, GIT, AGENT, MEMORY, QUESTION

@dataclass(slots=True)
class ToolResult:
    content: str
    error: bool = False
    metadata: dict[str, Any] = {}

    @classmethod ok(cls, content, **metadata) -> ToolResult
    @classmethod fail(cls, content, **metadata) -> ToolResult

class Tool(Protocol):
    name: str
    description: str
    schema: dict[str, Any]       # JSON Schema for arguments
    category: ToolCategory
    async def execute(self, arguments: dict[str, Any]) -> ToolResult
```

**Optional fields** not in the Protocol but used by builtins:
- `guidelines: str` — text appended to system prompt
- `working_dir: Path` — scoped to workspace directory

#### `registry.py`

```python
class ToolRegistry:
    def register(self, tool: Tool) -> None        # Raises on duplicate name
    def register_or_replace(self, tool: Tool)     # Upsert
    def unregister(self, name: str) -> Tool        # Raises if missing
    def get(self, name: str) -> Tool               # Raises if missing
    def __contains__(self, name: str) -> bool
    def __len__(self) -> int
    @property names -> list[str]                   # Sorted
    def by_category(category) -> list[Tool]
    def schemas(*, include=None, exclude=None) -> list[dict]
        # Returns OpenAI function-calling format:
        # [{"type": "function", "function": {"name", "description", "parameters"}}]
    def subset(names: list[str]) -> ToolRegistry   # For sub-agent scoping
    def guidelines() -> str                        # Collects tool.guidelines into markdown
```

#### `executor.py`

```python
class PolicyDecision(str, Enum):
    AUTO, CONFIRM, DENY

class ToolPolicy:
    def decide(self, tool_name: str) -> PolicyDecision
    def set(self, tool_name: str, decision: PolicyDecision)

# Outcomes:
@dataclass Completed(result: ToolResult)
@dataclass NeedsApproval(tool_call_id, tool_name, arguments)
@dataclass Denied(result: ToolResult)

class ToolExecutor:
    def __init__(self, registry, policy, *, timeout=120.0)
    async def run(self, tool_call_id, tool_name, arguments, *, approved=None) -> Outcome
        # 1. Look up tool in registry
        # 2. Check policy → DENY returns Denied, CONFIRM without approval returns NeedsApproval
        # 3. Execute with asyncio.wait_for(timeout)
        # 4. Catch exceptions → Completed(ToolResult.fail(...))
        # 5. Add duration_ms to result.metadata
```

---

### `taui/tools/builtins/` — Built-in Tools

#### `common.py` — Shared Utilities

```python
SKIP_DIRS: frozenset[str]
    # .git, __pycache__, node_modules, .venv, venv, .tox, .mypy_cache,
    # .pytest_cache, .ruff_cache, dist, build, .egg-info

def resolve_path(working_dir: Path, raw: str) -> Path
    # Expands ~, resolves relative to working_dir, rejects paths outside workspace

def is_binary(path: Path, sample_size=8192) -> bool
    # Null bytes or >30% non-printable → binary

def suggest_similar(path: Path, working_dir: Path, n=5) -> str | None
    # difflib.get_close_matches on siblings → "Did you mean: ..."

def truncate(text: str, *, max_lines=2000, max_bytes=50_000) -> tuple[str, bool]
    # Never splits mid-line. Returns (truncated_text, was_truncated)
```

#### `files.py` — File Tools

All tools are `@dataclass` with `working_dir: Path` and `guidelines: str`.

| Tool | Name | Category | Key behavior |
|------|------|----------|-------------|
| `ReadTool` | `read` | FILE_READ | Numbered lines, offset/limit pagination, dir listing, "did you mean?" on missing |
| `WriteTool` | `write` | FILE_WRITE | Atomic write (tempfile+rename), creates parent dirs |
| `GlobTool` | `glob` | SEARCH | Pattern match, mtime sort, SKIP_DIRS filter, 200 match cap |
| `GrepTool` | `grep` | SEARCH | Regex search, include filter, 500 match cap, binary skip |

#### `edit.py` — Edit Tool

```python
class EditTool:
    name = "edit"
    category = FILE_WRITE

    schema:
        path: str
        edits: [{old_text: str, new_text: str}, ...]

    async def execute(arguments) -> ToolResult
```

**Fuzzy matching chain** (tried in order, first unique match wins):
1. Exact string match
2. Unicode normalization (smart quotes → straight, em dashes → hyphens, etc.)
3. Whitespace normalization (strip trailing whitespace per line)
4. Indentation-flexible (textwrap.dedent both sides)

**Multi-edit**: All edits are matched against original content first.
Overlapping edits are rejected. Applied in reverse position order so
offsets stay stable. Atomic write via tempfile+rename.

**Per-file locking**: `asyncio.Lock` per path prevents concurrent edits
to the same file. Different files can be edited in parallel.

**Output**: Returns unified diff of changes + metadata
(`edits_applied`, `strategies` used).

#### `bash.py` — Shell Tool

```python
class BashTool:
    name = "bash"
    category = SHELL
    # Filtered env (allowlist only), process group isolation,
    # SIGTERM→SIGKILL timeout escalation, output truncation via common.truncate()
```

#### `git.py` — Git Operations

```python
class GitTool:
    name = "git"
    category = GIT
    # Read ops: status, diff, log, show, blame, branch_list, branch_current, stash_list
    # Write ops: commit, add, checkout, stash_push, stash_pop
    # All operations via asyncio subprocess with 30s timeout and 50KB output limit
    # Takes operation: str + args: dict — dispatches to per-op handlers
```

#### `question.py` — User Clarification

```python
class QuestionTool:
    name = "question"
    category = QUESTION
    # Parameters: question (required), options (optional list)
    # Uses _ask callback: async (question, options) -> answer | None
    # CLI wires _ask to interactive prompt. Returns "best judgment" if no callback.
```

#### `memory.py` — Cross-Session Knowledge

```python
class MemoryTool:
    name = "memory"
    category = MEMORY
    # Operations: save, read, list, delete
    # Stores entries as .md files in .taui/memory/ within the workspace
    # Path traversal prevention via key sanitization
    # Keys are simple names (e.g. "build-commands", "architecture-notes")
```

#### `__init__.py`

```python
def register_builtins(registry: ToolRegistry) -> None
    # Registers: ReadTool, WriteTool, EditTool, GlobTool, GrepTool,
    #            BashTool, GitTool, MemoryTool, QuestionTool
```

---

### `taui/cost.py` — Cost Tracker

```python
def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float
    # Pricing table lookup (exact → prefix → default)

@dataclass
class TurnRecord:
    model: str; input_tokens: int; output_tokens: int; cost_usd: float; timestamp: float

@dataclass
class CostTracker:
    def record(*, model, input_tokens, output_tokens, cost_usd=None) -> TurnRecord
    def summary() -> str          # "tokens: 1,000in / 500out | cost: $0.0120 | turns: 2"
    def to_dict() -> dict
    # Running totals: total_input_tokens, total_output_tokens, total_cost_usd, turn_count
```

**Integration**: `Session.send()` records cost from each turn's usage data.
CLI displays cumulative cost in the turn summary. `/cost` command shows full summary.

---

### `taui/commands/` — Slash Commands

```python
# registry.py
@dataclass
class CommandContext:
    raw_input: str; args: list[str]; extras: dict

@dataclass
class CommandResult:
    output: str; error: bool; metadata: dict
    @classmethod ok(output, **metadata); fail(output, **metadata)

class SlashCommand(Protocol):
    name: str; description: str
    async def execute(ctx: CommandContext) -> CommandResult

class CommandRegistry:
    def register(command: SlashCommand)
    def alias(alias: str, command_name: str)
    def get(name: str) -> SlashCommand | None
    async def execute(raw_input: str) -> CommandResult
    def help_text() -> str

# builtins.py — HelpCommand, CostCommand, CompactCommand, ClearCommand, ModelCommand
def register_builtins(registry, *, get_session=None, get_tracker=None)
    # Aliases: /h → /help, /? → /help
```

**CLI integration**: `Repl._build_commands()` creates the registry with lambdas
for session/tracker access. `/quit` and `/exit` are handled directly in the REPL
loop before command dispatch.

---

### `taui/prompt_builder.py` — System Prompt Construction

Template-based prompt builder. The system prompt is a single template string
with `{variable}` placeholders substituted at render time.

```python
DEFAULT_TEMPLATE = """
You are an expert coding assistant operating inside taui, a coding agent
harness. You help users by reading files, executing commands, editing code,
and writing new files.
# Available tools
{tools}
# Guidelines
{guidelines}
# Environment
- Working directory: {cwd}
- Date: {date}
- Platform: {platform}
{git_status}{project_instructions}
"""

def render_template(template: str, variables: dict[str, str]) -> str
    # Simple {key} → value substitution. Unknown vars left as-is.

class SystemPromptBuilder:
    def __init__(*, template=None, max_total_tokens=None)
    def with_project_context(ctx) -> self     # Injects cwd, date, git, instructions
    def with_tools(registry) -> self          # Builds tool snippets + adaptive guidelines
    def with_tool_names(names) -> self        # Simple comma-separated {tools}
    def set(key, value) -> self               # Sets any {variable}
    def add_section(key, content, ...) -> self # Priority-managed extra section
    def append(section: str) -> self          # Raw text after everything
    def remove_section(key: str) -> self
    def build() -> list[str]
    def render() -> str
```

**Template variables**: `{tools}`, `{guidelines}`, `{cwd}`, `{date}`,
`{platform}`, `{git_status}`, `{project_instructions}`.

**Tool snippets**: `with_tools(registry)` generates `- name: description` lines.

**Adaptive guidelines**: Built from `_build_guidelines(registry)` — core rules +
tool-aware rules (e.g. "prefer grep over bash") + per-tool guidelines + safety.

**Custom template**: Place `.taui/system_prompt.md` in project root to override.

**Integration**: `Session.create()` builds prompt via
`SystemPromptBuilder().with_project_context(ctx).with_tools(registry).render()`.

See `docs/system-prompt.md` for full documentation.

---

### `taui/llm_provider/` — LLM Provider Layer

#### `types.py` — Shared Types

```python
ProviderToolCall(call_id, name, arguments: dict)
    .to_chat_completions_format() -> dict   # OpenAI Chat Completions tool_call
    .to_responses_format() -> dict          # OpenAI Responses function_call

ProviderTurnResult(response_id, text, tool_calls: list[ProviderToolCall],
                   usage: Usage | None, assistant_metadata, stop_reason)
    .has_tool_calls -> bool

Usage(input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
      reasoning_tokens, cost_usd)
    .total_tokens -> int

StreamEvent(type, delta, tool_call, tool_call_index, tool_call_name,
            usage, reasoning_text, error_message)
    # Factory methods: .text_delta(), .reasoning_delta(), .tool_call_start(),
    #   .tool_call_delta(), .tool_call_done(), .usage_event(), .done(), .error()

ProviderCapabilities(supports_tools, supports_streaming, supports_reasoning,
                     supports_images, reasoning_format, tool_call_id_format, ...)

LLMRequest(url, headers, body)   # HTTP request descriptor
```

#### `base.py` — Abstract Base

```python
class BaseLLMProvider(ABC):
    api_format: ApiFormat  # "chat_completions" | "responses" | "messages" | "genai"

    # Abstract:
    @property capabilities -> ProviderCapabilities
    def build_request(messages, model, temperature, *, tools, **kwargs) -> LLMRequest
    def parse_stream_event(data: str) -> StreamEvent | None
    def refresh_credentials() -> None

    # Overridable:
    def convert_tools(tools) -> list[dict]       # Default: passthrough
    def convert_messages(messages) -> list[dict]  # Default: passthrough
    def is_context_overflow(status, body) -> bool
    def is_usage_limit(status, body) -> bool
    def is_retryable(status, body) -> bool

    # Public API:
    async def create_turn(messages, model, *, tools, temperature=0.1,
                          previous_response_id, thinking_level, **kwargs) -> ProviderTurnResult
        # 1. refresh_credentials()
        # 2. convert_tools() if tools
        # 3. build_request()
        # 4. _stream_turn_with_retry()

    async def stream_text(messages, model, temperature) -> AsyncIterator[StreamEvent]

    # Internal:
    async def _stream_turn_with_retry(req) -> ProviderTurnResult
        # MAX_RETRIES=3, exponential backoff, Retry-After header respect
    async def _accumulate_turn(req) -> ProviderTurnResult
    async def _do_stream(req) -> AsyncIterator[StreamEvent]  # SSE parsing loop
```

#### `auth/` — Credential Management

```python
# auth/__init__.py
def get_credentials(provider: str)   # "copilot" → CopilotCredentials, "codex" → CodexCredentials

# auth/copilot.py — GitHub Copilot OAuth device flow
CopilotCredentials(github_token, copilot_token, expires_at_ms, enterprise_domain)
def login() -> CopilotCredentials          # Interactive device flow
def get_copilot_credentials() -> CopilotCredentials   # Load from config or trigger login
def ensure_valid_token(credentials)        # Refresh if expired (5 min buffer)

# auth/codex.py — OpenAI Codex PKCE flow
CodexCredentials(access_token, refresh_token, expires_at_ms, account_id)
def login() -> CodexCredentials            # PKCE flow with local callback server
def get_codex_credentials() -> CodexCredentials
def ensure_valid_token(credentials)
```

#### `providers/` — Concrete Providers

```python
# CopilotProvider (api_format="chat_completions")
#   - build_request() → OpenAI Chat Completions format
#   - parse_stream_event() → handles content, reasoning_text, tool_calls
#   - Capabilities: tools=True, streaming=True, reasoning=True (OPAQUE)

# CodexProvider (api_format="responses")
#   - build_request() → OpenAI Responses API format
#   - parse_stream_event() → handles response.output_text.delta, function_call, etc.
#   - Capabilities: tools=True, streaming=True, reasoning=True (ENCRYPTED)
#   - Supports previous_response_id for multi-turn reasoning
```

#### `config.py` — TOML Persistence

```python
CONFIG_PATH = ~/.config/taui/config.toml

def load_config() -> dict                              # Full TOML parse
def save_provider_config(provider: str, data: dict)    # Merge into [providers.<name>]
def load_provider_config(provider: str) -> dict | None
```

---

## Key Design Patterns

### Duck-typed LLM

`AgentLoop` does not import `BaseLLMProvider`. It accepts `llm: Any` and
calls `llm.create_turn(messages, model, tools=schemas)`. This means tests
can inject a plain class with just a `create_turn` method — no ABC ceremony.

### Protocol-based Tools

`Tool` is a `typing.Protocol`, not an ABC. Any object with `name`,
`description`, `schema`, `category`, and `async execute()` satisfies it.
Builtins use `@dataclass` but custom tools can be anything.

### Callback Hooks

The agent loop's `on_tool_call`, `on_tool_result`, `on_approval`, and
`on_text` are optional async callables set as instance attributes.
Frontends wire them after construction — the loop doesn't know or care
what frontend is attached. The CLI sets them in `Repl._wire_callbacks()`.

### Atomic File Writes

Both `WriteTool` and `EditTool` write to a tempfile in the same directory,
then `Path.replace()` to the target. This prevents partial writes from
corrupting files on crash.

### Fuzzy Edit Matching

`EditTool` tries four matching strategies in order. This compensates for
LLM imprecision (smart quotes, whitespace drift, indentation differences)
without sacrificing safety — every match must be unique.

### Composition Root Pattern

`Session.create()` is the composition root. It constructs all components
and wires them together. Tests bypass `create()` and inject components
directly via the `Session(...)` constructor. This keeps production wiring
and test wiring completely separate.

### Event Sourcing via Store

Every agent action is appended to an SQLite event log. This provides:
- Full audit trail of every conversation
- Inter-process communication (frontends read events from the store)
- Reconnect capability (read from last-seen offset)
- Diagnostics and cost tracking

---

## Test Structure

```
tests/
├── test_agent.py         # AgentLoop: simple responses, tool calls, max turns, errors
├── test_builtins.py      # ReadTool, WriteTool, GlobTool, GrepTool, BashTool, GitTool, MemoryTool, QuestionTool, register_builtins
├── test_cli.py           # parse_args
├── test_common.py        # resolve_path, is_binary, suggest_similar, truncate, SKIP_DIRS
├── test_config.py        # Config defaults, overrides, load
├── test_edit.py          # EditTool: exact/fuzzy/multi-edit, overlap, errors, find_match
├── test_session.py       # Session wiring with mock provider, multi-message, close
├── test_store.py         # Store lifecycle, CRUD, append, read, live-tail, StreamClient
├── test_commands.py      # CommandRegistry, built-in commands
├── test_context.py       # Compaction: compact_messages, token estimation
├── test_cost.py          # CostTracker, estimate_cost
├── test_git.py           # GitTool operations
├── test_memory.py        # MemoryTool: save/read/list/delete, path traversal
├── test_prompt_builder.py # SystemPromptBuilder, instruction discovery, budget fit
├── test_question.py      # QuestionTool with mock callbacks
└── test_tools.py         # ToolRegistry, ToolPolicy, ToolExecutor with mock tools
```

All tests use `pytest` with `asyncio_mode = "auto"`. No external services
required — LLM providers are mocked. Run with `python -m pytest tests/ -v`.

---

## Adding a New Tool

1. Create a `@dataclass` class implementing the `Tool` protocol:
   - `name`, `description`, `schema` (JSON Schema), `category` (ToolCategory)
   - `async execute(self, arguments: dict) -> ToolResult`
   - Optional: `working_dir: Path`, `guidelines: str`

2. Register it in `builtins/__init__.py` `register_builtins()`.

3. Write tests in `tests/test_<toolname>.py`.

4. If the tool needs approval by default, set its policy in `ToolPolicy._DEFAULTS`.

---

## Adding a New Provider

1. Subclass `BaseLLMProvider` in `llm_provider/providers/<name>.py`.
   Implement: `capabilities`, `build_request()`, `parse_stream_event()`,
   `refresh_credentials()`.

2. Add credentials class and auth flow in `llm_provider/auth/<name>.py`.

3. Register in `llm_provider/auth/__init__.py` `get_credentials()`.

4. Register in `session.py` `_create_provider()`.

5. Add to CLI `parse_args()` choices.

---

## Configuration Files

| File | Purpose |
|------|---------|
| `~/.config/taui/config.toml` | Credentials + user preferences |
| `<workspace>/.taui/store.db` | SQLite event log for this workspace |
| `pyproject.toml` | Package config, dependencies, ruff, pytest |

### config.toml structure

```toml
[taui]
provider = "copilot"
model = "claude-sonnet-4-20250514"
max_turns = 50

[providers.copilot]
github_token = "gho_..."

[providers.codex]
refresh_token = "..."
account_id = "..."
```

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `aiosqlite` | ≥0.20 | Async SQLite with WAL mode |
| `httpx` | ≥0.28 | HTTP client for LLM provider APIs |
| Python | ≥3.13 | match statements, `Path` improvements |

No CLI framework (no click, no typer) — just `argparse` from stdlib.
No prompt toolkit — just `input()`. Minimal dependency surface.
