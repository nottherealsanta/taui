# Agent Variants

Agent variants are named runtime profiles for model, prompt, tool access, and limits.

## Code

- Variant dataclass: `taui/agent/variants.py:11`
- Builtin registry: `taui/agent/variants.py:24`
- Builtin `build` and `plan`: `taui/agent/variants.py:33`
- TOML loading: `taui/agent/variants.py:64`
- Session application: `taui/session.py:940`

## Fields

| Field | Meaning |
| --- | --- |
| `name` | variant id used by `/agents` or extensions |
| `description` | human-readable summary |
| `model` | optional model override |
| `system_prompt` | optional complete prompt override |
| `tool_names` | optional allow-list of tool names |
| `read_only` | excludes file write, shell, and git tools |
| `max_turns` | optional loop limit |
| `permission` | optional pattern rules for this variant |

## Builtins

- `build`: default full-access profile.
- `plan`: read-only planning profile; excludes mutation categories in
  `Session.switch_variant()`: `taui/session.py:953`.

## TOML

Place project variants in `.taui/agents/<name>.toml`.

```toml
name = "review"
description = "Read-only code review"
read_only = true
max_turns = 20
system_prompt = "Review the code and report issues. Do not edit files."

[permission]
read = { "*" = "allow" }
grep = { "*" = "allow" }
glob = { "*" = "allow" }
```

## Extension Registration

```python
from taui.agent.variants import AgentVariant


def register(ctx):
    ctx.agents.register(AgentVariant(name="review", read_only=True))
```

Use `/agents` to list and activate variants. Command behavior is in
`taui/commands/builtins.py:181`.
