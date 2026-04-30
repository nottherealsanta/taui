# Taui: Harness Framework Plan

Taui is a framework for building coding harnesses. It ships as a minimal harness you can use directly, but the real point is that every component — tools, commands, prompts, hooks, UI — is a composable piece you can swap, extend, or replace. Extensions aren't an afterthought bolted onto the side. They're how taui itself is built.

There are two ways to use taui:

1. **Write extensions** — drop `.py` files into `.taui/extensions/`. Add tools, commands, hooks, prompt overrides. The agent can do this for you via `/i`. No fork, no build step, no package manager. This is the fast path.

2. **Build a new harness** — import taui's components as a library. Wire your own session, pick which tools to register, write your own CLI or UI, swap the LLM provider. Taui gives you the agent loop, tool executor, store, config, and extension loader as building blocks. You build the harness.

---

## Core Thesis

Most coding harnesses are closed. You use them as-is or you fork. Taui is open by design: the default app is just one arrangement of the underlying framework components. Extensions use the same APIs as the builtins. There's no privileged internal surface that extensions can't reach.

The goal: **any team can build their own harness — either by extending taui or by using it as a base**.

---

## The Framework

Taui's components are designed to be used independently or composed together. When you run `taui` out of the box, it wires all of these together for you. When you build a custom harness, you pick what you need.

### Core Components

| Component | Module | What It Does |
|-----------|--------|-------------|
| **Agent Loop** | `taui.agent.loop` | think → tool → observe cycle. Drives the conversation. |
| **Tool Registry** | `taui.tools.registry` | Register tools, look them up by name, generate schemas for the LLM. |
| **Tool Executor** | `taui.tools.executor` | Execute tool calls with policy enforcement (auto/confirm/deny). |
| **Store** | `taui.store` | Append-only SQLite event log. Sessions, messages, tool calls. |
| **Config** | `taui.config` | Layered config: file → env → CLI args. |
| **Extension Loader** | `taui.extensions` | Discover, load, isolate `.py` extension files. |
| **Hook Registry** | `taui.hooks` | UI hooks, pipeline hooks, observer hooks, override hooks. |
| **Session** | `taui.session` | Wires provider + tools + loop + store together. The unit of interactive use. |
| **LLM Providers** | `taui.llm_provider` | Copilot, Codex. Pluggable auth and completion. |
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

Extensions are isolated (broken ones don't crash the core), hot-reloadable (`/reload`), and scopable (project overrides global).

### Path 2: Build a Harness

Import taui as a library and wire your own harness. You get full control over what's included and how it's wired.

```python
from taui.agent.loop import AgentLoop
from taui.config import Config
from taui.llm_provider.providers import CopilotProvider
from taui.llm_provider.auth import get_credentials
from taui.store.store import Store
from taui.store.stream import StreamClient
from taui.tools.registry import ToolRegistry
from taui.tools.executor import ToolExecutor, ToolPolicy
from taui.tools.builtins import register_builtins
from taui.prompt_builder import SystemPromptBuilder, ProjectContext

async def main():
    config = Config.load()
    provider = CopilotProvider(credentials=get_credentials("copilot"))

    # Pick your tools — use builtins, add your own, or start from scratch
    registry = ToolRegistry()
    register_builtins(registry)  # or don't — register only what you need
    registry.register(MyCustomTool())

    executor = ToolExecutor(registry=registry, policy=ToolPolicy())
    store = Store(config.working_dir)
    await store.connect()
    stream = StreamClient(store)

    # Build your prompt
    builder = SystemPromptBuilder()
    builder.with_project_context(ProjectContext.discover(config.working_dir))
    builder.with_tools(registry)

    loop = AgentLoop(
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

## Roadmap

### Phase 1: Stabilize Core (Current)

What exists and works today:

- [x] Agent loop (think → tool → observe)
- [x] Tool registry + executor with policy
- [x] Extension discovery, loading, isolation
- [x] Hook system (UI, pipeline, observer, override)
- [x] Extensions mode (`/i`) with write guard
- [x] Store (append-only SQLite)
- [x] CLI, TUI, Web interfaces
- [x] Sub-agents
- [x] MCP integration
- [x] Skill system
- [x] Cost tracking
- [x] Session persistence and resume
- [x] Hot-reload (`/reload`)

### Phase 2: Extension Developer Experience

Make it easy for teams to build harnesses.

- [ ] **Extension templates** — `taui init-extension <type>` scaffolds a tool, command, or hook extension with boilerplate
- [ ] **Extension testing** — test harness for running extension code in isolation (`taui test-extension my_tool.py`)
- [ ] **Extension docs** — `taui extension-docs` generates API reference from the current hook/tool/command surface
- [ ] **Typed extension API** — publish `taui.ext` module with stable types: `ExtensionTool`, `ExtensionCommand`, `ExtensionHook` — so extensions get IDE autocomplete and type checking
- [ ] **Extension validation** — `taui validate-extension my_tool.py` checks schema, signatures, import compatibility before loading
- [ ] **Extension marketplace / registry** — lightweight: a curated list of community extensions with install instructions. No package manager, just git + copy

### Phase 3: Harness Composition

Enable teams to compose multiple extension sets into a coherent harness.

- [ ] **Extension groups** — `.taui/harness.toml` declares which extensions are active, their load order, and per-extension config
- [ ] **Extension dependencies** — declare that `deploy.py` requires `ci_hooks.py`
- [ ] **Extension config** — extensions can declare config keys read from `.taui/config.toml`
- [ ] **Harness packaging** — `taui pack-harness` bundles `.taui/` into a distributable archive (or just: "check `.taui/` into git")
- [ ] **Harness inheritance** — a project harness can extend a team harness (global → team → project layering)

### Phase 4: Advanced Extension Capabilities

- [ ] **UI extensions** — Svelte components that render in the Web interface, loaded from extensions
- [ ] **Agent persona extensions** — swap the entire agent personality (system prompt, tool surface, approval policy) via a single extension
- [ ] **Workflow extensions** — multi-step orchestrated workflows (review → test → deploy) defined as extensions
- [ ] **Event bus** — extensions can emit and subscribe to custom events beyond the current hook categories
- [ ] **Extension storage** — extensions get a scoped key-value store for persisting their own state (separate from the core Store)

### Phase 5: Multi-Agent Framework

- [ ] **Agent registry** — register named agents with different prompts, tool sets, and policies
- [ ] **Agent routing** — route user messages to the right agent based on intent or command
- [ ] **Agent handoff** — structured protocol for agents to delegate to each other (beyond current sub_agent)
- [ ] **Agent memory scoping** — per-agent memory that doesn't leak across agents

---

## Rename: self-edit → extensions

**Done.** All references to "self-edit" have been renamed to "extensions" throughout the codebase:

| Old | New |
|-----|-----|
| `self.self_edit` | `self.extensions_mode` |
| `toggle_self_edit()` | `toggle_extensions_mode()` |
| `_self_edit_prompt` | `_extensions_prompt` |
| `_SELF_EDIT_SYSTEM_PROMPT` | `_EXTENSIONS_SYSTEM_PROMPT` |
| `_self_edit_guard()` | `_extensions_guard()` |
| `SelfEditCommand` | `ExtensionsModeCommand` |
| `action="self_edit_on"` | `action="extensions_on"` |
| `action="self_edit_off"` | `action="extensions_off"` |
| `mode="self-edit"` | `mode="extensions"` |
| `session/toggleSelfEdit` | `session/toggleExtensions` |
| `"self_edit": ...` (JSON) | `"extensions_mode": ...` |
| `⚙ SELF-EDIT` (status bar) | `⚙ EXTENSIONS` |

The `/i` command name is unchanged — it's short and memorable. Its description now reads "Toggle extensions mode".

### Files Changed
- `taui/session.py` — core mode logic, guard, prompt constant
- `taui/commands/builtins.py` — command class, action strings
- `taui/cli.py` — prompt UI, /q behavior, action handling
- `taui/tui.py` — status bar, /q behavior, action handling
- `taui/server/app.py` — RPC method name, JSON response keys
- `tests/test_commands.py` — test names, fake sessions, assertions
- `tests/test_store.py` — session mode string assertions

### Docs (to update separately)
- `docs/taui.md` — self-edit section heading and references
- `docs/architecture_docs/self-edit.md` — rename file to `extensions-mode.md`, update content
- `docs/architecture_docs/extensions.md` — update cross-references
- `docs/architecture_docs/cli-commands.md` — update extension points section
- `docs/todo.md` — update completed items

---

## Design Principles

1. **Framework first.** Taui is a library of composable components. The default app is one assembly. Extensions use the same APIs as builtins — there's no privileged internal surface.
2. **Two paths.** Write extensions to customize taui, or import taui's components to build something new. Both are first-class.
3. **Files, not packages.** Extensions are `.py` files. Copy a file, it works. No setup.py, no manifest, no build step.
4. **Agent-writable.** The agent can create extensions via `/i`. The harness can reshape itself mid-session.
5. **Isolation by default.** A broken extension cannot crash the core. Extensions are loaded in try/except. `--no-extensions` always works.
6. **Project-scoped by default.** `.taui/` lives in the repo. Check it into git and the team shares the harness.
7. **Convention over configuration.** `register(tools, commands, hooks)` is the only contract.
