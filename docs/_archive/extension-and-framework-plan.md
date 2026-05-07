# Taui: Extension & Framework Plan

Taui is a framework for building coding harnesses. It ships as a minimal harness you can use directly, but the real point is that every component — tools, commands, prompts, hooks, UI, providers, store — is a composable piece you can swap, extend, or replace. Extensions aren't an afterthought bolted onto the side. They're how taui itself is built.

There are two ways to use taui:

1. **Write extensions** — drop `.py` files into `.taui/extensions/`. Add tools, commands, hooks, prompt overrides. The agent can do this for you via `/i`. No fork, no build step, no package manager. This is the fast path.

2. **Build a new harness** — import taui's components as a library. Wire your own session, pick which tools to register, write your own CLI or UI, swap the LLM provider. Taui gives you the agent loop, tool executor, store, config, and extension loader as building blocks. You build the harness.

---

## Core Thesis

Most coding harnesses are closed. You use them as-is or you fork. Taui is open by design: the default app is just one arrangement of the underlying framework components. Extensions use the same APIs as the builtins. There's no privileged internal surface that extensions can't reach.

The goal: **any team can build their own harness — either by extending taui or by using it as a base**.

---

## Current State (Codebase Audit)

This section captures **what exists today** and **what's broken or tightly coupled**, based on an audit of every module. Everything in this plan flows from these findings.

### What Works

| Component | Module | Status |
|-----------|--------|--------|
| Agent Loop | `taui.agent.loop` | Working. think → tool → observe cycle. |
| Tool Protocol | `taui.tools.base` | Clean Protocol class. `Tool`, `ToolResult`, `ToolCategory`. |
| Tool Registry | `taui.tools.registry` | Working. `register()`, `get()`, `schemas()`, `subset()`. |
| Tool Executor | `taui.tools.executor` | Working. Policy-gated dispatch with timeout. |
| Extension Loader | `taui.extensions` | Working. Discovers `.py` files, calls `register(tools, commands, hooks)`. |
| Hook System | `taui.hooks` | Working. `run()`, `collect()`, `transform()`, `first()`. |
| Store | `taui.store` | Working. Append-only SQLite, WAL mode, streams. |
| Config | `taui.config` | Basic. TOML file + CLI overrides. |
| Prompt Builder | `taui.prompt_builder` | Working. Template rendering with variable substitution. |
| CLI | `taui.cli` | Working. prompt-toolkit REPL. |
| Cost Tracking | `taui.cost` | Working. Per-turn token accounting. |
| Skills | `taui.skills` | Working. Markdown skill discovery + injection. |
| MCP | `taui.mcp` | Working. Server discovery + tool export. |

### What's Broken for Extensibility

These are the concrete problems that block taui from being a clean extensible framework:

#### 1. No public API surface

`taui/__init__.py` is empty (just a docstring). There's no `__all__`, no re-exports. Consumers must know the internal module structure:

```python
# Today: consumer must know internal paths
from taui.agent.loop import AgentLoop
from taui.tools.base import Tool, ToolResult
from taui.tools.registry import ToolRegistry
from taui.store.store import Store
```

#### 2. Provider creation is hardcoded

`session.py` has a `match config.provider:` block that only handles `"copilot"` and `"codex"`. Adding a third provider requires editing core taui code:

```python
# session.py — hardcoded
match config.provider:
    case "copilot": return CopilotProvider(credentials=creds)
    case "codex":   return CodexProvider(credentials=creds)
    case _:         raise ValueError(...)
```

#### 3. Session.create() is a monolith

`Session.create()` is ~100 lines that hardwires every dependency. Sub-agent tool gets `_llm`, `_stream`, `_parent_executor`, `_model` injected via attribute assignment. Skills tool gets `_skill_registry` and `_inject_message`. MCP tool gets `_manager`. None of this is configurable from outside.

#### 4. Store backend is not pluggable

The `Store` class is a concrete SQLite implementation. There's no abstract interface. A consumer who wants PostgreSQL or in-memory storage must replace the entire class and hope the API surface matches.

#### 5. Tool wiring requires private attribute injection

Built-in tools that need shared state (SubAgentTool, SkillsTool, McpTool) receive it via private attribute assignment after construction. This is undocumented and fragile:

```python
sub_agent._llm = provider           # private attr injection
sub_agent._stream = stream
skills_tool._skill_registry = skill_registry
skills_tool._inject_message = inject_skill_message
mcp_tool._manager = mcp_manager
```

#### 6. Config is underspecified

`Config` doesn't expose: tool policies (beyond `auto_approve_reads`), extension paths, store path, prompt template paths, or provider-specific settings. Teams can't configure taui without editing code.

#### 7. Hook signatures are not enforced

Hooks are registered by name string. The signature contract (`(session) → str` vs `(value, session) → value` vs `(..., session) → None`) is documented but not checked at registration time. A broken hook silently fails or corrupts data.

#### 8. No provider registry

Unlike tools and commands which have registries, LLM providers are just classes imported directly. There's no `ProviderRegistry.register()`, no discovery, no way for an extension to add a provider.

#### 9. Commands aren't wired through extensions

`Session.create()` passes `commands=None` to `ext_registry.load_all()`. Extensions can technically register commands, but the session doesn't wire a command registry. The CLI creates its own command registry separately.

---

## The Framework

Taui's components are designed to be used independently or composed together. When you run `taui` out of the box, it wires all of these together for you. When you build a custom harness, you pick what you need.

### Core Components

| Component | Module | What It Does |
|-----------|--------|-------------|
| **Agent Loop** | `taui.agent.loop` | think → tool → observe cycle. Drives the conversation. |
| **Tool Registry** | `taui.tools.registry` | Register tools, look them up by name, generate schemas for the LLM. |
| **Tool Executor** | `taui.tools.executor` | Execute tool calls with policy enforcement (auto/confirm/deny). |
| **Store** | `taui.store` | Append-only event log. Pluggable backend (SQLite default). |
| **Config** | `taui.config` | Layered config: file → env → CLI args. |
| **Extension Loader** | `taui.extensions` | Discover, load, isolate `.py` extension files. |
| **Hook Registry** | `taui.hooks` | UI hooks, pipeline hooks, observer hooks, override hooks. |
| **Session** | `taui.session` | Wires provider + tools + loop + store together. The unit of interactive use. |
| **LLM Providers** | `taui.llm_provider` | Pluggable providers with registry. Copilot and Codex built-in. |
| **Prompt Builder** | `taui.prompt_builder` | Assembles system prompts from project context, tools, and extensions. |

### Builtin Tools (Part of the Framework)

The default tool surface ships as part of the framework: `read`, `write`, `edit`, `bash`, `glob`, `grep`, `ls`, `sub_agent`, `question`, `memory`, `skills`, `mcp`. These are registered by `taui.tools.builtins.register_builtins()` — the same function extensions use to register their own tools. They can be disabled, overridden, or replaced.

### Builtin Commands (Part of the Framework)

`/help`, `/cost`, `/compact`, `/clear`, `/model`, `/i`, `/sessions`, `/new`, `/reload`, `/extensions`. Registered by `taui.commands.builtins.register_builtins()`. Same pattern.

### Interfaces (Choose or Build Your Own)

- **CLI** — prompt-toolkit REPL. Default when you run `taui`.
- **TUI** — Textual terminal UI. `taui --tui`.
- **Web** — FastAPI + Svelte. `taui --web`.

All three are thin layers over the same Session. A custom harness can replace them entirely — import `Session`, call `session.send()`, render the result however you want.

---

## Two Paths to Customization

### Path 1: Extensions

Extensions are `.py` files in `~/.taui/extensions/` (global) or `.taui/extensions/` (project). Each has a `register(tools, commands, hooks)` entry point. The agent can create them via `/i`, or you write them by hand.

Extensions use the same APIs as builtins. A tool extension is structurally identical to a builtin tool. A hook extension registers hooks the same way the core does.

| Extension Type | Mechanism | Example |
|----------------|-----------|---------|
| **Tool** | `tools.register(MyTool())` | JIRA lookup, deploy, custom search |
| **Command** | `commands.register(MyCommand())` | `/deploy`, `/lint`, `/review` |
| **Hook: UI** | `hooks.prompt()`, `hooks.banner()`, `hooks.status()`, `hooks.turn_summary()` | Custom prompt, status bar segments |
| **Hook: Pipeline** | `hooks.before_send()`, `hooks.after_result()`, `hooks.system_prompt()` | Input preprocessing, output filtering, prompt injection |
| **Hook: Observer** | `hooks.on_tool_call()`, `hooks.on_tool_result()`, `hooks.on_session_start()` | Logging, metrics, audit |
| **Hook: Override** | `hooks.on_approval()` | Auto-approve/deny tools per policy |
| **Prompt Override** | `hooks.system_prompt(lambda p, s: p + "\nExtra instructions.")` | Domain-specific agent behavior |
| **Provider** | `providers.register("my_provider", MyProvider)` | Custom LLM backend |

Extensions are isolated (broken ones don't crash the core), hot-reloadable (`/reload`), and scopable (project overrides global).

### Path 2: Build a Harness

Import taui as a library and wire your own harness. You get full control over what's included and how it's wired.

```python
import taui

async def main():
    config = taui.Config.load()
    provider = taui.CopilotProvider(credentials=taui.get_credentials("copilot"))

    # Pick your tools — use builtins, add your own, or start from scratch
    registry = taui.ToolRegistry()
    taui.register_builtins(registry)
    registry.register(MyCustomTool())

    executor = taui.ToolExecutor(registry=registry, policy=taui.ToolPolicy())
    store = taui.Store(config.working_dir)
    await store.connect()
    stream = taui.StreamClient(store)

    # Build your prompt
    builder = taui.SystemPromptBuilder()
    builder.with_project_context(taui.ProjectContext.discover(config.working_dir))
    builder.with_tools(registry)

    loop = taui.AgentLoop(
        llm=provider,
        executor=executor,
        stream=stream,
        system_prompt=builder.render(),
        model=config.model,
    )

    # Your harness, your interface
    result = await loop.run("What files are in src/?")
    print(result.text)
```

This is not a toy example. `Session.create()` does exactly this wiring internally. A custom harness just does it differently — different tools, different prompt, different UI, different policies.

---

## Extension Scoping

| Scope | Path | When It Applies |
|-------|------|-----------------|
| Global | `~/.taui/extensions/` | Every workspace |
| Project | `.taui/extensions/` | This workspace only |

Project overrides global when names collide. Check `.taui/` into git and every developer on the project gets the same harness.

```
.taui/
├── config.toml        # provider, model, tool policies
├── extensions/
│   ├── deploy.py      # /deploy command + deploy tool
│   ├── policy.py      # auto-approve reads, confirm writes
│   ├── prompt.py      # team-specific system prompt additions
│   └── ci_hooks.py    # observer hooks for CI integration
└── skills/
    └── review.md      # code review skill context
```

### Configuration

```toml
[taui]
provider = "copilot"
model = "gpt-4.1"
max_turns = 25

[tools.policy]
bash = "confirm"
write = "confirm"
read = "auto"
```

### Skills vs Extensions

Skills add knowledge — they're context documents injected into the conversation. Extensions add behavior — they register tools, commands, and hooks. Both live under `.taui/`.

---

## Implementation Plan

### Phase 1: Clean Public API (Foundation)

**Goal:** Make `import taui` useful. Consumers shouldn't need to know internal module paths.

**Problem:** `taui/__init__.py` is empty. Every import requires knowing `taui.tools.base`, `taui.agent.loop`, `taui.store.store`, etc.

**Changes:**

1. **Export core types from `taui/__init__.py`:**

```python
# taui/__init__.py
from taui.agent.loop import AgentLoop, Message, RunResult
from taui.config import Config
from taui.cost import CostTracker
from taui.extensions import ExtensionRegistry
from taui.hooks import HookRegistry
from taui.llm_provider.auth import get_credentials
from taui.llm_provider.base import BaseLLMProvider
from taui.llm_provider.providers import CopilotProvider, CodexProvider
from taui.prompt_builder import ProjectContext, SystemPromptBuilder
from taui.session import Session
from taui.store.events import Event, EventType
from taui.store.store import Store
from taui.store.stream import StreamClient
from taui.tools.base import Tool, ToolResult, ToolCategory
from taui.tools.builtins import register_builtins
from taui.tools.executor import ToolExecutor, ToolPolicy
from taui.tools.registry import ToolRegistry

__all__ = [
    "AgentLoop", "Message", "RunResult",
    "Config",
    "CostTracker",
    "ExtensionRegistry",
    "HookRegistry",
    "get_credentials",
    "BaseLLMProvider", "CopilotProvider", "CodexProvider",
    "ProjectContext", "SystemPromptBuilder",
    "Session",
    "Event", "EventType", "Store", "StreamClient",
    "Tool", "ToolResult", "ToolCategory",
    "register_builtins",
    "ToolExecutor", "ToolPolicy", "ToolRegistry",
]
```

2. **Ensure each subpackage `__init__.py` exports its public types:**
   - `taui/store/__init__.py` → `Store`, `StreamClient`, `Event`, `EventType`
   - `taui/agent/__init__.py` → `AgentLoop`, `Message`, `RunResult`
   - `taui/llm_provider/__init__.py` → `BaseLLMProvider`, `ProviderRegistry`

3. **Rule: deep imports still work, but top-level is canonical.** `from taui import Tool` and `from taui.tools.base import Tool` both resolve to the same class.

**Files to change:**
- `taui/__init__.py` — add all exports
- `taui/store/__init__.py` — add exports if missing
- `taui/agent/__init__.py` — add exports if missing
- `taui/llm_provider/__init__.py` — add exports if missing

---

### Phase 2: Provider Registry

**Goal:** LLM providers are pluggable — extensions can register new providers, and `Session.create()` looks them up by name instead of hardcoding.

**Problem:** Only `"copilot"` and `"codex"` work. Adding a third provider requires editing `session.py`.

**Changes:**

1. **Create `ProviderRegistry`** in `taui/llm_provider/registry.py`:

```python
from taui.llm_provider.base import BaseLLMProvider

class ProviderRegistry:
    """Registry of LLM provider factories."""

    def __init__(self) -> None:
        self._factories: dict[str, type[BaseLLMProvider]] = {}

    def register(self, name: str, factory: type[BaseLLMProvider]) -> None:
        self._factories[name] = factory

    def get(self, name: str) -> type[BaseLLMProvider]:
        if name not in self._factories:
            raise ValueError(
                f"Unknown provider: {name!r}. "
                f"Available: {', '.join(sorted(self._factories))}"
            )
        return self._factories[name]

    @property
    def names(self) -> list[str]:
        return sorted(self._factories)

    def create(self, name: str, **kwargs) -> BaseLLMProvider:
        cls = self.get(name)
        return cls(**kwargs)
```

2. **Register built-in providers:**

```python
# taui/llm_provider/providers/__init__.py
_default_registry = ProviderRegistry()
_default_registry.register("copilot", CopilotProvider)
_default_registry.register("codex", CodexProvider)
```

3. **Update `session.py`** — replace `match config.provider:` with registry lookup:

```python
# Before (hardcoded)
match config.provider:
    case "copilot": return CopilotProvider(credentials=creds)
    case "codex":   return CodexProvider(credentials=creds)

# After (registry)
provider_cls = provider_registry.get(config.provider)
return provider_cls(credentials=creds)
```

4. **Extension API** — extensions can register providers:

```python
# .taui/extensions/ollama.py
from taui.llm_provider.base import BaseLLMProvider

class OllamaProvider(BaseLLMProvider):
    ...

def register(tools, commands, hooks):
    from taui.llm_provider.registry import default_registry
    default_registry.register("ollama", OllamaProvider)
```

**Files to change:**
- `taui/llm_provider/registry.py` — new file
- `taui/llm_provider/providers/__init__.py` — register defaults
- `taui/llm_provider/__init__.py` — export registry
- `taui/session.py` — use registry instead of match
- `taui/extensions/__init__.py` — pass provider registry to `register()` if needed

---

### Phase 3: Session Builder Pattern

**Goal:** Replace the monolithic `Session.create()` with a composable builder that consumers can customize at every step.

**Problem:** `Session.create()` makes all decisions — provider, tools, store, prompt — in one monolithic function. Consumers can't intervene.

**Changes:**

1. **Create `SessionBuilder`** in `taui/session.py`:

```python
class SessionBuilder:
    """Composable session assembly."""

    def __init__(self, config: Config | None = None) -> None:
        self._config = config or Config.load()
        self._provider = None
        self._registry = None
        self._executor = None
        self._store = None
        self._stream = None
        self._hooks = None
        self._prompt_builder = None
        self._skip_builtins = False
        self._extra_tools: list[Tool] = []
        self._tool_policies: dict[str, str] = {}

    def with_provider(self, provider: BaseLLMProvider) -> SessionBuilder:
        self._provider = provider
        return self

    def with_tools(self, registry: ToolRegistry) -> SessionBuilder:
        self._registry = registry
        return self

    def add_tool(self, tool: Tool) -> SessionBuilder:
        self._extra_tools.append(tool)
        return self

    def without_builtins(self) -> SessionBuilder:
        self._skip_builtins = True
        return self

    def with_store(self, store: Store) -> SessionBuilder:
        self._store = store
        return self

    def with_hooks(self, hooks: HookRegistry) -> SessionBuilder:
        self._hooks = hooks
        return self

    def with_policy(self, tool_name: str, decision: str) -> SessionBuilder:
        self._tool_policies[tool_name] = decision
        return self

    def with_prompt_builder(self, builder: SystemPromptBuilder) -> SessionBuilder:
        self._prompt_builder = builder
        return self

    async def build(self) -> Session:
        """Assemble and return a configured Session."""
        config = self._config

        # Provider — use provided or create from config
        provider = self._provider or _create_provider(config)

        # Tools — use provided or create default
        if self._registry:
            registry = self._registry
        else:
            registry = ToolRegistry()
            if not self._skip_builtins:
                register_builtins(registry)
                for name in registry.names:
                    tool = registry.get(name)
                    if hasattr(tool, "working_dir"):
                        tool.working_dir = config.working_dir

        for tool in self._extra_tools:
            registry.register(tool)

        # Policy
        policy = ToolPolicy()
        for name, decision in self._tool_policies.items():
            policy.set(name, decision)
        executor = ToolExecutor(registry=registry, policy=policy)

        # Store
        store = self._store or Store(config.working_dir)
        if not store._db:  # not yet connected
            await store.connect()
        stream = StreamClient(store)

        # Prompt
        builder = self._prompt_builder or SystemPromptBuilder()
        if not self._prompt_builder:
            try:
                ctx = ProjectContext.discover_with_git(config.working_dir)
            except Exception:
                ctx = ProjectContext.discover(config.working_dir)
            builder.with_project_context(ctx)
            builder.with_tools(registry)
        system_prompt = builder.render()

        # Wire complex tools ...
        _wire_builtins(registry, provider, stream, executor, config, system_prompt)

        # Extensions
        hooks = self._hooks or HookRegistry()
        ext_registry = ExtensionRegistry(config.working_dir)
        ext_registry.discover()
        ext_registry.load_all(tools=registry, commands=None, hooks=hooks)

        if hooks.has("system_prompt"):
            system_prompt = await hooks.transform("system_prompt", system_prompt, None)

        # Loop
        loop = AgentLoop(
            llm=provider,
            executor=executor,
            stream=stream,
            system_prompt=system_prompt,
            model=config.model,
            max_turns=config.max_turns,
        )

        return Session(
            config=config, provider=provider, registry=registry,
            executor=executor, store=store, stream=stream,
            loop=loop, ext_registry=ext_registry, hooks=hooks,
        )
```

2. **Keep `Session.create()` as a convenience** — it just calls `SessionBuilder().build()`.

3. **Consumer usage:**

```python
# Simple — same as today
session = await Session.create()

# Custom — override specific parts
session = await (
    SessionBuilder(config)
    .with_provider(my_ollama)
    .add_tool(DeployTool())
    .with_policy("bash", "confirm")
    .build()
)

# Minimal — no builtins, custom everything
session = await (
    SessionBuilder(config)
    .with_provider(my_provider)
    .with_tools(my_registry)
    .without_builtins()
    .build()
)
```

**Files to change:**
- `taui/session.py` — add `SessionBuilder`, refactor `Session.create()` to use it
- Extract `_wire_builtins()` helper for sub-agent/skills/mcp tool wiring

---

### Phase 4: Tool Wiring Protocol

**Goal:** Eliminate private attribute injection. Tools that need shared state declare their dependencies explicitly.

**Problem:** `SubAgentTool._llm = provider` is undocumented, fragile, and invisible to consumers.

**Changes:**

1. **Add optional `wire()` method to the Tool protocol:**

```python
class Tool(Protocol):
    name: str
    description: str
    schema: dict[str, Any]
    category: ToolCategory

    async def execute(self, arguments: dict) -> ToolResult: ...

    def wire(self, context: ToolContext) -> None:
        """Receive shared dependencies. Optional — not all tools need this."""
        ...
```

2. **Define `ToolContext`** — a typed bag of shared dependencies:

```python
@dataclass(slots=True)
class ToolContext:
    """Shared dependencies available to tools that need them."""
    working_dir: Path
    provider: BaseLLMProvider | None = None
    stream: StreamClient | None = None
    executor: ToolExecutor | None = None
    model: str = ""
    system_prompt: str = ""
    skill_registry: SkillRegistry | None = None
    mcp_manager: McpManager | None = None
    config: Config | None = None
```

3. **Tools opt-in** by implementing `wire()`:

```python
@dataclass
class SubAgentTool:
    name: str = "sub_agent"
    # ...

    def wire(self, ctx: ToolContext) -> None:
        self._llm = ctx.provider
        self._stream = ctx.stream
        self._parent_executor = ctx.executor
        self._model = ctx.model
```

4. **Session/Builder calls `wire()` once** after construction:

```python
ctx = ToolContext(working_dir=config.working_dir, provider=provider, ...)
for name in registry.names:
    tool = registry.get(name)
    if hasattr(tool, "wire"):
        tool.wire(ctx)
```

**Files to change:**
- `taui/tools/base.py` — add `ToolContext` dataclass
- `taui/tools/builtins/sub_agent.py` — add `wire()` method
- `taui/tools/builtins/skills.py` — add `wire()` method
- `taui/tools/builtins/mcp.py` — add `wire()` method
- `taui/session.py` — replace private attr injection with `wire()` calls

---

### Phase 5: Store Abstraction

**Goal:** Make the store backend pluggable so consumers can use PostgreSQL, in-memory, or custom backends.

**Problem:** `Store` is a concrete SQLite class. No interface exists.

**Changes:**

1. **Extract `StoreProtocol`** in `taui/store/base.py`:

```python
from typing import Protocol

class StoreProtocol(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def create_stream(self, stream_id: str, parent_id: str | None = None) -> None: ...
    async def append(self, stream_id: str, event_type: EventType, data: dict) -> int: ...
    async def read(self, stream_id: str, from_offset: int = 0, limit: int = 1000) -> list[Event]: ...
    async def close_stream(self, stream_id: str) -> None: ...
    async def stream_exists(self, stream_id: str) -> bool: ...
    async def create_session(self, session_id: str, **kwargs) -> None: ...
    async def get_session(self, session_id: str) -> dict | None: ...
    async def update_session(self, session_id: str, **kwargs) -> None: ...
    async def list_sessions(self) -> list[dict]: ...
```

2. **Rename current `Store` → `SqliteStore`**, keep `Store` as alias for backward compat.

3. **Add `InMemoryStore`** for testing and lightweight usage:

```python
class InMemoryStore:
    """In-memory store for testing and single-session use."""
    # implements StoreProtocol using plain dicts and lists
```

4. **Update `StreamClient`** to accept `StoreProtocol` instead of `Store`:

```python
class StreamClient:
    def __init__(self, store: StoreProtocol) -> None:
        ...
```

**Files to change:**
- `taui/store/base.py` — new file with `StoreProtocol`
- `taui/store/store.py` — rename class, add alias
- `taui/store/memory.py` — new file with `InMemoryStore`
- `taui/store/__init__.py` — export new types
- `taui/store/stream.py` — type hint update

---

### Phase 6: Config Expansion

**Goal:** Everything that's currently hardcoded becomes configurable via `.taui/config.toml`.

**Problem:** Tool policies, extension paths, store path, and provider settings aren't configurable without editing code.

**Changes:**

1. **Expand Config dataclass:**

```python
@dataclass
class Config:
    # Core
    provider: str = "copilot"
    model: str = ""
    max_turns: int = 50
    working_dir: Path = field(default_factory=Path.cwd)

    # System prompt
    system_prompt: str = ""
    instructions_files: list[str] = field(default_factory=lambda: [
        "AGENTS.md", ".taui/instructions.md", ".taui/AGENTS.md"
    ])

    # Tools
    auto_approve_reads: bool = True
    tool_policies: dict[str, str] = field(default_factory=dict)
    disabled_tools: list[str] = field(default_factory=list)

    # Store
    store_path: str = ".taui/store.db"
    store_backend: str = "sqlite"  # "sqlite" | "memory"

    # Extensions
    extension_dirs: list[str] = field(default_factory=lambda: [
        "~/.taui/extensions", ".taui/extensions"
    ])
    disabled_extensions: list[str] = field(default_factory=list)
    no_extensions: bool = False

    # Skills
    skill_dirs: list[str] = field(default_factory=lambda: [
        ".agents/skills", ".taui/skills"
    ])

    # Provider-specific
    provider_config: dict[str, Any] = field(default_factory=dict)
```

2. **TOML mapping:**

```toml
[taui]
provider = "copilot"
model = "gpt-4.1"
max_turns = 25
store_backend = "sqlite"
no_extensions = false
disabled_tools = ["bash"]

[taui.tool_policies]
bash = "confirm"
write = "confirm"
edit = "confirm"
read = "auto"
glob = "auto"

[taui.extension_dirs]
extra = ["~/shared-taui/extensions"]

[providers.copilot]
# provider-specific auth/config

[providers.ollama]
base_url = "http://localhost:11434"
```

3. **Environment variable override:** `TAUI_PROVIDER=ollama`, `TAUI_MODEL=llama3`, `TAUI_NO_EXTENSIONS=1`

**Files to change:**
- `taui/config.py` — expand dataclass, add env var reading, TOML section parsing
- `taui/session.py` — use new config fields
- `taui/extensions/__init__.py` — use config for discovery paths

---

### Phase 7: Wire Commands Through Session

**Goal:** Extensions can register slash commands that work in all interfaces (CLI, TUI, Web).

**Problem:** `Session.create()` passes `commands=None` to `ext_registry.load_all()`. The CLI creates its own command registry separately. Extension-registered commands only work if the CLI happens to pick them up.

**Changes:**

1. **Session owns a CommandRegistry:**

```python
class Session:
    def __init__(self, ..., commands: CommandRegistry | None = None):
        self.commands = commands or CommandRegistry()
```

2. **`Session.create()` registers builtins and passes to extensions:**

```python
commands = CommandRegistry()
register_builtin_commands(commands, session=session)
ext_registry.load_all(tools=registry, commands=commands, hooks=hooks)
```

3. **CLI/TUI/Web use `session.commands`** instead of creating their own:

```python
# CLI (before)
commands = CommandRegistry()
register_builtins(commands, ...)

# CLI (after)
commands = session.commands
```

4. **Extension `register()` signature** already supports commands — it just needs to be wired:

```python
def register(tools, commands, hooks):
    commands.register(MySlashCommand())  # Now actually works
```

**Files to change:**
- `taui/session.py` — add `CommandRegistry` ownership, wire through `create()`
- `taui/cli.py` — use `session.commands` instead of local registry
- `taui/tui.py` — same
- `taui/server/app.py` — same

---

### Phase 8: Extension Developer Experience

**Goal:** Make it easy for developers to write, test, and validate extensions.

**Changes:**

1. **Typed extension API** — publish `taui.ext` module:

```python
# taui/ext.py — stable types for extension authors
from taui.tools.base import Tool, ToolResult, ToolCategory, ToolContext
from taui.commands.registry import CommandContext, CommandResult
from taui.hooks import HookRegistry
from taui.tools.registry import ToolRegistry
from taui.commands.registry import CommandRegistry

# Type alias for the register function
RegisterFn = Callable[
    [ToolRegistry, CommandRegistry, HookRegistry],
    None,
]

# Re-export everything extension authors need
__all__ = [
    "Tool", "ToolResult", "ToolCategory", "ToolContext",
    "CommandContext", "CommandResult",
    "HookRegistry", "ToolRegistry", "CommandRegistry",
    "RegisterFn",
]
```

Extensions import from one place:
```python
from taui.ext import Tool, ToolResult, ToolCategory
```

2. **Extension templates** — `taui init-extension <type>`:

```bash
$ taui init-extension tool my_tool
Created .taui/extensions/my_tool.py

$ taui init-extension command deploy
Created .taui/extensions/deploy.py

$ taui init-extension hook metrics
Created .taui/extensions/metrics.py
```

Each template is a minimal working example with type hints and docstrings.

3. **Extension validation** — `taui validate-extension`:

```bash
$ taui validate-extension .taui/extensions/my_tool.py
✓ register() function found
✓ Signature: (tools, commands, hooks) — 3 params
✓ Tool "my_tool" has valid schema
✓ Tool "my_tool" has execute() method
✓ No import errors
```

Checks:
- `register()` exists and has correct signature
- Registered tools implement the `Tool` protocol
- Tool schemas are valid JSON Schema
- No import-time exceptions
- Commands implement `SlashCommand` protocol

4. **Extension testing harness:**

```python
# tests/test_my_extension.py
from taui.ext.testing import ExtensionTestHarness

async def test_my_tool():
    harness = ExtensionTestHarness()
    harness.load(".taui/extensions/my_tool.py")

    result = await harness.call_tool("my_tool", {"query": "test"})
    assert not result.error
    assert "expected" in result.content
```

**Files to create:**
- `taui/ext.py` — stable extension API surface
- `taui/ext/testing.py` — test harness for extensions
- `taui/commands/init_extension.py` — template scaffolding

---

### Phase 9: Harness Composition

**Goal:** Teams can compose multiple extension sets into a coherent harness with explicit configuration.

**Changes:**

1. **Extension groups** in `.taui/config.toml`:

```toml
[extensions]
# Load order matters — later extensions can override earlier ones
load_order = ["base_tools", "team_policy", "ci_hooks"]

[extensions.base_tools]
enabled = true

[extensions.team_policy]
enabled = true
config = { auto_approve_reads = true, deny_tools = ["bash"] }

[extensions.ci_hooks]
enabled = true
requires = ["base_tools"]
```

2. **Extension dependencies** — `requires` field:

```python
# deploy.py
EXTENSION_META = {
    "name": "deploy",
    "version": "1.0",
    "requires": ["ci_hooks"],
    "config_keys": ["deploy_target", "deploy_branch"],
}

def register(tools, commands, hooks):
    ...
```

3. **Extension config** — extensions can read their own config:

```python
def register(tools, commands, hooks):
    # Extension config from .taui/config.toml [extensions.deploy]
    config = hooks.extension_config("deploy")
    target = config.get("deploy_target", "staging")
```

4. **Harness inheritance** — global → team → project layering:

```
~/.taui/extensions/          # global (personal tools)
~/team-taui/extensions/      # team (shared via git)
.taui/extensions/            # project (repo-specific)
```

Config declares extra extension directories:
```toml
[taui]
extension_dirs = ["~/team-taui/extensions"]
```

**Files to change:**
- `taui/extensions/__init__.py` — add dependency resolution, config passing, load ordering
- `taui/config.py` — add extension config section parsing

---

### Phase 10: Advanced Extension Capabilities

**Goal:** Extensions can do everything the core can do.

**Changes:**

1. **Agent persona extensions** — swap entire agent personality:

```python
# personas/code_reviewer.py
def register(tools, commands, hooks):
    hooks.system_prompt(lambda prompt, session:
        REVIEWER_PROMPT + "\n\n" + prompt
    )
    # Restrict tool surface
    tools.disable("write")
    tools.disable("edit")
    tools.disable("bash")
```

2. **Workflow extensions** — multi-step orchestrated workflows:

```python
# workflows/review_and_deploy.py
class ReviewAndDeployTool:
    name = "review_deploy"
    description = "Review code, run tests, deploy if passing"
    schema = {...}

    async def execute(self, arguments: dict) -> ToolResult:
        # Step 1: sub-agent reviews code
        review = await self._sub_agent.run("Review the diff...")
        if "LGTM" not in review.text:
            return ToolResult.fail("Review failed")

        # Step 2: run tests
        tests = await self._executor.execute("bash", {"command": "pytest"})
        if tests.error:
            return ToolResult.fail("Tests failed")

        # Step 3: deploy
        deploy = await self._executor.execute("bash", {"command": "git push"})
        return ToolResult.ok("Deployed successfully")
```

3. **Extension storage** — scoped key-value store:

```python
def register(tools, commands, hooks):
    storage = hooks.extension_storage("my_extension")
    await storage.set("last_run", datetime.now().isoformat())
    last = await storage.get("last_run")
```

Stored in `.taui/extension_data/<name>.json` — separate from the core event store.

4. **Event bus** — extensions emit and subscribe to custom events:

```python
def register(tools, commands, hooks):
    hooks.on("deploy:started", lambda data, session: ...)
    hooks.on("deploy:completed", lambda data, session: ...)

    # Later, in a tool:
    await hooks.emit("deploy:started", {"target": "production"})
```

---

### Phase 11: Multi-Agent Framework

**Goal:** Named agents with different prompts, tool sets, and policies — with structured handoff.

**Changes:**

1. **Agent registry:**

```python
from taui import AgentLoop, ToolRegistry

agent_registry = AgentRegistry()
agent_registry.register("reviewer", AgentConfig(
    system_prompt=REVIEWER_PROMPT,
    tools=["read", "glob", "grep", "git"],
    max_turns=10,
))
agent_registry.register("coder", AgentConfig(
    system_prompt=CODER_PROMPT,
    tools=["read", "write", "edit", "bash", "glob", "grep", "git"],
    max_turns=50,
))
```

2. **Agent routing** — direct messages to the right agent:

```python
# config.toml
[agents.reviewer]
system_prompt_file = ".taui/prompts/reviewer.md"
tools = ["read", "glob", "grep", "git"]
trigger = "/review"  # or automatic routing

[agents.coder]
system_prompt_file = ".taui/prompts/coder.md"
tools = ["read", "write", "edit", "bash", "glob", "grep", "git"]
default = true
```

3. **Agent handoff** — structured protocol:

```python
@dataclass
class AgentHandoff:
    from_agent: str
    to_agent: str
    context: str           # summary for the receiving agent
    artifacts: list[str]   # file paths or data refs
    return_to: str | None  # agent to return to when done
```

4. **Agent memory scoping** — per-agent memory:

```python
# Memory paths are scoped:
# .taui/memory/reviewer/...
# .taui/memory/coder/...
# .taui/memory/shared/...  (accessible by all agents)
```

---

## Import Path Summary

After all phases, consumers can build on taui at three levels:

### Level 1: Extensions (no import needed)

Drop a `.py` file, implement `register()`, done:

```python
# .taui/extensions/my_tool.py
from taui.ext import Tool, ToolResult

class MyTool:
    name = "my_tool"
    description = "Does a thing"
    schema = {"type": "object", "properties": {"input": {"type": "string"}}}
    category = "SHELL"

    async def execute(self, arguments: dict) -> ToolResult:
        return ToolResult.ok(f"Did the thing with {arguments['input']}")

def register(tools, commands, hooks):
    tools.register(MyTool())
```

### Level 2: Custom Session (light import)

Override specific parts, keep the rest:

```python
import taui

session = await (
    taui.SessionBuilder()
    .with_provider(my_provider)
    .add_tool(MyTool())
    .with_policy("bash", "deny")
    .build()
)

result = await session.send("What's in src/?")
```

### Level 3: Full Harness (deep import)

Wire everything yourself:

```python
import taui

# Build from components
config = taui.Config.load()
provider = taui.CopilotProvider(credentials=taui.get_credentials("copilot"))
registry = taui.ToolRegistry()
taui.register_builtins(registry)
executor = taui.ToolExecutor(registry=registry, policy=taui.ToolPolicy())
store = taui.Store(config.working_dir)
await store.connect()
stream = taui.StreamClient(store)

builder = taui.SystemPromptBuilder()
builder.with_project_context(taui.ProjectContext.discover(config.working_dir))
builder.with_tools(registry)

loop = taui.AgentLoop(
    llm=provider, executor=executor, stream=stream,
    system_prompt=builder.render(), model=config.model,
)

# Your UI, your rules
async for event in stream.tail(loop.stream_id):
    render(event)
```

---

## Priority Order

| Phase | Effort | Impact | Dependencies |
|-------|--------|--------|-------------|
| 1. Clean Public API | Small | High | None |
| 2. Provider Registry | Small | High | None |
| 3. Session Builder | Medium | High | Phase 2 |
| 4. Tool Wiring Protocol | Medium | Medium | None |
| 5. Store Abstraction | Medium | Medium | None |
| 6. Config Expansion | Medium | High | None |
| 7. Wire Commands | Small | Medium | None |
| 8. Extension DX | Medium | High | Phases 1-4 |
| 9. Harness Composition | Large | Medium | Phases 6, 8 |
| 10. Advanced Extensions | Large | Medium | Phases 8, 9 |
| 11. Multi-Agent | Large | High | Phases 3, 4, 9 |

Phases 1, 2, 4, 5, 6, 7 are independent — they can be done in parallel. Phase 3 depends on Phase 2 (provider registry). Phase 8 depends on 1-4 being done (stable API to document). Phases 9-11 are later stages that build on the foundation.

---

## Design Principles

1. **Framework first.** Taui is a library of composable components. The default app is one assembly. Extensions use the same APIs as builtins — there's no privileged internal surface.
2. **Two paths.** Write extensions to customize taui, or import taui's components to build something new. Both are first-class.
3. **Files, not packages.** Extensions are `.py` files. Copy a file, it works. No setup.py, no manifest, no build step.
4. **Agent-writable.** The agent can create extensions via `/i`. The harness can reshape itself mid-session.
5. **Isolation by default.** A broken extension cannot crash the core. Extensions are loaded in try/except. `--no-extensions` always works.
6. **Project-scoped by default.** `.taui/` lives in the repo. Check it into git and the team shares the harness.
7. **Convention over configuration.** `register(tools, commands, hooks)` is the only contract.
8. **Import-friendly.** `import taui` gives you everything. Deep imports still work but aren't required.
9. **No privileged internals.** Anything a builtin does, an extension can do. The APIs are the same.
10. **Progressive disclosure.** Level 1 (extensions) requires zero imports. Level 2 (custom session) requires one. Level 3 (full harness) requires many — but they're all documented and stable.
