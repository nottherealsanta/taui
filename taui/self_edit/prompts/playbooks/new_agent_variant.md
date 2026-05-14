# Playbook: Create an Agent Variant

## Goal
Scaffold a new agent variant as a `.taui/agents/<name>.toml` file or as a
Python extension that calls `ctx.agents.register(...)`.

## Steps

1. Ask the user for the variant name and purpose.
2. Determine the tool subset (read-only? specific tools?).
3. Choose: TOML config or Python extension.

### TOML variant (`.taui/agents/<name>.toml`)

```toml
name = "<name>"
description = "<purpose>"
read_only = false

# Optional: restrict to specific tools
# tool_names = ["read", "grep", "glob"]

# Optional: custom system prompt
# system_prompt = "You are a code reviewer..."

# Optional: permission overrides
# [permission]
# bash = { "*" = "ask" }
```

### Python extension variant

```python
from taui.agent.variants import AgentVariant

def register(ctx):
    ctx.agents.register(AgentVariant(
        name="<name>",
        description="<purpose>",
        tool_names=["read", "grep", "glob"],
        read_only=True,
    ))
```

4. Write the file.
5. Tell the user to run `/reload` to activate.
