# Agent Variants

**Section 10.3** | See also: [Permission DSL](permission-dsl.md), `taui/agent/variants.py`

## Overview

Agent variants are named bundles that group together a model selection, system prompt,
tool subset, permission overrides, and a read-only flag. A variant lets you switch the
agent's personality and capability envelope without changing global configuration.

Each variant carries:

| Field | Type | Description |
| --- | --- | --- |
| `name` | `str` | Unique identifier used in `/agent <name>` |
| `description` | `str` | Human-readable label shown in the picker |
| `model` | `str \| None` | Override the active model; `None` inherits the session default |
| `system_prompt` | `str \| None` | Replaces the default system prompt when set |
| `tool_subset` | `list[str] \| None` | Restrict available tools by name; `None` means all tools |
| `permission` | `dict \| None` | Per-variant permission rules layered over project/global rules |
| `read_only` | `bool` | Convenience flag; when `True`, write/edit/bash tools are blocked |

The `AgentVariant` dataclass is defined in `taui/agent/variants.py`.

---

## Built-in Variants

Two variants ship with Taui:

### `build` (default)

Full access. This is the variant that is active when Taui starts.

- No tool restrictions
- No read-only constraint
- Uses the session model and default system prompt

### `plan`

Read-only planning assistant.

- `read_only = True`
- Write, edit, and shell tools are unavailable
- Suitable for exploration and design tasks where accidental file modification is
  undesirable

---

## Defining a Custom Variant

Create a TOML file at `.taui/agents/<name>.toml` inside your project. The file is
discovered automatically when the session starts.

```toml
name = "review"
description = "Code review agent — read-only"
read_only = true
system_prompt = """
You are a code reviewer. Analyze the codebase and provide feedback.
You cannot modify any files.
"""

[permission]
read = { "*" = "allow" }
bash = { "git log *" = "allow", "git diff *" = "allow", "*" = "deny" }
```

The `[permission]` table uses the same DSL as the project-level permission configuration.
See [Permission DSL](permission-dsl.md) for pattern syntax and evaluation order.

Global variants live at `~/.taui/agents/<name>.toml`. Project variants with the same
name override global variants.

---

## Registering a Variant via Extension

Extensions can register variants programmatically through the extension context:

```python
from taui.agent.variants import AgentVariant

def register(ctx):
    ctx.agents.register(
        AgentVariant(
            name="commit",
            description="Git commit assistant — focused on staged changes",
            system_prompt=(
                "You help the user write clear, scoped git commit messages. "
                "Inspect staged changes and propose a commit message. "
                "Do not modify source files."
            ),
            tool_subset=["bash", "read", "glob", "grep"],
            permission={
                "bash": {
                    "git diff --staged": "allow",
                    "git log *": "allow",
                    "git commit *": "allow",
                    "*": "ask",
                },
            },
        )
    )
```

Place this file in `.taui/extensions/commit_variant.py` or
`~/.taui/extensions/commit_variant.py`. See the Extensions section of `AGENTS.md` for
loading rules.

---

## Switching Variants

### Slash command

```
/agent review
```

Switches the active variant to `review` immediately. The session model and tool registry
are updated in place; the conversation history is preserved.

### Keyboard picker

`Ctrl+A` opens the variant picker. Use arrow keys to select and Enter to confirm.

The current variant name is shown in the info bar at the bottom of the TUI.

---

## Recipe Variants

These are ready-to-use variant definitions for common workflows. Copy and adjust as
needed.

### `review` — read-only code review

```toml
name = "review"
description = "Read-only code reviewer"
read_only = true
system_prompt = """
You are a senior code reviewer. Read the codebase and provide structured feedback
covering correctness, clarity, test coverage, and potential edge cases. Do not
modify any files.
"""

[permission]
read  = { "*" = "allow" }
glob  = { "*" = "allow" }
grep  = { "*" = "allow" }
bash  = { "git log *" = "allow", "git diff *" = "allow", "*" = "deny" }
```

### `commit` — git-focused commit helper

```toml
name = "commit"
description = "Writes commit messages from staged changes"
system_prompt = """
You help the user write clear, atomic git commit messages. Inspect the staged diff,
summarize the intent, and propose a conventional-commit message. Ask for confirmation
before running git commit.
"""
tool_subset = ["bash", "read", "glob", "grep"]

[permission]
bash = { "git diff *" = "allow", "git log *" = "allow", "git commit *" = "ask", "*" = "deny" }
read = { "*" = "allow" }
glob = { "*" = "allow" }
grep = { "*" = "allow" }
```

### `pair` — interactive planning partner

```toml
name = "pair"
description = "Interactive planning — asks before acting"
system_prompt = """
You are a pair programming partner. Think out loud, propose a plan, and ask for
confirmation at each step before making changes. Prefer small, reversible edits.
"""

[permission]
bash  = { "*" = "ask" }
write = { "*" = "ask" }
edit  = { "*" = "ask" }
read  = { "*" = "allow" }
glob  = { "*" = "allow" }
grep  = { "*" = "allow" }
```

---

## Reference

- `taui/agent/variants.py` — `AgentVariant` dataclass and variant registry
- `taui/session.py` — variant activation during session composition
- [Permission DSL](permission-dsl.md) — full syntax for the `[permission]` table
- `AGENTS.md` — extensions loading and registration conventions
