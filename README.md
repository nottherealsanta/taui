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

CLI parsing and app launch live in `taui/main.py:104` (`parse_args`) and `taui/main.py:180` (`main`).

## What It Does

- Runs an async agent loop over provider responses, tool calls, and observations:
  `taui/agent/loop.py:99`.
- Wires providers, tools, extensions, prompts, store, and loop in one composition root:
  `taui/session.py:66`.
- Stores sessions as append-only SQLite event streams in the working directory:
  `taui/store/store.py:113` and `taui/store/stream.py:22`.
- Renders chat, streaming output, approvals, questions, the file sidebar, and session
  modal controls in
  Textual: `taui/tui/app.py:65`.

## Providers

Built-in providers:

| Provider | Auth | Implementation |
| --- | --- | --- |
| GitHub Copilot | device flow | `taui/llm_provider/providers/copilot.py:49` |
| OpenAI Codex | PKCE browser flow | `taui/llm_provider/providers/codex.py:26` |

Run `taui --login` to authenticate. Credentials are loaded through
`taui/llm_provider/config.py:15` and selected by `Config.load()` at
`taui/config.py:77`.

## Commands

Important slash commands are registered in `taui/commands/builtins.py:1271`.

| Command | Purpose |
| --- | --- |
| `/help`, `/h`, `/?` | Show help |
| `/model` | Show, refresh, or switch models |
| `/variant` | Show, set, or pick model variant (reasoning effort) |
| `/provider` | Show or switch provider |
| `/agents` | List or activate agent profiles |
| `/skills [name\|add <source>]` | List/toggle skills, or install from a source |
| `/prompts` | List or apply prompt files |
| `/sessions` | Open the session picker modal or resume a session |
| `/new [message]` | Start a new session |
| `/compact`, `/context` | Manage or inspect context |
| `/clear` | Clear conversation history |
| `/worktree [add <branch>]` | List git worktrees, or create one |
| `/extensions`, `/reload`, `/ext-mode` | Inspect and reload extensions |
| `/i [message]` | Enter self-edit mode |
| `/copy`, `/export` | Copy context or export a session |
| `/cost` | Show token usage and estimated cost |
| `/tasks [stop <id>]` | List or cancel background tasks |
| `/mcp [list\|connect\|disconnect]` | Manage MCP server connections |
| `/login`, `/logout` | Add/re-authenticate or remove provider credentials |
| `/hotkeys`, `/keys` | Show key bindings |
| `/verbose`, `/quiet` | Toggle tool output verbosity |
| `/theme [dark\|light]` | Switch UI theme |
| `/update-providers-models` | Refresh the models.dev cache |

## Keys

App-level bindings are defined in `TauiApp.BINDINGS` at `taui/tui/app.py:76`.
Input-specific bindings are in `ChatInput.BINDINGS` at
`taui/tui/widgets/chat_input.py:71`.

| Key | Action |
| --- | --- |
| `Ctrl+Q` | Quit |
| `Ctrl+N` | New session |
| `Ctrl+C` | Cancel active request or approval |
| `Ctrl+D` | Quit after double press |
| `Ctrl+B` | Toggle file sidebar |
| `Ctrl+R` | Toggle info sidebar |
| `Ctrl+X` | Context breakdown |
| `Alt+Left/Right` | Focus left/right pane |
| `Ctrl+PageDown/Up` | Next/previous tab |
| `Escape` | Leave mode or dismiss panels |

## Configuration

Config fields are defined in `taui/config.py:33`. Everything — provider credentials
(under `[providers.<name>]`), last-used state, and `[taui]` settings — lives in a single
file: `~/.config/taui/config.toml`.

```toml
[taui]
provider = "copilot"
model = "claude-sonnet-4.5"
max_turns = 50
verbose_tools = true
# Require approval for edits made in self-edit (/i) mode (off by default).
self_edit_confirm_edits = false

[taui.tool_policy]
bash = "confirm"
write = "confirm"
edit = "confirm"

[taui.permission]
read = { "*" = "allow" }
bash = { "git status" = "allow", "*" = "ask" }
```

Tool policy evaluation is in `taui/tools/executor.py:152`; pattern permissions are in
`taui/permissions.py:38`.

## Extensions And Skills

Extensions are Python files loaded from `~/.taui/extensions/*.py` and
`.taui/extensions/*.py`. The `register(ctx)` context is `ExtensionContext`, defined at
`taui/extensions/__init__.py:66`; extension loading starts at
`taui/extensions/__init__.py:169`.

Skills are `SKILL.md` files discovered by `taui/skills/__init__.py:114` (`SkillRegistry.discover`)
and loaded lazily by `taui/skills/__init__.py:75` (`Skill.load_content`).

Install skills from external sources (compatible with
[`vercel-labs/skills`](https://github.com/vercel-labs/skills)) with
`/skills add <source>`, or just paste `npx skills add <source>` / a bare repo
ref into the chat input. Sources may be GitHub shorthand (`owner/repo`), a full
git/GitHub/GitLab URL, a URL pointing at one skill
(`…/tree/<ref>/<path>`), an SSH git URL, or a local path; add `-g` to install
globally. The installer lives in `taui/skills/installer.py`, and the self-edit
agent exposes the same engine as the `install_skill` tool.

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
uv run python -m pytest -q -m tools  # replace tools with the changed domain
```

Use domain groups for focused checks instead of running everything:

```bash
uv run python -m pytest -q -m tools
uv run python -m pytest -q -m agent
uv run python -m pytest -q -m "agent or provider"
uv run python -m pytest -q -m tui
```

Target focused tests first when changing one subsystem. The scenario and visual harness
are documented in `docs/testing.md:1`.
