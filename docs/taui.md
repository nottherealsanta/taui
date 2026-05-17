# Taui

Taui is a customizable agentic coding interface for developers. It runs entirely as a
full-screen Textual TUI — there is no web UI, REST API, or other interface. The terminal
is the product.

## Philosophy

**You control the agent.** Taui is a harness, not a product with an opinionated
workflow. The tools the agent can call, the permissions required for each tool, the
system prompt, the agent variant in use, the extensions loaded, and the skills available
are all under your control without modifying any source code.

**The store is the truth.** All agent activity — messages, tool calls, results, usage —
is written to an append-only SQLite event store at `.taui/store.db`. Session replay,
cost tracking, and transcript export all read from the store. There is no second event
bus.

**Extensions, not forks.** Customization happens through the extension surface
(`register(ctx)`). Extensions can register tools, commands, hooks, skills, agent
variants, context strategies, and providers. Broken extensions are isolated; they cannot
crash the agent.

**Safety by default.** Destructive tools (`bash`, `write`, `edit`) require confirmation
before they run. Permissions can be layered (agent → project → global) using a TOML DSL.
Read-only agent variants block file writes entirely. Self-edit mode confines writes to
`.taui/`.

## Core Capabilities

### Full-Screen TUI

The only interface. Provided by [Textual](https://github.com/Textualize/textual).
Features include:

- Scrollable chat log with streaming markdown responses
- Reasoning and text delta streaming
- Compact tool status display with FIFO start/end matching
- Inline approval prompts for tool confirmation
- `@file` expansion (text files inlined, image files as base64 data URLs)
- Image paste via `Ctrl+V`, drag-and-drop, or `@image.png` references
- Prompt history persisted at `~/.cache/taui/prompt_history`
- Session picker and replay (`/sessions`)
- Command palette for Taui actions, slash commands, and model switching (`Ctrl+P`)
- Sidebar toggle (`Ctrl+B`)
- Context breakdown modal (`Ctrl+X`)

Key bindings (verify against `TauiApp.BINDINGS` in `taui/tui/app.py`):

| Binding | Action |
|---------|--------|
| `Ctrl+Q` | Quit |
| `Ctrl+N` | New session |
| `Ctrl+C` | Cancel active request or approval |
| `Ctrl+B` | Toggle sidebar |
| `Ctrl+P` | Open command palette |
| `Ctrl+X` | Context breakdown |
| `Escape` | Exit self-edit mode |

### Agent Loop

The agent runs a think → tool → observe cycle (`taui/agent/loop.py`):

1. Sends the conversation to the LLM provider
2. Executes tool calls returned by the LLM (FILE_READ and SEARCH tools run in parallel)
3. Feeds results back and repeats
4. Stops when the LLM produces a final text response or `max_turns` is reached

### Sub-Agents

The `sub_agent` builtin tool spawns a child `Session` with an optional tool subset,
system prompt, model, and turn limit. The child session's stream has `parent_id` set to
the parent's stream for lineage tracking.

### Tools

Builtin tools cover file read/write/edit, search (glob, grep), bash execution, git
operations, MCP, memory, question, skills, sub-agents, and LSP. Extensions can register
additional tools via `ctx.tools.register(my_tool)`.

### Extensions

Python files loaded from `~/.taui/extensions/*.py` (global) and
`.taui/extensions/*.py` (project). Each file must define `register(ctx)`. Project
extensions override global ones with the same name. Extensions are isolated — errors are
logged, not re-raised. See `docs/build-your-harness.md` for the full registration API.

### Skills

Markdown prompt files discovered from:

- `~/.config/agents/skills/<name>/SKILL.md`
- `~/.taui/skills/<name>/SKILL.md`
- `.agents/skills/<name>/SKILL.md`
- `.taui/skills/<name>/SKILL.md`

Loaded lazily on demand. Extensions can bundle skills via `ctx.skills.add_path(...)`.

### Memory

The `memory` builtin tool writes structured facts to a persistent memory store that
survives across sessions.

### MCP

The `mcp` builtin tool connects to MCP servers and exposes their tools to the agent.

### LSP (Experimental)

The `lsp` builtin tool wraps an `LspManager` (`taui/lsp/`). No active consumers exist
yet; the surface is experimental.

### Session Replay

All sessions are replayable from the store. `/sessions` opens a picker; selecting a
session rebuilds the conversation from its stream. Fork and resume are first-class
operations.

### Permissions

Three-layer permission DSL: agent → project → global. Patterns use fnmatch glob syntax.
Rules are expressed in TOML. See `docs/permission-dsl.md`.

### Hooks

Extensions can intercept UI rendering, message pipelines, tool calls, session start, and
approval decisions. See `docs/extension-hooks.md`.

### Agent Variants

Named bundles of (model, system_prompt, tool_names, read_only, max_turns, permission).
Builtin variants: `build` (full access) and `plan` (read-only). Custom variants can be
added via TOML files in `.taui/agents/` or via `ctx.agents.register()`. See
`docs/agents.md`.

### Cost Tracking

Every LLM response includes usage data. `CostTracker` accumulates input/output tokens
and cost estimates per model. `/cost` shows the running total for the current session.

### Slash Commands

Registered in `taui/commands/builtins.py`. Relevant commands include `/help`, `/cost`,
`/compact`, `/clear`, `/model`, `/provider`, `/extensions`, `/i`, `/sessions`, `/diff`,
`/review`, `/commit`, `/new`, `/reload`, `/copy`, `/export`, `/hotkeys`, `/verbose`,
`/debug questions`.

## Self-Edit Mode (`/i`)

`/i` enters self-edit mode. The active session loop is replaced with a specialist
`AgentLoop` built by `taui/self_edit/factory.py` using playbooks from
`taui/self_edit/playbooks/`.

**Safety guarantees:**

- Writes are confined to `.taui/` — the `_extensions_guard` path guard on `write` and
  `edit` tools rejects any path outside the project's `.taui/` directory.
- Self-edit snapshots the prior session state (`_SessionSnapshot`) before entering, and
  restores it on exit via `Escape`.
- Scope can be toggled between `project` (`.taui/`) and `global` (`~/.taui/`) within
  self-edit mode.
- Core taui source files are structurally unreachable from self-edit mode.

The intended use is creating or modifying extension files, skills, commands, and tools
through the extension surface.

## System Prompt

Template-based with `{variable}` substitution. Variables are populated from working
directory, date, platform, git state, tool metadata, and discovered instruction files
(`AGENTS.md`, `.taui/instructions.md`). Override the entire template by creating
`.taui/system_prompt.md`. See `docs/system-prompt.md`.

## Context Management

Automatic compaction keeps conversation history within the LLM's token budget. Two
phases: soft (drop oldest to 80%) and hard (drop oldest to 90%). Manual compaction via
`/compact` uses a more aggressive 60%/70% ratio. `Ctrl+X` shows a per-section
breakdown. See `docs/context-strategies.md`.

## Quick Start

```bash
uv run taui                        # default provider and model
uv run taui -p copilot -m <model>  # explicit provider and model
uv run taui -d /path/to/project    # specific working directory
uv run taui --session <id>         # resume a session
uv run taui --login                # authenticate with a provider
```
