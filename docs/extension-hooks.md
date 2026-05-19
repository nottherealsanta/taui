# Extension Hooks

Hooks let extensions observe or transform selected runtime events without editing core
code.

## Registry

- Registry type: `taui/hooks.py:46`
- Add handler: `taui/hooks.py:54`
- Run handlers: `taui/hooks.py:120`
- Transform pipeline helper: `taui/hooks.py:88`

Hook failures are logged and isolated by the registry. Do not rely on a hook exception to
stop the agent.

## Common Hooks

| Hook | Shape | Use |
| --- | --- | --- |
| `system_prompt` | `(prompt, session) -> str` | append or rewrite system prompt text |
| `on_tool_call` | `(name, args, session) -> None` | observe requested tools |
| `on_tool_result` | `(name, content, is_error, session) -> None` | observe tool results |
| `on_approval` | `(name, args, session) -> bool | None` | approve, deny, or defer |

Session prompt rebuild applies the `system_prompt` hook at
`taui/session.py:619`. Tool approval hooks are consulted by `ToolExecutor` through the
approval callback path in `taui/tools/executor.py:219`.

## Example

```python
def add_prompt_note(prompt, session):
    return prompt + "\nPrefer small, reviewed patches."


def register(ctx):
    ctx.hooks.add("system_prompt", add_prompt_note)
```

Keep hooks deterministic when possible. Hooks can affect every turn in a session.
