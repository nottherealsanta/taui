# taui

Agentic coding interface you can reshape.

> **Alpha**: This project is still in early development. APIs, commands, and behavior may change without notice.

## Install

```bash
uvx taui
```

Or install permanently:

```bash
uv pip install taui
```

## What is taui?

Taui is a highly customizable agentic coding interface. Instead of adapting your workflow to a fixed assistant, you control the interface itself: UI, agent, tools, prompts, extensions, skills, and storage.

Taui is a full-screen Textual TUI. Running `taui` launches the terminal interface with a sidebar, scrollable chat history, live streaming, visual tool status, approvals, questions, steering, and queueing.

## Requirements

- Python 3.13+
- A supported LLM provider account (see below)

## Getting Started

### First Run

When you run `taui` for the first time, it launches an interactive provider selection prompt. Pick one or both providers and follow the auth flow:

```bash
taui
```

You can also authenticate explicitly at any time:

```bash
taui --login
```

### Providers

Taui currently ships with two built-in providers:

| Provider | Auth Method | What You Need |
|---|---|---|
| **GitHub Copilot** | OAuth device flow | A GitHub account with an active Copilot subscription |
| **OpenAI Codex** | PKCE browser redirect | A ChatGPT Plus or Pro account |

#### GitHub Copilot

1. Run `taui` or `taui --login`
2. Select **GitHub Copilot**
3. A device code is displayed — open the GitHub URL shown and enter the code
4. Once authorized, your token is saved to `~/.config/taui/config.toml`
5. Subsequent runs use the saved token automatically

#### OpenAI Codex (ChatGPT Plus/Pro)

1. Run `taui` or `taui --login`
2. Select **OpenAI Codex**
3. A browser window opens for OpenAI OAuth — sign in and authorize
4. The token is saved to `~/.config/taui/config.toml`

### Choosing a Provider and Model

```bash
# Start with a specific provider
taui -p copilot
taui -p codex

# Use a specific model
taui -p copilot -m claude-sonnet-4

# Work in a specific directory
taui -d /path/to/project

# Resume a previous session
taui --session <session_id>

# Check version
taui --version
```

Within the TUI, use `/model` to switch models and `/provider` to switch providers.

### Tool Approval Policy

By default, destructive tools (`bash`, `write`, `edit`) require user confirmation before executing. Read-only tools (`read`, `glob`, `grep`) run automatically.

You can customize this in your config file (`~/.config/taui/config.toml`):

```toml
[taui.tool_policy]
bash = "auto"       # skip confirmation for bash
write = "confirm"   # require confirmation (default)
edit = "deny"       # block entirely
```

Valid policy values: `auto`, `confirm`, `deny`.

Approval prompts also support persistent auto-approval for a whole tool. Choosing the
project option writes a generated extension to `.taui/extensions/`; choosing the global
option writes it to `~/.taui/extensions/`. The generated extension replaces the tool with
an equivalent wrapper and sets that tool's policy to `auto` when extensions load. Project
scope is the default persistent choice.

## Key Bindings

| Key | Action |
|---|---|
| `Ctrl+Q` | Quit |
| `Ctrl+N` | New session |
| `Ctrl+C` | Cancel active request or approval |
| `Ctrl+B` | Toggle sidebar |
| `Ctrl+X` | Context breakdown |
| `Escape` | Leave self-edit mode |

## Slash Commands

| Command | Description |
|---|---|
| `/help`, `/h`, `/?` | Show help |
| `/model` | Switch model |
| `/provider` | Switch provider |
| `/compact` | Compact conversation (shows token savings) |
| `/clear` | Clear chat |
| `/cost` | Show session cost |
| `/sessions` | Browse and resume sessions |
| `/new` | Start new session |
| `/reload` | Hot-reload extensions |
| `/extensions` | List extensions |
| `/i` | Enter self-edit mode |
| `/login` | Re-authenticate providers |
| `/logout` | Clear saved credentials |
| `/copy` | Copy last response |
| `/export` | Export session |
| `/hotkeys`, `/keys` | Show key bindings |
| `/verbose`, `/quiet` | Toggle tool output verbosity |

## Extending Taui

### Extensions

Extensions are Python files that register tools, commands, hooks, and skills.

**Locations:**
- Global: `~/.taui/extensions/*.py`
- Project: `.taui/extensions/*.py`

**Example extension:**

```python
def register(ctx):
    ctx.tools.register(my_tool)
    if ctx.commands:
        ctx.commands.register(my_command)
    if ctx.hooks:
        ctx.hooks.add("system_prompt", my_transform)
    ctx.skills.add_path("skills/my-skill.md")
```

Use `/reload` to hot-reload extensions without restarting. Errors from individual extensions are reported in the chat log.

### Skills

Skills provide specialized instructions loaded lazily into the agent context.

**Locations:**
- `~/.config/agents/skills/<name>/SKILL.md`
- `~/.taui/skills/<name>/SKILL.md`
- `.agents/skills/<name>/SKILL.md`
- `.taui/skills/<name>/SKILL.md`

### Self-Edit Mode

Run `/i` to enter self-edit mode — a specialist agent that can create or modify extensions, skills, commands, and tools through the extension surface.

## Configuration

Config is loaded from `~/.config/taui/config.toml` with this structure:

```toml
[taui]
provider = "copilot"
model = "claude-sonnet-4"
max_turns = 50
verbose_tools = true

[taui.tool_policy]
bash = "confirm"
write = "confirm"
edit = "confirm"
```

CLI arguments and environment variables override config file values.

## Data Storage

Taui stores session data in `.taui/store.db` (SQLite, WAL mode) in the working directory. Sessions are append-only event streams that support replay.

Credentials are stored at `~/.config/taui/config.toml`. Logs are at `~/.taui/.logs`.

## License

MIT
