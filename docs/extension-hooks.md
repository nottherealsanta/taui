# Extension Hooks

Hooks let extensions customize every aspect of taui without modifying source code.
They are registered via the `hooks` argument in `register(ctx)` and executed by
`HookRegistry` in `taui/hooks.py`.

## `HookRegistry` API

### Registration

```python
# Generic registration — any hook name
hooks.add(name: str, fn: Callable) -> None

# Typed convenience registrars (call hooks.add under the hood)
hooks.prompt(fn)
hooks.banner(fn)
hooks.status(fn)
hooks.turn_summary(fn)
hooks.before_send(fn)
hooks.after_result(fn)
hooks.system_prompt(fn)
hooks.on_tool_call(fn)
hooks.on_tool_result(fn)
hooks.on_session_start(fn)
hooks.on_mode_change(fn)
hooks.on_approval(fn)
```

### Inspection

```python
hooks.has(name: str) -> bool          # True if at least one hook registered
hooks.count(name: str) -> int         # Number of hooks under name
hooks.hook_names -> list[str]         # Sorted list of all registered names
hooks.clear() -> None                 # Remove all hooks (used during /reload)
```

### Execution

All execution methods are `async`. Individual hook errors are logged and skipped —
a broken extension cannot crash the agent.

| Method | Semantics |
|--------|-----------|
| `await hooks.run(name, *args)` | Call all hooks, return list of all results |
| `await hooks.collect(name, *args)` | Like `run`, but filter out `None` results |
| `await hooks.transform(name, value, *args)` | Pipeline — each hook receives and returns `value` |
| `await hooks.first(name, *args)` | Return first non-`None` result |

Sync and async hook functions are both supported. `HookRegistry._call()` awaits
coroutines automatically.

## Hook Categories

### UI Hooks

Sync functions returning `str | None`. Used to customize rendered text.

| Hook | Signature | Purpose |
|------|-----------|---------|
| `prompt` | `(session) -> str \| None` | Override the input prompt text |
| `banner` | `(session) -> str \| None` | Add a line to the startup banner |
| `status` | `(session) -> str \| None` | Add a segment to the status bar |
| `turn_summary` | `(result, session) -> str \| None` | Add a segment to the turn summary line |

Execution: `collect` (non-`None` results gathered and displayed).

### Pipeline Hooks

Sync or async. Each hook receives the current value and must return it (possibly
transformed). Hooks chain in registration order via `transform`.

| Hook | Signature | Purpose |
|------|-----------|---------|
| `system_prompt` | `(prompt: str, session) -> str` | Modify the system prompt after assembly |
| `before_send` | `(message: str, session) -> str` | Transform user input before sending to LLM |
| `after_result` | `(result: RunResult, session) -> RunResult` | Transform the agent's result after each run |

`system_prompt` runs once during `Session.create()` after the `SystemPromptBuilder`
renders the prompt.

`before_send` and `after_result` run on every `session.send()` call.

### Observer Hooks

Sync or async. Return value is ignored. Used for side-effects: logging, metrics,
notifications.

| Hook | Signature | When fired |
|------|-----------|-----------|
| `on_tool_call` | `(name, args, session)` | Before each tool execution |
| `on_tool_result` | `(name, content, is_error, session)` | After each tool execution |
| `on_session_start` | `(session)` | After a new session is created or resumed |
| `on_mode_change` | `(mode: str, session)` | When the session mode changes (normal/extensions/self_edit) |
| `on_compaction` | `(removed, before_tokens, after_tokens, session)` | After context compaction (if registered) |

`on_tool_call` and `on_tool_result` fire from within `AgentLoop._execute_tool()`.
`on_session_start` fires from `session.new_session()`.
`on_mode_change` fires from `session.toggle_extensions_mode()`.

### Override Hooks

Sync or async. First non-`None` return value wins via `first`.

| Hook | Signature | Return | Purpose |
|------|-----------|--------|---------|
| `on_approval` | `(name: str, args: dict, session) -> bool \| None` | `True` = approve, `False` = deny, `None` = defer | Auto-approve or auto-deny tool calls |

`on_approval` is consulted by `AgentLoop._execute_tool()` when a tool returns
`NeedsApproval`. If no hook returns a non-`None` value, the TUI's approval prompt is
shown to the user.

## Result Post-Processors

Post-processors run after each tool execution, before the result is written to the
stream. They are separate from hooks but serve a similar purpose.

```python
session.add_result_processor(fn)
# fn signature: (tool_name: str, call_id: str, result: ToolResult) -> ToolResult
```

Use cases: secret redaction, content tagging, output normalization.

Processors run in registration order. They are wired into `AgentLoop._on_result_process`
by `session._refresh_loop_integrations()`.

## Registering Hooks in Extensions

```python
# .taui/extensions/my_hooks.py

import logging

logger = logging.getLogger(__name__)


def register(ctx):
    # UI: custom prompt symbol
    ctx.hooks.prompt(lambda session: "➜ ")

    # UI: show message count in status bar
    ctx.hooks.status(lambda session: f"msgs:{session._message_count}")

    # Pipeline: prepend context to every user message
    def add_context(message, session):
        return f"[project: my-app]\n{message}"

    ctx.hooks.before_send(add_context)

    # Pipeline: append instructions to the system prompt
    ctx.hooks.system_prompt(
        lambda prompt, session: prompt + "\n\nAlways cite file:line references."
    )

    # Observer: log all tool calls
    async def log_tool_call(name, args, session):
        logger.info("tool_call name=%s", name)

    ctx.hooks.on_tool_call(log_tool_call)

    # Override: auto-approve all read operations
    def auto_approve_reads(name, args, session):
        if name in ("read", "glob", "grep"):
            return True
        return None

    ctx.hooks.on_approval(auto_approve_reads)
```

## Custom Hook Names

You can define arbitrary hooks for inter-extension communication:

```python
# Fire a custom hook
await session.hooks.run("my_custom_event", payload, session)

# Register a handler
ctx.hooks.add("my_custom_event", my_handler)
```
