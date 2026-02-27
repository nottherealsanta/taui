# taui Architecture Plan

## Design Philosophy

Minimal core, maximal composability. Ship a lean harness with a small built-in toolset and a clean system prompt. Keep primitives independently usable (`taui.llm` without TUI, `taui.tools` without agent loop, etc.).

## Module Structure

```text
taui/
├── __init__.py
├── __main__.py            # entry point
├── app.py                 # Textual TUI
├── cli.py                 # headless CLI mode (stdin/stdout)
│
├── config/                # configuration layer
│   ├── __init__.py
│   ├── settings.py        # global config, model selection, API keys
│   └── policies.py        # permission rules (confirm/deny for tools)
│
├── llm/                   # LLM client abstraction
│   ├── __init__.py
│   ├── types.py           # Message, ToolCall, StreamEvent, Usage, etc.
│   ├── provider.py        # Provider protocol (ABC)
│   ├── registry.py        # model registry + provider routing
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── openai.py      # OpenAI / Codex
│   │   └── copilot.py     # GitHub Copilot SDK
│   └── stream.py          # async streaming helpers, cancellation
│
├── tools/                 # tool system
│   ├── __init__.py
│   ├── base.py            # Tool protocol, schema, ToolResult
│   ├── registry.py        # tool registry + discovery
│   ├── executor.py        # validation, execution, timeout, error handling
│   └── builtins/          # built-in tools
│       ├── __init__.py
│       ├── read.py        # read file
│       ├── write.py       # write file (requires prior read)
│       ├── edit.py        # patch/replace in file
│       ├── bash.py        # shell execution (sandboxed)
│       ├── glob.py        # file pattern search
│       └── grep.py        # content search
│
├── agent/                 # agent loop / orchestrator
│   ├── __init__.py
│   ├── loop.py            # think → act → observe cycle
│   ├── session.py         # session state, message history, persistence
│   └── events.py          # token/tool/error/done event types
│
└── skills/                # on-demand capability packages
    ├── __init__.py
    ├── loader.py          # load/activate skills
    └── builtins/          # shipped skills
        └── __init__.py
```

## Primitive 1: `taui.llm` (LLM Client)

### Core Types (`llm/types.py`)

```python
@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

@dataclass
class StreamEvent:
    type: Literal["text_delta", "tool_call_delta", "tool_call_done", "done", "error"]
    delta: str | None = None
    tool_call: ToolCall | None = None
    usage: Usage | None = None

@dataclass
class Usage:
    input_tokens: int
    output_tokens: int
    cost_usd: float | None = None
```

### Provider Protocol (`llm/provider.py`)

```python
class Provider(Protocol):
    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a completion. Batch mode can be built by collecting all events."""
        ...

    def supports(self, capability: str) -> bool:
        """Examples: tool_calling, vision, json_mode."""
        ...
```

### Decisions

- Streaming-first (`AsyncIterator[StreamEvent]`), no separate batch path.
- `llm/registry.py` routes models to providers (`openai:*`, `copilot:*`).
- Usage tracking included from day one.
- Cancellation via normal `asyncio` task cancellation.

## Primitive 2: `taui.tools` (Tool System)

### Tool Contract (`tools/base.py`)

```python
class Tool(Protocol):
    name: str
    description: str
    schema: dict[str, Any]

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        ...

@dataclass
class ToolResult:
    content: str
    error: bool = False
    metadata: dict[str, Any] | None = None

@dataclass
class ToolContext:
    working_dir: Path
    session: "Session"
    policy: "Policy"
```

### Engine

- `tools/registry.py`: register, lookup, schema export.
- `tools/executor.py`: schema validation, policy checks, timeout handling, normalized errors, and tool events.

### Built-ins (MVP)

- `read`
- `edit`
- `write`
- `bash`
- `glob`
- `grep`

## Primitive 3: `taui.agent` (Agent Loop)

### Loop (`agent/loop.py`)

```python
async def run(session: Session, provider: Provider, tools: ToolRegistry, system_prompt: str) -> AsyncIterator[AgentEvent]:
    while True:
        async for event in provider.complete(messages=session.messages, tools=tools.list_schemas()):
            yield event
            if event.type == "tool_call_done":
                result = await executor.run(event.tool_call, context)
                session.add_tool_result(event.tool_call.id, result)
                yield ToolResultEvent(result)

        if not last_response_had_tool_calls:
            break
```

### Session and Events

- `agent/session.py`: message history, read-tracking, persistence (`~/.local/share/taui/sessions/`), token budget tracking.
- `agent/events.py`: `TextDelta`, `ToolStart`, `ToolEnd`, `TurnComplete`, `Error`, `Done`.

Both TUI and headless CLI should consume the same `AsyncIterator[AgentEvent]`.

## Primitive 4: Edit-after-Read Guard

`tools/builtins/edit.py` enforces read-before-edit:

```python
if not context.session.has_read(path):
    return ToolResult(content=f"Error: must read {path} before editing it.", error=True)
```

Edit behavior:

- Exact `old_string` match required.
- Clear error if no match.
- Conflict detection for ambiguous/multiple replacements (as configured).

## Primitive 5: `taui.skills`

```python
@dataclass
class Skill:
    name: str
    description: str
    instructions: str
    tools: list[Tool] | None
    when: str | None
```

- Skills loaded from `~/.config/taui/skills/` and `taui/skills/builtins/`.
- Loader activates matching skills and injects skill instructions/tools into the turn context.

## Primitive 6: Config and Permissions

`~/.config/taui/config.toml`:

```toml
[model]
default = "openai:codex-mini"

[providers.openai]
api_key_env = "OPENAI_API_KEY"

[providers.copilot]
# Uses GitHub auth/token source

[policy]
auto_approve = ["read", "glob", "grep"]
confirm = ["edit", "write", "bash"]
deny = []
```

## Interface Modes

- Primary interfaces: Textual TUI + headless CLI.
- Both run against the same core agent/event pipeline.

## Extensibility Direction

Future install workflow target:

- `taui install <tool>/<git_url>`

Initial packaging direction can be either:

- Python entry-point plugins, or
- file-based drop-ins under `~/.config/taui/extensions/`.

## Implementation Order

1. `llm/types.py`, `llm/provider.py`, `llm/providers/openai.py`
2. `tools/base.py`, `tools/registry.py`, `tools/executor.py`
3. Built-in tools: `read`, `edit`, `write`, `bash`, `glob`, `grep`
4. `agent/loop.py`, `agent/session.py`, `agent/events.py`
5. `cli.py` (headless mode)
6. `app.py` integration (Textual TUI)
7. `config/` settings + policy enforcement
8. `skills/` loader + built-in skills
9. `llm/providers/copilot.py`

## Known Follow-ups

- Decide prompt strategy (minimal default prompt vs fuller policy prompt).
- Finalize plugin package contract for `taui install`.
- Decide whether session tree/branching is MVP or post-MVP.
