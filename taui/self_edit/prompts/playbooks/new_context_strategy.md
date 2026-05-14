# Playbook: Create a Context Strategy

## Goal
Create a custom context strategy as a Python extension.

## Steps

1. Ask the user what compaction behavior they want.
2. Create an extension that registers the strategy.

### Template

```python
from taui.agent.context_strategy import ContextStrategy
from taui.agent.types import Message

class MyStrategy:
    name: str = "<name>"
    description: str = "<purpose>"

    def prepare(self, messages: list[Message]) -> list[Message]:
        """Transform messages before sending to the LLM."""
        # Example: drop all tool results older than 10 messages
        cutoff = max(0, len(messages) - 10)
        return [
            m for i, m in enumerate(messages)
            if i >= cutoff or m.role in ("system", "user")
        ]

    def on_turn_result(self, usage: dict) -> None:
        """React to usage data after a turn."""
        pass

def register(ctx):
    ctx.context.register(MyStrategy())
```

3. Write to `.taui/extensions/<name>_strategy.py`.
4. Tell the user to run `/reload` and configure via `/agent`.
