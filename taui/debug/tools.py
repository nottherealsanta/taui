"""Tool implementations for the embedded debug MCP server.

Each tool is a sync function that receives the live ``TauiApp`` and a
dict of arguments, performs its work, and returns a JSON-serializable
result.

All mutations of the TUI go through ``app.call_from_thread`` so they run
on Textual's event loop. Read-only attribute access is safe from any
thread.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from taui.tui.app import TauiApp


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "send_message",
        "description": "Type text into the chat input and submit it as a user message.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Message to send"},
                "wait_for_response": {
                    "type": "boolean",
                    "default": True,
                    "description": "Block until the agent finishes responding",
                },
                "timeout": {
                    "type": "number",
                    "default": 60.0,
                    "description": "Seconds to wait for the agent to go idle",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "screenshot",
        "description": "Capture the current TUI as SVG.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {"type": "string", "enum": ["svg"], "default": "svg"},
                "title": {"type": "string", "description": "Optional title for the SVG"},
            },
        },
    },
    {
        "name": "get_state",
        "description": "Query the app's internal state.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "session",
                            "messages",
                            "tools",
                            "agent",
                            "widgets",
                            "cost",
                        ],
                    },
                    "default": ["session", "agent"],
                }
            },
        },
    },
    {
        "name": "get_messages",
        "description": "Get the conversation history.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "last_n": {"type": "integer", "description": "Last N only"},
                "role": {
                    "type": "string",
                    "enum": ["user", "assistant", "tool", "system"],
                },
            },
        },
    },
    {
        "name": "press_key",
        "description": "Send a key press to the app (e.g. 'enter', 'ctrl+c', 'escape').",
        "inputSchema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    {
        "name": "run_command",
        "description": "Execute a slash command (e.g. '/clear').",
        "inputSchema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "query_widget",
        "description": "Inspect a widget by Textual CSS selector.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "property": {
                    "type": "string",
                    "description": "Optional widget property to read",
                },
            },
            "required": ["selector"],
        },
    },
    {
        "name": "wait_idle",
        "description": "Block until the agent finishes processing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timeout": {"type": "number", "default": 30.0},
            },
        },
    },
    {
        "name": "set_provider_mode",
        "description": (
            "Swap the live session's LLM provider. mode='scripted' installs a "
            "ScriptedProvider so the external driver can supply text/tool/error "
            "responses via script_push_turn. mode='real' restores the original "
            "provider created at startup. No-op if already in the requested mode."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["real", "scripted"]},
            },
            "required": ["mode"],
        },
    },
    {
        "name": "script_push_turn",
        "description": (
            "Append one scripted LLM turn to the queue. Requires "
            "set_provider_mode('scripted') first. Fields: text (final text), "
            "text_deltas (list of strings streamed before the final), "
            "reasoning_deltas (streamed reasoning chunks), tool_calls "
            "(list of {name, arguments[, call_id]}), delta_delay (seconds "
            "between deltas), raises (exception class name like "
            "'ContextOverflowError' to simulate provider errors), usage "
            "({input_tokens, output_tokens})."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "default": ""},
                "text_deltas": {"type": "array", "items": {"type": "string"}},
                "reasoning_deltas": {"type": "array", "items": {"type": "string"}},
                "tool_calls": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "arguments": {"type": "object"},
                            "call_id": {"type": "string"},
                        },
                        "required": ["name", "arguments"],
                    },
                },
                "delta_delay": {"type": "number", "default": 0.0},
                "raises": {"type": "string"},
                "usage": {
                    "type": "object",
                    "properties": {
                        "input_tokens": {"type": "integer"},
                        "output_tokens": {"type": "integer"},
                    },
                },
                "stop_reason": {"type": "string"},
            },
        },
    },
    {
        "name": "script_status",
        "description": (
            "Inspect the scripted provider: current mode, turns queued/remaining, "
            "create_turn call count, and the messages received on the last call."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# ── Tool implementations ────────────────────────────────────────────────


def _await(app: TauiApp, coro_or_callable, *args, **kwargs):
    """Run a coroutine factory on Textual's loop and block for the result."""
    return app.call_from_thread(coro_or_callable, *args, **kwargs)


def send_message(app: TauiApp, args: dict[str, Any]) -> dict[str, Any]:
    from taui.tui.widgets.chat_input import ChatInput

    text = args.get("text", "")
    wait = bool(args.get("wait_for_response", True))
    timeout = float(args.get("timeout", 60.0))

    def _inject() -> None:
        chat_input = app.query_one("#chat-input", ChatInput)
        chat_input.clear()
        chat_input.insert(text)
        app.post_message(ChatInput.Submitted(text))

    _await(app, _inject)

    if not wait:
        return {"status": "sent", "text": text, "waited": False}

    # Give the loop a moment to flip _is_processing to True
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not app._is_processing:
        time.sleep(0.05)

    deadline = time.monotonic() + timeout
    while app._is_processing:
        if time.monotonic() > deadline:
            return {
                "status": "timeout",
                "text": text,
                "waited": True,
                "still_processing": True,
            }
        time.sleep(0.1)

    return {"status": "sent", "text": text, "waited": True}


def screenshot(app: TauiApp, args: dict[str, Any]) -> dict[str, Any]:
    title = args.get("title")

    def _grab() -> str:
        return app.export_screenshot(title=title) if title else app.export_screenshot()

    svg = _await(app, _grab)
    return {"format": "svg", "content": svg, "length": len(svg)}


def _message_to_dict(msg) -> dict[str, Any]:
    out: dict[str, Any] = {"role": msg.role}
    if msg.content is not None:
        out["content"] = msg.content
    if msg.tool_calls:
        out["tool_calls"] = [
            {
                "id": getattr(tc, "id", None),
                "name": getattr(tc, "name", None),
                "arguments": getattr(tc, "arguments", None),
            }
            for tc in msg.tool_calls
        ]
    if msg.tool_call_id:
        out["tool_call_id"] = msg.tool_call_id
    if msg.name:
        out["name"] = msg.name
    if msg.kind and msg.kind != "user":
        out["kind"] = msg.kind
    return out


def get_state(app: TauiApp, args: dict[str, Any]) -> dict[str, Any]:
    include = args.get("include") or ["session", "agent"]
    include = set(include)

    out: dict[str, Any] = {}
    session = app._session

    if "session" in include:
        if session is None:
            out["session"] = None
        else:
            out["session"] = {
                "session_id": session.session_id,
                "provider": session.provider_name,
                "model": session.model_name,
                "model_variant": getattr(session, "model_variant", None),
                "description": getattr(session, "description", ""),
                "self_edit_mode": getattr(session, "self_edit_mode", False),
            }

    if "messages" in include and session is not None:
        loop = session._loop
        out["messages"] = [_message_to_dict(m) for m in loop._messages]

    if "tools" in include and session is not None:
        registry = getattr(session, "_registry", None)
        if registry is not None:
            try:
                out["tools"] = sorted(registry.names())
            except Exception:
                # Older registries expose `_tools` dict
                out["tools"] = sorted(getattr(registry, "_tools", {}).keys())

    if "agent" in include:
        out["agent"] = {
            "is_processing": app._is_processing,
            "agent_id": (
                str(getattr(session._loop, "agent_id", "") or "") if session else ""
            ),
        }

    if "widgets" in include:

        def _widget_tree() -> list[dict[str, Any]]:
            items: list[dict[str, Any]] = []
            for widget in app.query("*"):
                items.append(
                    {
                        "type": type(widget).__name__,
                        "id": widget.id,
                        "display": bool(getattr(widget, "display", True)),
                        "has_focus": bool(getattr(widget, "has_focus", False)),
                    }
                )
            return items

        out["widgets"] = _await(app, _widget_tree)

    if "cost" in include and session is not None and session.cost_tracker is not None:
        ct = session.cost_tracker
        out["cost"] = {
            "input_tokens": getattr(ct, "input_tokens", 0),
            "output_tokens": getattr(ct, "output_tokens", 0),
            "total_cost_usd": getattr(ct, "total_cost_usd", 0.0),
        }

    return out


def get_messages(app: TauiApp, args: dict[str, Any]) -> dict[str, Any]:
    session = app._session
    if session is None:
        return {"messages": []}
    msgs = [_message_to_dict(m) for m in session._loop._messages]
    role = args.get("role")
    if role:
        msgs = [m for m in msgs if m.get("role") == role]
    last_n = args.get("last_n")
    if last_n is not None:
        try:
            n = int(last_n)
            msgs = msgs[-n:]
        except (TypeError, ValueError):
            pass
    return {"messages": msgs, "count": len(msgs)}


def press_key(app: TauiApp, args: dict[str, Any]) -> dict[str, Any]:
    key = args.get("key", "")

    async def _press() -> None:
        # Textual's App._press_keys is async and accepts a list of key names
        await app._press_keys([key])

    _await(app, _press)
    return {"status": "pressed", "key": key}


def run_command(app: TauiApp, args: dict[str, Any]) -> dict[str, Any]:
    from taui.tui.widgets.chat_input import ChatInput

    command = args.get("command", "")
    if not command.startswith("/"):
        command = "/" + command

    def _inject() -> None:
        chat_input = app.query_one("#chat-input", ChatInput)
        chat_input.clear()
        chat_input.insert(command)
        app.post_message(ChatInput.Submitted(command))

    _await(app, _inject)
    return {"status": "submitted", "command": command}


def query_widget(app: TauiApp, args: dict[str, Any]) -> dict[str, Any]:
    selector = args["selector"]
    prop = args.get("property")

    def _query() -> dict[str, Any]:
        widget = app.query_one(selector)
        info: dict[str, Any] = {
            "type": type(widget).__name__,
            "id": widget.id,
            "display": bool(getattr(widget, "display", True)),
            "visible": bool(getattr(widget, "visible", True)),
            "has_focus": bool(getattr(widget, "has_focus", False)),
        }
        if prop is not None:
            try:
                value = getattr(widget, prop)
                if callable(value):
                    value = value()
                info["property"] = {prop: _safe_repr(value)}
            except Exception as exc:
                info["property"] = {prop: f"<error: {exc}>"}
        return info

    try:
        return _await(app, _query)
    except Exception as exc:
        return {"error": f"Selector failed: {exc}"}


def _safe_repr(value: Any) -> Any:
    """JSON-safe repr — pass primitives through, repr complex types."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_repr(v) for v in value][:50]
    if isinstance(value, dict):
        return {str(k): _safe_repr(v) for k, v in list(value.items())[:50]}
    return repr(value)


# ── Provider mocking ────────────────────────────────────────────────────


def _provider_state(app: TauiApp) -> dict[str, Any]:
    """Lazy slot on the app for the debug server's provider bookkeeping."""
    state = getattr(app, "_debug_provider_state", None)
    if state is None:
        state = {"mode": "real", "original": None, "scripted": None}
        app._debug_provider_state = state  # type: ignore[attr-defined]
    return state


def _install_provider(app: TauiApp, provider: Any) -> None:
    """Wire *provider* into the live session and current agent loop."""
    session = app._session
    if session is None:
        raise RuntimeError("No active session yet — wait for startup")

    loop = session._loop
    prev_text = getattr(loop._llm, "on_text_delta", None) if loop._llm else None
    prev_reasoning = (
        getattr(loop._llm, "on_reasoning_delta", None) if loop._llm else None
    )

    session._provider = provider
    loop._llm = provider
    # Preserve any callbacks the loop had wired on the old provider so
    # streaming deltas keep reaching the TUI.
    provider.on_text_delta = prev_text
    provider.on_reasoning_delta = prev_reasoning


def set_provider_mode(app: TauiApp, args: dict[str, Any]) -> dict[str, Any]:
    from taui.debug.scripted import ScriptedProvider

    mode = args.get("mode", "real")
    state = _provider_state(app)
    session = app._session
    if session is None:
        return {"error": "No active session"}

    if state["original"] is None:
        state["original"] = session._provider

    def _switch() -> dict[str, Any]:
        if mode == "real":
            if state["mode"] == "real":
                return {"mode": "real", "changed": False}
            _install_provider(app, state["original"])
            state["mode"] = "real"
            return {"mode": "real", "changed": True}
        elif mode == "scripted":
            if state["mode"] == "scripted" and state["scripted"] is not None:
                return {"mode": "scripted", "changed": False, "queued": state["scripted"].remaining}
            scripted = ScriptedProvider()
            state["scripted"] = scripted
            _install_provider(app, scripted)
            state["mode"] = "scripted"
            return {"mode": "scripted", "changed": True, "queued": 0}
        else:
            return {"error": f"Unknown mode: {mode}"}

    return _await(app, _switch)


_EXCEPTION_MAP = {
    "ContextOverflowError": (
        "taui.llm_provider.errors",
        "ContextOverflowError",
        ("Simulated context overflow",),
    ),
    "QuotaExceededError": (
        "taui.llm_provider.errors",
        "QuotaExceededError",
        ("Simulated quota exceeded",),
    ),
    "TransientProviderError": (
        "taui.llm_provider.errors",
        "TransientProviderError",
        ("Simulated transient error",),
    ),
    "ProviderError": (
        "taui.llm_provider.errors",
        "ProviderError",
        ("Simulated provider error",),
    ),
    "AuthExpiredError": (
        "taui.llm_provider.errors",
        "AuthExpiredError",
        ("Simulated auth expiry",),
    ),
    "RuntimeError": (None, "RuntimeError", ("Simulated runtime error",)),
}


def _build_exception(name: str) -> BaseException:
    spec = _EXCEPTION_MAP.get(name)
    if spec is None:
        return RuntimeError(f"Simulated error: {name}")
    module_path, cls_name, default_args = spec
    if module_path is None:
        return RuntimeError(*default_args)
    import importlib

    mod = importlib.import_module(module_path)
    cls = getattr(mod, cls_name)
    try:
        return cls(*default_args)
    except TypeError:
        return cls(*default_args)


def script_push_turn(app: TauiApp, args: dict[str, Any]) -> dict[str, Any]:
    from taui.debug.scripted import ScriptedToolCall, Turn
    from taui.llm_provider.types import Usage

    state = _provider_state(app)
    scripted = state.get("scripted")
    if state.get("mode") != "scripted" or scripted is None:
        return {"error": "Not in scripted mode — call set_provider_mode first"}

    raw_calls = args.get("tool_calls") or []
    tool_calls = [
        ScriptedToolCall(
            name=tc["name"],
            arguments=dict(tc.get("arguments") or {}),
            call_id=tc.get("call_id"),
        )
        for tc in raw_calls
    ]

    usage_dict = args.get("usage")
    usage = None
    if usage_dict:
        usage = Usage(
            input_tokens=int(usage_dict.get("input_tokens", 0)),
            output_tokens=int(usage_dict.get("output_tokens", 0)),
        )

    raises_name = args.get("raises")
    raises_exc = _build_exception(raises_name) if raises_name else None

    turn = Turn(
        text=str(args.get("text", "")),
        text_deltas=list(args.get("text_deltas") or []),
        reasoning_deltas=list(args.get("reasoning_deltas") or []),
        tool_calls=tool_calls,
        usage=usage,
        stop_reason=str(args.get("stop_reason", "stop")),
        delta_delay=float(args.get("delta_delay", 0.0) or 0.0),
        raises=raises_exc,
    )
    scripted.add(turn)
    return {
        "queued": 1,
        "remaining": scripted.remaining,
        "call_count": scripted.call_count,
    }


def script_status(app: TauiApp, args: dict[str, Any]) -> dict[str, Any]:
    state = _provider_state(app)
    scripted = state.get("scripted")
    out: dict[str, Any] = {"mode": state.get("mode", "real")}
    if scripted is not None:
        out["remaining"] = scripted.remaining
        out["call_count"] = scripted.call_count
        if scripted.calls:
            last = scripted.calls[-1]
            out["last_call"] = {
                "model": last.model,
                "message_count": len(last.messages),
                "tool_names": (
                    [t.get("function", {}).get("name") or t.get("name") for t in last.tools]
                    if last.tools
                    else []
                ),
                "last_user": next(
                    (
                        m.get("content")
                        if isinstance(m, dict)
                        else getattr(m, "content", None)
                        for m in reversed(last.messages)
                        if (
                            (isinstance(m, dict) and m.get("role") == "user")
                            or getattr(m, "role", None) == "user"
                        )
                    ),
                    None,
                ),
            }
    return out


def wait_idle(app: TauiApp, args: dict[str, Any]) -> dict[str, Any]:
    timeout = float(args.get("timeout", 30.0))
    deadline = time.monotonic() + timeout
    while app._is_processing:
        if time.monotonic() > deadline:
            return {"idle": False, "timed_out": True}
        time.sleep(0.1)
    return {"idle": True, "timed_out": False}


# ── Dispatch table ──────────────────────────────────────────────────────

HANDLERS = {
    "send_message": send_message,
    "screenshot": screenshot,
    "get_state": get_state,
    "get_messages": get_messages,
    "press_key": press_key,
    "run_command": run_command,
    "query_widget": query_widget,
    "wait_idle": wait_idle,
    "set_provider_mode": set_provider_mode,
    "script_push_turn": script_push_turn,
    "script_status": script_status,
}
