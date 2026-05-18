# AGENTS.md

This file is the working guide for coding agents in this repository. Keep it focused on
current behavior and edit it when architecture, commands, or conventions change.

## Project

Taui is a customizable agentic coding interface for developers.

- Package: `taui`
- Version: `0.4`
- Runtime: Python `>=3.13`
- UI: full-screen Textual TUI only
- Entry point: `taui.main:main`
- Console script: `taui`
- Core idea: users control the agent, tools, prompts, extensions, skills, and storage

The active product lives in `taui/`, `tests/`, `docs/`, and top-level package files.

## Quick Start

```bash
uv run taui
uv run taui --version
uv run taui --login
uv run taui -p copilot -m <model>
uv run taui -p codex -m <model>
uv run taui -d /path/to/project
uv run taui --session <session_id>
```

Run checks before handing off code changes:

```bash
uv run ruff check .
uv run python -m pytest tests/ -q
```

For targeted work, prefer focused tests first, then the full suite when the change touches
shared behavior:

```bash
uv run python -m pytest tests/test_tools.py -q
uv run python -m pytest tests/test_tui.py -q
uv run python -m pytest tests/test_session.py -q
```

## Architecture

Taui is organized around an append-only SQLite event store and an async agent loop.

```text
Textual TUI
  taui/tui/
    |
Session composition root
  taui/session.py
    |
AgentLoop
  taui/agent/loop.py
    |
ToolExecutor
  taui/tools/executor.py
    |
Builtin and extension tools
  taui/tools/builtins/

Store and streams sit beside the loop:
  taui/store/  SQLite event log, sessions, stream tailing
```

Important boundaries:

- `Session.create()` wires provider auth, tools, extensions, prompt builder, store,
  stream client, and `AgentLoop`.
- `AgentLoop` owns the think -> tool -> observe cycle and emits stream events.
- `ToolExecutor` is the policy and timeout gate. Tools should return `ToolResult.fail()`
  for expected failures, not raise.
- `Store` is the durable source for session and stream history. Do not introduce a
  second event bus or side-channel state store for agent lifecycle data.
- The TUI renders state and collects input. Keep agent behavior in session/agent/tool
  modules rather than burying it in widgets.

## Source Map

| Path | Purpose |
| --- | --- |
| `taui/main.py` | CLI parsing, logging setup, provider login flow, TUI launch |
| `taui/config.py` | Runtime config defaults and config-file loading |
| `taui/session.py` | Composition root for provider, tools, extensions, prompt, store, loop |
| `taui/agent/loop.py` | Agent state machine, tool cycle, streaming callbacks, steering |
| `taui/agent/context.py` | Token estimation and context breakdown helpers |
| `taui/store/` | SQLite store, stream client, event/session persistence |
| `taui/tools/base.py` | Tool protocol, categories, `ToolResult` |
| `taui/tools/registry.py` | Tool registration, schemas, subsets, guidelines |
| `taui/tools/executor.py` | Policy decisions, approval outcomes, timeout/error wrapping |
| `taui/tools/builtins/` | Builtin read/write/edit/search/bash/git/mcp/memory/question/skills/sub-agent tools |
| `taui/tui/app.py` | Main `TauiApp`, command dispatch, streaming render, steering/queue, sessions |
| `taui/tui/widgets/` | Textual widgets for input, sidebar, tool status, approvals, info bar |
| `taui/tui/screens/` | Modal screens such as context breakdown and session picker |
| `taui/commands/` | Slash command registry and builtins |
| `taui/extensions/` | Python extension discovery and loading |
| `taui/skills/` | Skill package discovery and lazy loading |
| `taui/llm_provider/` | Provider abstraction, auth, model discovery, Copilot/Codex implementations |
| `taui/self_edit/` | `/i` self-edit mode, panels, controller, scaffolding, playbooks |
| `taui/lsp/` | LSP client lifecycle and types (experimental — no current consumer) |
| `taui/symbols/` | Lightweight source symbol extraction (experimental — no current consumer) |
| `tests/` | Pytest suite with mock providers and isolated tool/TUI tests |
| `docs/architecture_docs/` | Deeper design notes; verify against code before copying details |

## Runtime Features

### TUI

`TauiApp` is the only interface. It provides:

- scrollable chat log and streaming markdown responses
- reasoning/text deltas via Textual messages
- compact tool status rendering with FIFO start/end matching
- inline approval and question handling
- approval prompts can persistently auto-approve an entire tool by generating a
  project `.taui/extensions/taui_auto_approve_<tool>.py` extension by default, or a
  global `~/.taui/extensions/taui_auto_approve_<tool>.py` extension when selected
- sidebar toggle
- prompt history at `~/.cache/taui/prompt_history`
- `@file` expansion before sending a message (text files inlined, image files
  attached as base64 data URLs)
- image paste support: drag-and-drop image file paths, `@image.png` references,
  `Ctrl+V` to paste from system clipboard
- session replay and session picker
- self-edit mode through `/i`

Current key bindings are defined in `TauiApp.BINDINGS` and `ChatInput`; verify in code
before documenting a shortcut. Important app-level bindings include:

- `Ctrl+Q`: quit
- `Ctrl+N`: new session
- `Ctrl+C`: cancel active request or approval
- `Ctrl+D`: quit (double-press required)
- `Ctrl+B`: toggle sidebar
- `Ctrl+R`: toggle info sidebar
- `Ctrl+E`: enter self-edit mode
- `Ctrl+X`: context breakdown
- `Alt+Left/Right`: focus left/right pane
- `Ctrl+PageDown/Up`: next/previous tab
- `Escape`: leave self-edit mode / dismiss panels

While the agent is busy, normal Enter input is used as steering and queued follow-ups
are handled by `ChatInput.Submitted.queue`.

### Slash Commands

Builtins are registered in `taui/commands/builtins.py`. Current commands include:

- `/help`, `/h`, `/?`
- `/cost`
- `/compact`
- `/context`
- `/clear`
- `/model`
- `/agents`
- `/provider`
- `/extensions`
- `/i`
- `/ext-mode`
- `/sessions`
- `/new`
- `/reload`
- `/login`
- `/logout`
- `/session`
- `/copy`
- `/export`
- `/hotkeys`, `/keys`
- `/verbose`, `/quiet`
- `/debug`

Keep command behavior in command classes where possible; TUI-specific actions can be
signaled through `CommandResult.metadata["action"]`.

### Store And Sessions

The store is a SQLite database under the working directory at `.taui/store.db`.

- Streams are append-only and offset-addressed.
- Session metadata is stored alongside streams.
- TUI replay is reconstructed from store events, not separate transcript files.
- `StreamClient.tail()` is the live consumer path.
- SQLite uses WAL mode in `Store.connect()`.

When adding events, keep payloads JSON-serializable and stable enough for replay.

### Extensions

Extensions are Python files loaded from:

- global: `~/.taui/extensions/*.py`
- project: `.taui/extensions/*.py`

Files beginning with `_` are ignored. Project extensions override global extensions with
the same name. Builtin extension names are reserved.

Preferred extension entry point:

```python
def register(ctx):
    ctx.tools.register(my_tool)
    if ctx.commands:
        ctx.commands.register(my_command)
    if ctx.hooks:
        ctx.hooks.add("system_prompt", my_transform)
    ctx.skills.add_path("skills/my-skill.md")
```

Extension failures should be logged and isolated; a bad extension must not prevent Taui
from starting.

### Skills

Skills are discovered from:

- `~/.config/agents/skills/<name>/SKILL.md`
- `~/.taui/skills/<name>/SKILL.md`
- `.agents/skills/<name>/SKILL.md`
- `.taui/skills/<name>/SKILL.md`

Skills are loaded lazily and truncated at `MAX_SKILL_CHARS`. Extension-bundled skills can
be contributed with `ctx.skills.add_path(...)`.

### Self-Edit Mode

`/i` opens self-edit mode. The current session loop is temporarily replaced with a
specialist loop using playbooks from `taui/self_edit/playbooks/`.

Self-edit should create or modify extension files, skills, commands, or tools through the
extension surface. Do not use self-edit as a reason to bypass core invariants in
`AgentLoop`, `Store`, or `ToolExecutor`.

## Coding Conventions

- Use dataclasses with `slots=True` for lightweight structured types unless there is a
  reason not to.
- Keep public APIs typed.
- Prefer async APIs for I/O paths; the rest of the runtime is async.
- Keep changes scoped to the module that owns the behavior.
- Use registries for tools, commands, providers, skills, and extensions.
- Preserve the `ToolResult.ok()` / `ToolResult.fail()` convention for tool outcomes.
- Do not let extension, hook, or tool implementation errors crash the agent loop unless
  the failure is truly unrecoverable.
- Follow Ruff settings from `pyproject.toml`: rules `E`, `F`, `I`, `UP`, line length 100,
  target `py313`.
- Avoid adding dependencies unless the feature materially needs them.

## Testing Guidance

Use existing mock providers and test tools instead of real network calls. Prefer tests
near the changed behavior:

- tools and policy: `tests/test_tools.py`, `tests/test_builtins.py`, `tests/test_question.py`
- agent loop and context: `tests/test_agent.py`, `tests/test_context.py`,
  `tests/test_sub_agent.py`
- TUI behavior: `tests/test_tui.py`
- config/session/store: `tests/test_config.py`, `tests/test_session.py`,
  `tests/test_store.py`
- extensions/skills/hooks: `tests/test_extensions.py`, `tests/test_skills.py`,
  `tests/test_hooks.py`
- provider/auth/model plumbing: prefer unit tests with mocks; do not require live LLM auth

When modifying Textual UI behavior, add or update unit tests first when practical. If a
manual TUI check is needed, run `uv run taui` from a throwaway workspace or with a test
project directory so `.taui/store.db` writes are intentional.

### Visual & provider-scenario harness

For changes that affect what the user sees or how taui reacts to LLM responses,
use the harness in `tests/scenarios/`:

- `tests/scenarios/scripted_provider.py` — `ScriptedProvider` plays back a list of
  `Turn` definitions (text deltas, reasoning deltas, tool calls, usage, raised
  errors). It satisfies the same duck-type contract as the real providers, so
  the entire `AgentLoop` runs unmodified.
- `tests/scenarios/scenarios.py` — named factories: `happy_path`,
  `streamed_reply`, `with_reasoning`, `with_tool_call`, `parallel_tool_calls`,
  `rate_limit_then_recover`, `context_overflow_then_recover`, `auth_expired`,
  `quota_exceeded`, `empty_response`. Add new factories here when a shape
  recurs in more than one test.
- `tests/test_provider_scenarios.py` — runs each scenario through a real
  `Session` and asserts on the observable behavior. This is the contract
  between the scripted provider and the rest of taui — if it regresses, the
  visual snapshots become unreliable too.
- `tests/test_tui_visual.py` — captures SVG snapshots of `TauiApp` in
  representative states (driven by `ScriptedProvider`). Snapshots live under
  `tests/__snapshots__/test_tui_visual/`.

Running and updating snapshots:

```bash
uv run python -m pytest tests/test_tui_visual.py          # verify
uv run python -m pytest tests/test_tui_visual.py --snapshot-update  # accept new baseline
```

When a snapshot test fails, pytest-textual-snapshot writes an HTML diff report
at `snapshot_report.html`. A coding agent updating the TUI should open that
report, confirm the visual change matches intent, then re-run with
`--snapshot-update`. Adding a new snapshot point is usually one extra block in
`tests/test_tui_visual.py` plus a scenario.

The harness patches `taui.session._create_provider`, so no network/auth is
needed — tests run offline and deterministically.

## Common Pitfalls

- Do not duplicate state outside the SQLite store for sessions, stream replay, approvals,
  or agent lifecycle.
- Do not put provider-specific assumptions in the agent loop; keep them in
  `taui/llm_provider/`.
- Do not make tools raise for normal user-facing failures; return `ToolResult.fail()`.
- Do not hard-code model names as defaults outside `taui/llm_provider/models.py` and
  config loading.
- Do not add TUI-only behavior to core agent classes unless the behavior is truly
  interface-independent.
- Do not trust docs blindly when code has moved; prefer code, tests, then docs.

## Documentation

Update docs when behavior changes. If this file conflicts with implementation, either
fix the implementation or update this file in the same change.

### Documentation Index

| Document | Path | Covers |
| --- | --- | --- |
| **User-facing README** | `README.md` | Install, getting started, providers, key bindings, slash commands, config, extensions, skills |
| **Project overview** | `docs/taui.md` | Philosophy, core capabilities, design goals |
| **Agent-facing guide** | this `AGENTS.md` | Quick start, architecture, source map, conventions, testing, pitfalls |

### Architecture Deep-Dives (`docs/architecture_docs/`)

| Document | Path | Covers |
| --- | --- | --- |
| Agent loop | `docs/architecture_docs/agent-loop.md` | State machine, message types, turn lifecycle, callbacks, compaction, steering, variants |
| Store & streams | `docs/architecture_docs/store-streams.md` | SQLite schema, EventType enum, Store/StreamClient API, live-tail, sessions |
| Tool system overview | `docs/architecture_docs/tools/overview.md` | Tool protocol, ToolResult, ToolRegistry, ToolExecutor, policy, truncation |
| Built-in tools | `docs/architecture_docs/tools/builtins.md` | All 20 built-in tools with parameters and behavior |
| TUI | `docs/architecture_docs/tui.md` | TauiApp layout, messages, ToolController, widgets, screens, streaming |
| Session & config | `docs/architecture_docs/session-config.md` | Session composition root, Config dataclass, CostTracker |
| Prompt builder | `docs/architecture_docs/prompt-builder.md` | Template system, variables, adaptive guidelines, instruction discovery |
| Extensions | `docs/architecture_docs/extensions.md` | Discovery, loading, ExtensionContext, ExtensionRegistry API |
| Skills | `docs/architecture_docs/skills.md` | Discovery paths, Skill dataclass, SkillRegistry, SkillsTool |
| Self-edit mode | `docs/architecture_docs/self-edit.md` | /i mode, scoped tools, extension-only output, SelfEditInventory |
| Sub-agents | `docs/architecture_docs/sub-agents.md` | Sub-agent architecture, task tool, recursion prevention |
| LLM provider | `docs/architecture_docs/llm-provider.md` | Provider abstraction, wire types, Copilot/Codex implementations |
| Auth | `docs/architecture_docs/auth.md` | Copilot device flow, Codex PKCE OAuth, config persistence |
| MCP | `docs/architecture_docs/mcp.md` | MCP protocol bridge, JSON-RPC, server configuration |
| LSP | `docs/architecture_docs/lsp.md` | LSP client, language servers, wire protocol (experimental) |
| Symbols | `docs/architecture_docs/symbols.md` | AST-based symbol indexer (experimental) |

### Guides & References (`docs/`)

| Document | Path | Covers |
| --- | --- | --- |
| Agent variants | `docs/agents.md` | AgentVariant dataclass, built-in/custom variants, TOML format |
| Extension hooks | `docs/extension-hooks.md` | HookRegistry API, all hook categories, execution semantics |
| Permission DSL | `docs/permission-dsl.md` | PermissionRule, 3-layer cascade, TOML format, pattern matching |
| System prompt | `docs/system-prompt.md` | Template, variables, adaptive guidelines, overrides, assembly pipeline |
| Context strategies | `docs/context-strategies.md` | Compaction algorithm, soft/hard phases, manual compact, recovery |
| Build your harness | `docs/build-your-harness.md` | How-to: register tools, variants, hooks, commands, providers, skills |
