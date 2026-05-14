# 10.1 Build Your Harness

A harness is a set of extensions, agents, permissions, hooks, and commands that shape how
Taui behaves for a specific project or workflow. Everything lives in `.taui/extensions/`
(project-scoped) or `~/.taui/extensions/` (global). No core files are modified.

---

## Step 1: Register a Tool

Create `.taui/extensions/my_tool.py`. A tool is any object satisfying the `Tool` protocol
defined in `taui/tools/base.py`: it needs `name`, `description`, `schema`, `category`, and
an async `execute` method.

```python
# .taui/extensions/my_tool.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from taui.tools.base import ToolCategory, ToolResult


@dataclass(slots=True)
class WordCountTool:
    name: str = "word_count"
    description: str = "Count words in a string."
    category: ToolCategory = ToolCategory.FILE_READ
    schema: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.schema = {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to count words in."},
            },
            "required": ["text"],
        }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        text = arguments.get("text", "")
        if not isinstance(text, str):
            return ToolResult.fail("'text' must be a string")
        count = len(text.split())
        return ToolResult.ok(f"{count} words", word_count=count)


def register(ctx) -> None:
    ctx.tools.register(WordCountTool())
```

Rules:
- Return `ToolResult.fail(...)` for expected errors; do not raise.
- `schema` follows JSON Schema object notation — list all parameters the agent may pass.
- `category` controls default policy (`ToolCategory.SHELL` requires confirmation by default).

---

## Step 2: Register an Agent Variant

An agent variant is a named configuration bundle (`taui/agent/variants.py`). Variants can
be declared as TOML files or registered directly from an extension.

### TOML declaration

```toml
# .taui/agents/review.toml
name        = "review"
description = "Read-only code review agent."
read_only   = true
max_turns   = 20
system_prompt = """
You are a careful code reviewer. Read files and report issues.
Do not modify any file.
"""
```

TOML files in `.taui/agents/` are discovered automatically when Taui starts.

### Extension registration

```python
# .taui/extensions/review_agent.py
from taui.agent.variants import AgentVariant


def register(ctx) -> None:
    if ctx.agents is None:
        return
    ctx.agents.register(
        AgentVariant(
            name="review",
            description="Read-only code review agent.",
            read_only=True,
            max_turns=20,
            system_prompt=(
                "You are a careful code reviewer. Read files and report issues. "
                "Do not modify any file."
            ),
        )
    )
```

`AgentVariant` fields: `name`, `description`, `model`, `system_prompt`, `tool_names`,
`read_only`, `max_turns`, `permission`. `None` means "use session default".

---

## Step 3: Register a Context Strategy

A context strategy controls how the conversation is compacted before each LLM call. The
protocol is defined in `taui/agent/context_strategy.py`.

```python
# .taui/extensions/summarize_strategy.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from taui.agent.types import Message
from taui.agent.context import compact_messages


@dataclass(slots=True)
class SummarizeOldStrategy:
    """Keep the most recent N messages; drop everything older."""

    name: str = "summarize_old"
    keep_recent: int = 40
    _turn_count: int = field(default=0, repr=False, compare=False)

    def prepare(self, messages: list[Message], max_tokens: int) -> list[Message]:
        # First apply the standard drop-oldest pass
        compact_messages(messages, max_input_tokens=max_tokens)
        # Then trim to the most recent window
        system = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]
        if len(non_system) > self.keep_recent:
            non_system = non_system[-self.keep_recent:]
        messages[:] = system + non_system
        return messages

    def on_turn_result(self, usage: dict[str, Any]) -> None:
        self._turn_count += 1


def register(ctx) -> None:
    if ctx.context is None:
        return
    ctx.context.register(SummarizeOldStrategy())
```

`prepare()` may modify `messages` in place and must return the list.
`on_turn_result()` receives the raw usage dict (`input_tokens`, `output_tokens`, etc.)
after every completed LLM turn — use it to calibrate or log.

---

## Step 4: Register a Permission Rule

Permission rules live in your project config file (`pyproject.toml` or `.taui/config.toml`)
under `[tool.taui.permission]`. They are loaded by `taui/config.py` and applied as the
"project" layer of `taui/permissions.py:PermissionRuleset`.

```toml
# pyproject.toml
[tool.taui.permission]

# read tool: allow all files, prompt before reading .env files
read = { "*" = "allow", "*.env" = "ask", ".env.local" = "ask" }

# bash tool: allow common read-only commands, prompt for everything else
bash = { "git status" = "allow", "git log*" = "allow", "git diff*" = "allow", "*" = "ask" }

# edit tool: auto-approve edits inside src/, ask for everything else
edit = { "src/**" = "allow", "tests/**" = "allow", "*" = "ask" }

# write tool: deny writing outside the project root by default
write = { "src/**" = "allow", "tests/**" = "allow", "*" = "deny" }
```

Pattern matching uses `fnmatch` glob syntax. Rules are sorted by specificity (longest
non-wildcard prefix wins). Actions: `"allow"` (auto-execute), `"ask"` (prompt user),
`"deny"` (block).

The subject matched against patterns is:
- `bash` — the full `command` string
- `read`, `edit`, `write` — the `file_path` argument
- `glob` — the `pattern` argument
- `grep` — the `pattern` argument

---

## Step 5: Register a Hook

Hooks are registered through `ctx.hooks` and are defined in `taui/hooks.py`. They are
called by `taui/session.py` at the appropriate points in the agent lifecycle.

```python
# .taui/extensions/my_hooks.py
from __future__ import annotations


async def _before_send(message: str, session) -> str:
    """Strip trailing whitespace from every user message."""
    return message.strip()


async def _system_prompt(prompt: str, session) -> str:
    """Append project-specific instructions to the system prompt."""
    return prompt + "\n\nAlways prefer immutable data structures in Python."


def register(ctx) -> None:
    # ── UI hooks (sync, return str | None) ──────────────────────────────────
    # Override the input prompt character
    ctx.hooks.prompt(lambda session: "> ")
    # Append a line to the startup banner
    ctx.hooks.banner(lambda session: "Project: my-service  |  env: dev")
    # Add a segment to the status bar
    ctx.hooks.status(lambda session: f"turns: {session._loop.turn_count if session._loop else 0}")
    # Append to the per-turn summary line shown after each response
    ctx.hooks.turn_summary(lambda result, session: f"cost: ${result.cost_usd:.4f}"
                           if result.cost_usd else "")

    # ── Pipeline hooks (sync or async, transform and return data) ───────────
    # Transform the user message before it is sent to the LLM
    ctx.hooks.before_send(_before_send)
    # Transform the RunResult after the agent finishes
    ctx.hooks.after_result(lambda result, session: result)
    # Modify the system prompt once at session start
    ctx.hooks.system_prompt(_system_prompt)

    # ── Observer hooks (sync or async, side-effects only) ───────────────────
    # Called when the agent is about to invoke a tool
    ctx.hooks.on_tool_call(lambda call_id, name, args, session: None)
    # Called after a tool returns
    ctx.hooks.on_tool_result(lambda name, content, is_error, session: None)
    # Called when a new session starts
    ctx.hooks.on_session_start(lambda session: None)
    # Called when the agent mode changes (e.g., normal -> self-edit)
    ctx.hooks.on_mode_change(lambda mode, session: None)

    # ── Override hooks (sync or async, first non-None return wins) ──────────
    # Return True to auto-approve, False to auto-deny, None to fall through
    ctx.hooks.on_approval(lambda call_id, name, args, session: (
        True if name in {"read", "glob", "grep"} else None
    ))
```

Hook reference:

| Hook | Category | Signature | Notes |
|------|----------|-----------|-------|
| `prompt` | UI | `(session) -> str` | Input prompt string |
| `banner` | UI | `(session) -> str` | Startup banner line |
| `status` | UI | `(session) -> str` | Status bar segment |
| `turn_summary` | UI | `(result, session) -> str` | Per-turn summary text |
| `before_send` | Pipeline | `(message, session) -> message` | Transform user input |
| `after_result` | Pipeline | `(result, session) -> result` | Transform agent output |
| `system_prompt` | Pipeline | `(prompt, session) -> prompt` | Modify system prompt |
| `on_tool_call` | Observer | `(call_id, name, args, session)` | Watch tool invocations |
| `on_tool_result` | Observer | `(name, content, is_error, session)` | Watch tool results |
| `on_session_start` | Observer | `(session)` | Session lifecycle |
| `on_mode_change` | Observer | `(mode, session)` | Mode changes |
| `on_approval` | Override | `(call_id, name, args, session) -> bool \| None` | Approval gate |

---

## Step 6: Register a Command

Slash commands are registered in `taui/commands/registry.py`. The protocol requires
`name`, `description`, and an async `execute(ctx) -> CommandResult`.

```python
# .taui/extensions/ping_command.py
from __future__ import annotations

import time
from dataclasses import dataclass

from taui.commands.registry import CommandContext, CommandResult


@dataclass(slots=True)
class PingCommand:
    name: str = "ping"
    description: str = "Check that the extension system is alive."

    async def execute(self, ctx: CommandContext) -> CommandResult:
        label = ctx.args[0] if ctx.args else "world"
        ts = time.strftime("%H:%M:%S")
        return CommandResult.ok(f"pong — hello {label} at {ts}")


def register(ctx) -> None:
    if ctx.commands is None:
        return
    ctx.commands.register(PingCommand())
```

Users invoke it as `/ping` or `/ping Alice`. `CommandContext` provides:
- `raw_input` — the full original string (e.g. `"/ping Alice"`)
- `args` — tokenised arguments after the command name
- `extras` — arbitrary dict populated by the TUI (e.g. current session)

Return `CommandResult.fail(...)` to surface an error in the UI without crashing.

---

## Activating Extensions

After writing an extension file, run `/reload` in the Taui prompt to load it without
restarting. Project extensions in `.taui/extensions/` override global extensions with
the same filename stem.
