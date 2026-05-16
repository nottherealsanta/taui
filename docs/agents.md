# Agent Variants

Agent variants are named configuration bundles that change the agent's tool access,
system prompt, model, turn limit, and permission rules without creating a new session.

Source: `taui/agent/variants.py`

## `AgentVariant` Dataclass

```python
@dataclass(slots=True)
class AgentVariant:
    name: str
    description: str = ""
    model: str | None = None          # None = use session default
    system_prompt: str | None = None  # None = use session default
    tool_names: list[str] | None = None  # None = use all tools
    read_only: bool = False           # True = exclude FILE_WRITE/SHELL/GIT tools
    max_turns: int | None = None      # None = use session default
    permission: dict[str, dict[str, str]] = field(default_factory=dict)
```

All fields are optional except `name`. `None` values fall back to the session default.

## Built-In Variants

Two variants are registered at startup:

### `build`

```python
AgentVariant(
    name="build",
    description="Default agent with full tool access.",
)
```

Full tool access. No restrictions. This is the default operating mode.

### `plan`

```python
AgentVariant(
    name="plan",
    description="Read-only agent for planning. Cannot modify files.",
    read_only=True,
    system_prompt=(
        "You are a planning assistant. You can read files and search "
        "the codebase, but you CANNOT modify any files. Your job is to "
        "analyze the codebase and create a detailed plan for the task. "
        "Write the plan as a structured response."
    ),
)
```

`read_only=True` excludes all tools in the `FILE_WRITE`, `SHELL`, and `GIT` categories
from the executor. The agent can read and search but cannot write, edit, run bash, or
use git commands.

## TOML-Based Custom Variants

Place `.toml` files in `.taui/agents/` to define project-local variants. They are
discovered by `AgentVariantRegistry.discover_from_dir()` during `Session.create()`.

```toml
# .taui/agents/reviewer.toml
name = "reviewer"
description = "Code reviewer — reads files and annotates."
read_only = true
system_prompt = """
You are a code reviewer. Read files and provide inline feedback.
Do not modify files. Focus on correctness, clarity, and test coverage.
"""
max_turns = 20

[permission]
read = { "*" = "allow" }
grep = { "*" = "allow" }
```

Supported TOML keys:

| Key | Type | Description |
|-----|------|-------------|
| `name` | string | Variant name (defaults to file stem) |
| `description` | string | Human-readable description |
| `model` | string | Override model identifier |
| `system_prompt` | string | Override system prompt |
| `tools` | list of strings | Explicit tool whitelist |
| `read_only` | bool | Exclude write/shell/git tools |
| `max_turns` | int | Maximum agent turns |
| `[permission]` | table | Tool permission rules (same format as `permission-dsl.md`) |

## Extension Registration

Extensions can register variants via `ctx.agents.register()`:

```python
from taui.agent.variants import AgentVariant

def register(ctx):
    ctx.agents.register(AgentVariant(
        name="security",
        description="Security-focused reviewer. Read-only.",
        read_only=True,
        system_prompt=(
            "You are a security auditor. Identify vulnerabilities, "
            "hardcoded secrets, and unsafe dependencies. Never modify files."
        ),
    ))
```

`ctx.agents` is an `AgentVariantRegistry` instance. Call `register()` with any
`AgentVariant`. The variant is immediately available after `/reload`.

## Switching Variants

`session.switch_variant(name)` applies a variant to the current loop:

```python
ok = session.switch_variant("plan")
# ok is False if the variant name is unknown
```

What `switch_variant` does:

1. Looks up the variant in `_variant_registry`.
2. Builds an effective `ToolRegistry` — either an explicit `tool_names` subset, a
   category-filtered read-only subset, or the full registry.
3. Creates a new `ToolExecutor` from the effective registry and current policy.
4. If the variant has a `permission` table, wraps the policy with a variant-layer
   `PermissionRuleset`.
5. Updates the loop's executor and system prompt in place (no new `AgentLoop` created).

The switch is live immediately — the next message the user sends uses the new variant's
tools and prompt.

## Inspecting Available Variants

```python
registry = session._variant_registry
names = registry.names()        # sorted list of names
all_v = registry.all()          # list[AgentVariant]
v = registry.get("plan")        # AgentVariant | None
```
