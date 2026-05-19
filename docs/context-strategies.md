# Context Strategies

Context management keeps provider input inside the model token budget.

## Code

- Token estimation and compaction: `taui/agent/context.py:134`
- Default strategy wrapper: `taui/agent/context.py:203`
- Strategy protocol and registry: `taui/agent/context_strategy.py:11`
- Loop integration before provider calls: `taui/agent/loop.py:452`
- Manual compaction command: `taui/commands/builtins.py:50`
- Context UI action: `taui/tui/app.py:3250`

## Default Behavior

The loop estimates message tokens, preserves essential messages, and drops older
non-essential messages when projected input is too large. Compaction emits a notice into
the conversation so the user and model can see that context was reduced:
`taui/agent/loop.py:464`.

Manual `/compact` uses the same context machinery through command metadata and TUI
dispatch: `taui/commands/builtins.py:50`.

## Extension Point

Register a strategy through `ctx.context`:

```python
def register(ctx):
    if ctx.context:
        ctx.context.register(MyStrategy())
```

Strategies should be deterministic, typed, and conservative. Do not drop the latest user
request or the active system prompt.
