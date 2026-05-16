# Build Your Harness

This guide covers every extension point available in taui. All customization happens
through `register(ctx)` in a `.py` file dropped into an extensions directory — no
source code modification required.

## Extension Locations

| Directory | Scope | Note |
|-----------|-------|------|
| `~/.taui/extensions/` | Global | Applied to every project |
| `.taui/extensions/` | Project | Overrides global extension with the same name |

Files starting with `_` are ignored. One extension per file. The file stem is the
extension name.

Activate after writing: run `/reload` in the TUI, or restart taui.

## The `register(ctx)` Entry Point

Every extension must define:

```python
def register(ctx):
    ...
```

`ctx` is an `ExtensionContext` with these attributes:

| Attribute | Type | Purpose |
|-----------|------|---------|
| `ctx.tools` | `ToolRegistry` | Register tools |
| `ctx.commands` | `CommandRegistry \| None` | Register slash commands |
| `ctx.hooks` | `HookRegistry` | Register hooks |
| `ctx.policy` | `ToolPolicy` | Set permission rules |
| `ctx.skills` | `SkillContribution` | Bundle skill files |
| `ctx.agents` | `AgentVariantRegistry` | Register agent variants |
| `ctx.context` | `ContextStrategyRegistry` | Register context strategies |
| `ctx.providers` | `ProviderRegistrationProxy` | Register LLM providers |

`ctx.commands` may be `None` when the extension is loaded outside the TUI context
(e.g., during testing). Guard with `if ctx.commands:`.

---

## 1. Register a Tool

Tools expose capabilities to the agent. The agent calls them by name.

```python
# .taui/extensions/word_count.py
from dataclasses import dataclass, field
from typing import Any
from taui.tools.base import ToolCategory, ToolResult


@dataclass
class WordCountTool:
    name: str = "word_count"
    description: str = "Count words in a string. Returns an integer."
    category: ToolCategory = ToolCategory.AGENT
    schema: dict[str, Any] = field(default=None)

    def __post_init__(self):
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to count words in"},
                },
                "required": ["text"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        text = arguments.get("text", "")
        count = len(text.split())
        return ToolResult.ok(str(count))


def register(ctx):
    ctx.tools.register(WordCountTool())
```

**`ToolResult` convention:**

```python
ToolResult.ok("output string")           # success
ToolResult.fail("error description")     # expected failure — do NOT raise
```

**Tool categories** (from `taui.tools.base.ToolCategory`):

| Category | Description | Auto-parallelised? |
|----------|-------------|-------------------|
| `FILE_READ` | Read-only file access | Yes |
| `FILE_WRITE` | File write/edit | No |
| `SEARCH` | Search operations | Yes |
| `SHELL` | Shell execution | No |
| `GIT` | Git operations | No |
| `AGENT` | Agent-level tools | No |
| `MEMORY` | Persistent memory | No |

Tools in `FILE_READ` and `SEARCH` categories are automatically retried on failure (up
to 3 times with exponential backoff) and may be executed in parallel with other
same-category tools.

---

## 2. Register an Agent Variant

Agent variants bundle a model, system prompt, tool subset, and permission rules into a
named configuration.

```python
# .taui/extensions/security_variant.py
from taui.agent.variants import AgentVariant


def register(ctx):
    ctx.agents.register(AgentVariant(
        name="security",
        description="Security auditor — read-only, focused on vulnerabilities.",
        read_only=True,
        system_prompt=(
            "You are a security auditor. Your job is to identify vulnerabilities, "
            "hardcoded secrets, unsafe dependencies, and injection risks. "
            "Never modify files. Produce a structured findings report."
        ),
        max_turns=30,
    ))
```

Switch to the variant from the TUI or programmatically:

```python
session.switch_variant("security")
```

For TOML-based variants (no extension required), create `.taui/agents/security.toml`:

```toml
name = "security"
description = "Security auditor — read-only."
read_only = true
max_turns = 30
system_prompt = """
You are a security auditor...
"""
```

See `docs/agents.md` for the full field reference.

---

## 3. Register a Context Strategy

Context strategies control how the conversation is compacted when approaching the token
budget. The default strategy drops the oldest non-essential messages.

```python
# .taui/extensions/my_context_strategy.py
from dataclasses import dataclass
from typing import Any
from taui.agent.types import Message


@dataclass(slots=True)
class KeepRecentStrategy:
    """Keep only the last N user/assistant exchanges plus preserved messages."""

    name: str = "keep_recent"
    keep_exchanges: int = 10

    def prepare(self, messages: list[Message], max_tokens: int) -> list[Message]:
        from taui.agent.context import compact_messages
        # Custom logic here. As a skeleton, delegate to the default algorithm.
        compact_messages(messages, max_input_tokens=max_tokens)
        return messages

    def on_turn_result(self, usage: dict[str, Any]) -> None:
        pass  # could track rolling average token usage here


def register(ctx):
    if ctx.context:
        ctx.context.register(KeepRecentStrategy())
```

The strategy must implement the `ContextStrategy` protocol:

```python
class ContextStrategy(Protocol):
    name: str
    def prepare(self, messages: list[Message], max_tokens: int) -> list[Message]: ...
    def on_turn_result(self, usage: dict[str, Any]) -> None: ...
```

---

## 4. Register a Permission Rule

Add tool access rules without editing config files.

```python
# .taui/extensions/my_permissions.py
from taui.permissions import PermissionRuleset


def register(ctx):
    ruleset = PermissionRuleset()
    ruleset.add_rules(
        {
            # Allow all reads, ask before reading .env files
            "read":  {"*": "allow", "*.env": "ask"},
            # Allow safe git commands, ask for anything else
            "bash":  {
                "git status": "allow",
                "git log*":   "allow",
                "git diff*":  "allow",
                "*":          "ask",
            },
            # Allow edits in src/ and tests/, ask elsewhere
            "edit":  {"src/**": "allow", "tests/**": "allow", "*": "ask"},
        },
        layer="project",
    )
    ctx.policy.set_ruleset(ruleset)
```

Layers: `"agent"` (highest priority) → `"project"` → `"global"` (lowest priority).
Actions: `"allow"` (auto-approve) or `"ask"` (confirm). Use `"deny"` to block.

See `docs/permission-dsl.md` for pattern matching semantics.

---

## 5. Register a Hook

Hooks intercept UI rendering, the message pipeline, tool calls, and approval decisions.

```python
# .taui/extensions/my_hooks.py
import logging

logger = logging.getLogger(__name__)


def register(ctx):
    # ── UI hooks ───────────────────────────────────────────────────────────

    # Override the input prompt symbol
    ctx.hooks.prompt(lambda session: "❯ ")

    # Add a line to the startup banner
    ctx.hooks.banner(lambda session: "my-company internal taui build")

    # Add a segment to the status bar
    ctx.hooks.status(lambda session: f"turns:{session._loop._max_turns}")

    # Add a segment to the turn summary
    ctx.hooks.turn_summary(lambda result, session: f"cost:${result.cost_usd:.4f}"
                           if result.cost_usd else None)

    # ── Pipeline hooks ─────────────────────────────────────────────────────

    # Prepend project name to every user message
    def tag_message(message, session):
        return f"[project: acme]\n{message}"

    ctx.hooks.before_send(tag_message)

    # Append a reminder to the system prompt
    ctx.hooks.system_prompt(
        lambda prompt, session: prompt + "\n\nAlways cite file:line references."
    )

    # ── Observer hooks ─────────────────────────────────────────────────────

    async def log_tool_call(name, args, session):
        logger.info("tool_call tool=%s", name)

    ctx.hooks.on_tool_call(log_tool_call)

    async def log_session_start(session):
        logger.info("session_start id=%s", session.session_id)

    ctx.hooks.on_session_start(log_session_start)

    # ── Override hooks ─────────────────────────────────────────────────────

    # Auto-approve read-only tools; defer others to the UI
    def auto_approve(name, args, session):
        if name in ("read", "glob", "grep"):
            return True
        return None  # defer to next hook or TUI prompt

    ctx.hooks.on_approval(auto_approve)
```

See `docs/extension-hooks.md` for the full hook reference and execution semantics.

---

## 6. Register a Slash Command

Slash commands run when the user types `/name` in the input box.

```python
# .taui/extensions/hello_command.py
from dataclasses import dataclass
from taui.commands.registry import CommandContext, CommandResult


@dataclass(slots=True)
class HelloCommand:
    name: str = "hello"
    description: str = "Say hello."

    async def execute(self, cmd_ctx: CommandContext) -> CommandResult:
        who = cmd_ctx.args.strip() or "world"
        return CommandResult.ok(f"Hello, {who}!")


def register(ctx):
    if ctx.commands:
        ctx.commands.register(HelloCommand())
```

`CommandContext` provides:

- `cmd_ctx.args: str` — everything after the command name
- `cmd_ctx.session` — the active `Session`
- `cmd_ctx.app` — the `TauiApp` instance (may be `None` outside TUI)

`CommandResult.ok(text)` renders the text in the chat log.
`CommandResult.fail(text)` renders it as an error.
`CommandResult.metadata` can carry `{"action": "..."}` for TUI-specific side effects.

---

## 7. Register an LLM Provider

Add a new LLM provider (e.g., a local Ollama endpoint, a custom API wrapper).

```python
# .taui/extensions/my_provider.py


class MyProvider:
    """Minimal provider stub."""

    on_text_delta = None
    on_reasoning_delta = None

    async def create_turn(self, messages, model, *, tools=None):
        # Call your LLM API here.
        # Return a ProviderTurnResult-compatible object.
        from taui.llm_provider.types import ProviderTurnResult
        return ProviderTurnResult(
            text="Hello from my provider.",
            tool_calls=[],
            usage=None,
            assistant_metadata={},
        )


def create_my_provider(config):
    return MyProvider()


def register(ctx):
    if ctx.providers:
        ctx.providers.register("my_provider", create_my_provider)
```

Once registered, select it with `uv run taui -p my_provider`.

---

## 8. Bundle a Skill File

Skills are Markdown prompt files loaded on demand by the `skills` tool.

```python
# .taui/extensions/code_review.py

def register(ctx):
    # Path is relative to this .py file
    ctx.skills.add_path("skills/code-review.md")
```

Place the skill at `.taui/extensions/skills/code-review.md`. The agent can then load
it with the `skills` tool when the user requests a code review.

---

## Result Post-Processors

Post-processors transform tool results after execution, before they are written to the
stream. Register them on the session after it is created.

```python
from taui.tools.base import ToolResult
import re

def redact_secrets(tool_name: str, call_id: str, result: ToolResult) -> ToolResult:
    redacted = re.sub(r'(SECRET|TOKEN|PASSWORD)=\S+', r'\1=***', result.content)
    return ToolResult.ok(redacted)

session.add_result_processor(redact_secrets)
```

Post-processors cannot be registered via `register(ctx)` because they require a
`Session` instance. Register them from a hook:

```python
def register(ctx):
    async def on_start(session):
        session.add_result_processor(redact_secrets)

    ctx.hooks.on_session_start(on_start)
```

---

## Quick Reference

| Customization | API |
|---------------|-----|
| Add a tool | `ctx.tools.register(MyTool())` |
| Add an agent variant | `ctx.agents.register(AgentVariant(...))` |
| Add a context strategy | `ctx.context.register(MyStrategy())` |
| Add permission rules | `ctx.policy.set_ruleset(ruleset)` |
| Add a hook | `ctx.hooks.<hook_name>(fn)` or `ctx.hooks.add(name, fn)` |
| Add a slash command | `ctx.commands.register(MyCommand())` |
| Add an LLM provider | `ctx.providers.register(name, factory_fn)` |
| Bundle a skill | `ctx.skills.add_path("skills/my-skill.md")` |
| Post-process results | `session.add_result_processor(fn)` (via `on_session_start` hook) |
