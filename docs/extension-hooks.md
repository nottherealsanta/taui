# Extension Lifecycle Hooks

Taui extensions interact with the runtime through hooks — callback functions
registered during extension loading. This document catalogs every hook point.

## Registration

Hooks are registered in `register(ctx)`:

```python
def register(ctx):
    ctx.hooks.add("system_prompt", my_transform)
    ctx.hooks.add("before_send", my_preprocessor)
    ctx.hooks.add("on_tool_call", my_observer)
```

Or using the convenience methods on `ctx.hooks`:

```python
def register(ctx):
    ctx.hooks.system_prompt(lambda prompt, session: prompt + "\nExtra.")
    ctx.hooks.before_send(lambda msg, session: msg.upper())
    ctx.hooks.on_tool_call(lambda name, args, session: print(f"Tool: {name}"))
```

## Hook Categories

### UI Hooks (sync, return `str | None`)

| Hook | Signature | Purpose |
|------|-----------|---------|
| `prompt` | `(session) -> str` | Override the input prompt text |
| `banner` | `(session) -> str` | Add a line to the startup banner |
| `status` | `(session) -> str` | Add a segment to the status bar |
| `turn_summary` | `(result, session) -> str` | Add text to the turn summary line |

### Pipeline Hooks (sync or async, transform data)

| Hook | Signature | Purpose |
|------|-----------|---------|
| `system_prompt` | `(prompt, session) -> prompt` | Transform the system prompt |
| `before_send` | `(message, session) -> message` | Preprocess user input |
| `after_result` | `(result, session) -> result` | Postprocess agent output |

### Observer Hooks (sync or async, side-effects only)

| Hook | Signature | Purpose |
|------|-----------|---------|
| `on_tool_call` | `(name, args, session)` | Called before tool execution |
| `on_tool_result` | `(name, content, is_error, session)` | Called after tool execution |
| `on_session_start` | `(session)` | New session created |
| `on_session_end` | `(session)` | Session closed |
| `on_mode_change` | `(mode, session)` | Mode toggled (normal/extensions/self_edit) |
| `on_compaction` | `(removed, before_tokens, after_tokens, session)` | Context compacted |

### Override Hooks (sync or async, first non-None wins)

| Hook | Signature | Purpose |
|------|-----------|---------|
| `on_approval` | `(name, args, session) -> bool` | Auto-approve or deny tool calls |

## Result Post-Processors

Separate from hooks, `Session.add_result_processor(fn)` registers a function
that transforms every `ToolResult` before it enters the stream:

```python
from taui.tools.base import ToolResult

def redact_secrets(tool_name: str, call_id: str, result: ToolResult) -> ToolResult:
    content = result.content.replace(os.environ.get("API_KEY", ""), "[REDACTED]")
    return ToolResult.ok(content) if not result.error else ToolResult.fail(content)

session.add_result_processor(redact_secrets)
```

## Execution Order

1. `system_prompt` — runs once when building the prompt
2. `before_send` — runs before each user message is sent
3. `on_tool_call` — runs before each tool execution
4. `on_tool_result` — runs after each tool execution
5. Result post-processors — run after tool execution, before stream
6. `after_result` — runs after the full agent run completes

Multiple hooks of the same type run in registration order. Pipeline hooks
chain — each receives the previous hook's output. Observer hooks run
independently; exceptions are logged and swallowed.
