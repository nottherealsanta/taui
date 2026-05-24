# Live Testing via the Embedded MCP Debug Server

`taui --debug` launches the real TUI plus a JSON-RPC server that lets an
external client drive the running app — inject keys, type messages,
take SVG screenshots, query widgets, and (the big one) **replace the
LLM entirely** so every text token, tool call, and error can be
scripted from the outside. The TUI you see is the same code you ship;
only the provider is swapped.

This is the path to use when:

- You want to demo or record taui without spending tokens.
- You want a deterministic UI test that runs the real `app.run()` loop
  (no `run_test()` headless mock).
- You want to assert on what the agent actually sent to the LLM, or
  reproduce a tricky scenario (context overflow, quota error, slow
  streaming, mid-turn tool failure) on demand.

## Architecture

```
┌────────────────────────────┐
│  External client / driver  │
│  (any MCP-speaking process)│
└──────────────┬─────────────┘
               │ newline-delimited JSON-RPC
               ▼
┌────────────────────────────┐
│  Unix socket               │
│  /tmp/taui-debug-<pid>.sock│
└──────────────┬─────────────┘
               │
               ▼
┌────────────────────────────┐
│  DebugServer (bg thread)   │  taui/debug/server.py
│  ── dispatches tools ──    │
└──────────────┬─────────────┘
               │ app.call_from_thread(...)
               ▼
┌────────────────────────────┐
│  Live TauiApp (main thread)│  taui/tui/app.py
│  real session, real loop,  │
│  swap-in ScriptedProvider  │  taui/debug/scripted.py
└────────────────────────────┘
```

The server runs in a background thread inside the same process as the
TUI. All mutations cross the Textual event-loop boundary via
`app.call_from_thread(...)`. Read-only attribute access is safe from any
thread, which is how `wait_idle` and `_is_processing` work.

No new dependencies. The wire format is the same newline-delimited
JSON-RPC that `taui/mcp/__init__.py` already speaks, so any MCP-aware
client (including taui's own) can drive it.

## Launch

```bash
uv run taui --debug --debug-socket /tmp/taui-live.sock
```

Stderr prints:

```
[taui-debug] MCP server listening on /tmp/taui-live.sock
```

`--debug-socket` is optional; without it the socket lands at
`/tmp/taui-debug-{pid}.sock`. The socket is created with mode `0600`.

To test headlessly (no terminal needed, for CI):

```python
from taui.tui.app import TauiApp
from taui.debug.server import DebugServer
from taui.config import Config

app = TauiApp(Config.load(provider="copilot"))
server = DebugServer(app, socket_path="/tmp/test.sock")
server.start()
app.run(headless=True, size=(120, 40))   # blocks; no TTY required
server.stop()
```

That's exactly what `tests/test_debug_mcp.py` and
`tests/test_debug_mcp_scripted.py` do — they fork a headless app in a
subprocess and drive it from the parent.

## Connecting a Client

The protocol is the same MCP JSON-RPC handshake taui uses for outbound
MCP servers. A minimal client:

```python
import asyncio, json
from pathlib import Path

async def main():
    reader, writer = await asyncio.open_unix_connection(
        "/tmp/taui-live.sock", limit=16 * 1024 * 1024,
    )

    async def call(method, params=None):
        msg = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        writer.write((json.dumps(msg) + "\n").encode())
        await writer.drain()
        line = await reader.readline()
        return json.loads(line)["result"]

    await call("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "demo", "version": "0.1"},
    })

    tools = await call("tools/list")
    print([t["name"] for t in tools["tools"]])

asyncio.run(main())
```

The 16 MiB stream limit matters for screenshots — SVG output of a
typical session is ~30–90 KB, well past the default 64 KiB
`StreamReader` buffer. Bumping the limit on both client connect and
the server (`asyncio.start_unix_server(..., limit=...)`) prevents
`LimitOverrunError` on large messages.

Every tool follows the MCP `tools/call` shape:

```json
{
  "jsonrpc": "2.0", "id": 7, "method": "tools/call",
  "params": {"name": "send_message", "arguments": {"text": "hi"}}
}
```

Responses include both `content` (text-only MCP convention) and
`structuredContent` (the raw return value). Code that doesn't care
about MCP compatibility can read `structuredContent` directly.

## Tool Reference

### Control the UI

| Tool | Args | Purpose |
| --- | --- | --- |
| `send_message` | `text`, `wait_for_response=true`, `timeout=60.0` | Type into `#chat-input` and submit. With `wait_for_response`, polls `_is_processing` until idle. |
| `press_key` | `key` (e.g. `enter`, `ctrl+b`, `escape`) | Routes through `app._press_keys`. Same path Textual's own test infra uses. |
| `run_command` | `command` (slash command, with or without leading `/`) | Equivalent to typing a slash command and pressing Enter. |
| `screenshot` | `format="svg"`, optional `title` | Returns the live SVG via `app.export_screenshot()`. Save it, diff it, hand it to a vision model. |
| `wait_idle` | `timeout=30.0` | Blocks until the agent stops processing. |

### Introspect

| Tool | Args | Purpose |
| --- | --- | --- |
| `get_state` | `include=["session","agent"]` (choices: `session`, `messages`, `tools`, `agent`, `widgets`, `cost`) | Snapshot of session id/provider/model, agent processing flag, full widget tree, registered tools, cost tracker. |
| `get_messages` | `last_n?`, `role?` | Pull the conversation history out of `session._loop._messages` in JSON form. |
| `query_widget` | `selector` (Textual CSS), `property?` | Inspect any widget by ID/class — read its `text`, `display`, `value`, anything. |

### Mock the LLM

| Tool | Args | Purpose |
| --- | --- | --- |
| `set_provider_mode` | `mode` ∈ `{"real","scripted"}` | Hot-swap `session._provider` and `loop._llm` to a `ScriptedProvider` (or back). Streaming callbacks survive the swap. |
| `script_push_turn` | one Turn (see below) | Append a turn to the scripted queue. |
| `script_status` | — | Mode, queued turns remaining, `create_turn` call count, plus `last_call` (model, message_count, tool_names, last_user) for assertions. |

**Turn fields** (all optional):

| Field | Type | Notes |
| --- | --- | --- |
| `text` | string | Final assistant text. If empty but `text_deltas` are set, the final text is the join of deltas — same as real streaming providers. |
| `text_deltas` | list[str] | Streamed text chunks. Visible to the TUI as they emit. |
| `reasoning_deltas` | list[str] | Streamed reasoning, rendered above the response. |
| `tool_calls` | list of `{name, arguments[, call_id]}` | Each becomes a `ProviderToolCall` the agent loop executes. |
| `delta_delay` | float (seconds) | Sleep between deltas so streaming is visible. `0.05`–`0.15` looks natural. |
| `usage` | `{input_tokens, output_tokens}` | Surfaces in the cost tracker. |
| `stop_reason` | string | Defaults to `"stop"`; use `"tool_use"` when the turn ends on a tool call. |
| `raises` | string | Named exception to raise *instead of* returning. See "Simulating errors" below. |
| `response_id` | string | Surfaces in `ProviderTurnResult.response_id` (used by some providers). |

When the queue is empty and the agent calls `create_turn`, the
provider waits up to ~5 seconds for a turn to be pushed (so a driver
can react after observing a request), then returns a benign empty turn
so the loop settles instead of hanging.

## Simulating Errors

Pass an exception class name as `raises`. The provider raises an
instance instead of returning a turn — the loop reacts as if the real
provider failed.

| Name | Behavior in the loop |
| --- | --- |
| `ContextOverflowError` | Triggers auto-compaction; if still over the budget, surfaces the error to the user. |
| `QuotaExceededError` | Surfaces "subscription/quota usage limit reached". |
| `TransientProviderError` | Retried per `base.py` retry logic. |
| `ProviderError` | Non-retryable; surfaces the error. |
| `AuthExpiredError` | Surfaces the "delete config and re-login" path. |
| `RuntimeError` | Generic — surfaces as an internal error. |

Anything not in this list becomes a `RuntimeError("Simulated error: <name>")`.

## End-to-End Recipes

### Replay a deterministic turn with streaming

```python
await call("tools/call", {"name": "set_provider_mode", "arguments": {"mode": "scripted"}})
await call("tools/call", {"name": "script_push_turn", "arguments": {
    "text_deltas": ["Hi", " there!", " How", " can", " I", " help?"],
    "delta_delay": 0.1,
}})
await call("tools/call", {"name": "send_message", "arguments": {"text": "hello"}})
```

You'll watch the deltas land one chunk at a time in the live TUI.

### Force a tool call without an LLM

```python
await call("tools/call", {"name": "script_push_turn", "arguments": {
    "tool_calls": [{"name": "read", "arguments": {"path": "README.md"}}],
    "stop_reason": "tool_use",
}})
await call("tools/call", {"name": "script_push_turn", "arguments": {
    "text_deltas": ["Read", " the", " README!"],
    "delta_delay": 0.05,
}})
await call("tools/call", {"name": "send_message", "arguments": {"text": "summarize"}})
```

The agent issues the tool call, executes it for real against the
working directory, feeds the result back into the (scripted) provider,
which then streams the final reply.

### Trigger the question tool

```python
await call("tools/call", {"name": "script_push_turn", "arguments": {
    "tool_calls": [{"name": "question", "arguments": {
        "question": "Where should I deploy first?",
        "options": ["Staging (Recommended)", "Production", "Skip"],
    }}],
    "stop_reason": "tool_use",
}})
await call("tools/call", {"name": "script_push_turn", "arguments": {
    "text_deltas": ["Got", " it —", " proceeding."],
    "delta_delay": 0.05,
}})
await call("tools/call", {"name": "send_message", "arguments": {
    "text": "deploy", "wait_for_response": False,
}})
```

Important: use `wait_for_response: false` for any turn that ends on an
interactive tool like `question`. The driver should poll
`script_status` — `call_count` goes from 1 to 2 after the user answers
in the TUI.

### Assert what the agent sent

```python
status = (await call("tools/call",
    {"name": "script_status", "arguments": {}}))["structuredContent"]

assert status["last_call"]["message_count"] == 2
assert status["last_call"]["last_user"] == "deploy"
assert "read" in status["last_call"]["tool_names"]
```

`script_status` is the only way to observe what the agent built into
the LLM request without monkey-patching anything.

### Simulate an error mid-conversation

```python
await call("tools/call", {"name": "script_push_turn",
    "arguments": {"raises": "ContextOverflowError"}})
await call("tools/call", {"name": "send_message",
    "arguments": {"text": "overflow please"}})
```

The TUI will run its auto-compact path and (if still over) surface
the overflow message to the user. UI behavior is identical to a real
provider raising the same error.

### Mix scripted + real

`set_provider_mode("scripted")` and `set_provider_mode("real")` can be
called any number of times during one session. Useful for tests that
want a few canned interactions then real follow-up exploration.

## File Map

| Path | Role |
| --- | --- |
| `taui/debug/server.py` | Background-thread JSON-RPC server. Handles `initialize`, `tools/list`, `tools/call`, `ping`. Unix socket + 16 MiB buffer for screenshots. |
| `taui/debug/tools.py` | All MCP tool implementations and their schemas. Each handler is sync and crosses the Textual loop via `app.call_from_thread`. |
| `taui/debug/scripted.py` | Runtime `ScriptedProvider`. Duck-types the LLM provider contract the agent loop needs (`create_turn` plus optional `on_text_delta`/`on_reasoning_delta`). |
| `taui/tui/__init__.py:7` | `run_tui(..., debug=, debug_socket=)` — starts/stops the debug server around `app.run()`. |
| `taui/main.py` | `--debug` and `--debug-socket` flags. |
| `tests/test_debug_mcp.py` | End-to-end: launch headless taui in a subprocess, exercise every UI/introspection tool. |
| `tests/test_debug_mcp_scripted.py` | End-to-end: scripted text streaming, scripted tool call against the real `read` tool, mode flip-flop. Zero LLM calls. |

## Pitfalls

- **TUI process predates the code.** If you add a tool to
  `taui/debug/tools.py` or change `ScriptedProvider`, you have to
  restart `taui --debug` for the changes to load — the process
  imported the modules at launch.
- **Subprocess stderr is your friend.** When the headless app dies on
  startup, the launcher subprocess's stderr (captured in the test
  helper, or `~/.taui/.logs` for normal launches) has the traceback.
  Always check it before assuming the socket protocol is wrong.
- **`question` tool blocks the loop.** A scripted `question` tool call
  blocks `create_turn` until the user answers in the TUI. Use
  `wait_for_response: false` on `send_message` and poll `script_status`
  for the answer.
- **Approval-gated tools still ask.** Scripting the LLM doesn't bypass
  approval flow — if a tool requires approval, the TUI prompts the
  user the same way it would for a real LLM-issued call. Use
  `press_key` or `approve` (if/when wired) to drive the prompt.
- **Empty scripted queue waits ~5s.** Push your next turn before the
  agent's next `create_turn`, or expect a settle-with-empty-turn
  fallback after the grace period.
- **Streaming callbacks are attached per-call.** The agent loop wires
  `on_text_delta` / `on_reasoning_delta` on the active provider before
  each turn. `set_provider_mode` preserves the wiring across the swap,
  but custom code that mutates `loop._llm` directly may not — go
  through `set_provider_mode`.

## Why Not `app.run_test()`?

Textual's built-in test harness (`Pilot`) runs the app in headless
mode against the same event loop your test lives in. That works for
isolated unit-style tests but it bypasses startup, session creation,
and the real `app.run()` loop — exactly the pieces most likely to
break in production.

The debug-MCP server runs the actual `app.run()` path in a real
process and lets a peer drive it from outside. Same test ergonomics,
production-equivalent execution.
