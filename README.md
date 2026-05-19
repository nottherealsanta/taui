# taui

Taui is a customizable agentic coding interface for developers. It runs as a
full-screen Textual TUI; the terminal app is the product.

Alpha software: APIs, commands, and behavior may change.

## Install

```bash
uvx taui
```

For local development:

```bash
uv run taui
uv run taui --version
uv run taui --login
uv run taui -p copilot -m <model>
uv run taui -p codex -m <model>
uv run taui -d /path/to/project
uv run taui --session <session_id>
```

CLI parsing and app launch live in `taui/main.py:29` and `taui/main.py:90`.

## What It Does

- Runs an async agent loop over provider responses, tool calls, and observations:
  `taui/agent/loop.py:93`.
- Wires providers, tools, extensions, prompts, store, and loop in one composition root:
  `taui/session.py:139`.
- Stores sessions as append-only SQLite event streams in the working directory:
  `taui/store/store.py:97` and `taui/store/stream.py:22`.
- Renders chat, streaming output, approvals, questions, sidebars, and session controls in
  Textual: `taui/tui/app.py:206`.

## Providers

Built-in providers:

| Provider | Auth | Implementation |
| --- | --- | --- |
| GitHub Copilot | device flow | `taui/llm_provider/providers/copilot.py:33` |
| OpenAI Codex | PKCE browser flow | `taui/llm_provider/providers/codex.py:26` |

Run `taui --login` to authenticate. Credentials are loaded through
`taui/llm_provider/config.py:15` and selected by `Config.load()` at
`taui/config.py:64`.

## Commands

Important slash commands are registered in `taui/commands/builtins.py:858`.

| Command | Purpose |
| --- | --- |
| `/help`, `/h`, `/?` | Show help |
| `/model` | Show, refresh, or switch models |
| `/provider` | Show or switch provider |
| `/agents` | List or activate agent profiles |
| `/sessions` | List or resume sessions |
| `/new [message]` | Start a new session |
| `/compact`, `/context` | Manage or inspect context |
| `/extensions`, `/reload`, `/ext-mode` | Inspect and reload extensions |
| `/i [message]` | Enter self-edit mode |
| `/copy`, `/export` | Copy context or export a session |
| `/hotkeys`, `/keys` | Show key bindings |
| `/verbose`, `/quiet` | Toggle tool output verbosity |
| `/update-providers-models` | Refresh the models.dev cache |

## Keys

App-level bindings are defined in `TauiApp.BINDINGS` at `taui/tui/app.py:399`.
Input-specific bindings are in `ChatInput.BINDINGS` at
`taui/tui/widgets/chat_input.py:64`.

| Key | Action |
| --- | --- |
| `Ctrl+Q` | Quit |
| `Ctrl+N` | New session |
| `Ctrl+C` | Cancel active request or approval |
| `Ctrl+D` | Quit after double press |
| `Ctrl+B` | Toggle sidebar |
| `Ctrl+R` | Toggle info sidebar |
| `Ctrl+E` | Enter self-edit mode |
| `Ctrl+X` | Context breakdown |
| `Alt+Left/Right` | Focus left/right pane |
| `Ctrl+PageDown/Up` | Next/previous tab |
| `Escape` | Leave mode or dismiss panels |

## Configuration

Config fields are defined in `taui/config.py:33`.

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
```

Tool policy evaluation is in `taui/tools/executor.py:42`; pattern permissions are in
`taui/permissions.py:38`.

## Extensions And Skills

Extensions are Python files loaded from `~/.taui/extensions/*.py` and
`.taui/extensions/*.py`. The `register(ctx)` context is defined at
`taui/extensions/__init__.py:66`; extension loading starts at
`taui/extensions/__init__.py:169`.

Skills are `SKILL.md` files discovered by `taui/skills/__init__.py:91` and loaded lazily
by `taui/skills/__init__.py:52`.

## Documentation

- Product and architecture overview: `docs/taui.md:1`
- Runtime flow: `docs/runtime.md:1`
- Tools and permissions: `docs/tools.md:1`, `docs/permission-dsl.md:1`
- Extensions, hooks, skills, and agents: `docs/build-your-harness.md:1`,
  `docs/extension-hooks.md:1`, `docs/agents.md:1`
- Providers and auth: `docs/providers.md:1`
- Context and prompts: `docs/context-strategies.md:1`, `docs/system-prompt.md:1`
- Tests and visual harness: `docs/testing.md:1`

## Checks

```bash
uv run ruff check .
uv run python -m pytest tests/ -q
```

Target focused tests first when changing one subsystem. The scenario and visual harness
are documented in `docs/testing.md:1`.
