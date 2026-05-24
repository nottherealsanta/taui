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
]


# ── Tool implementations ────────────────────────────────────────────────


def _await(app: "TauiApp", coro_or_callable, *args, **kwargs):
    """Run a coroutine factory on Textual's loop and block for the result."""
    return app.call_from_thread(coro_or_callable, *args, **kwargs)


def send_message(app: "TauiApp", args: dict[str, Any]) -> dict[str, Any]:
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


def screenshot(app: "TauiApp", args: dict[str, Any]) -> dict[str, Any]:
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


def get_state(app: "TauiApp", args: dict[str, Any]) -> dict[str, Any]:
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


def get_messages(app: "TauiApp", args: dict[str, Any]) -> dict[str, Any]:
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


def press_key(app: "TauiApp", args: dict[str, Any]) -> dict[str, Any]:
    key = args.get("key", "")

    async def _press() -> None:
        # Textual's App._press_keys is async and accepts a list of key names
        await app._press_keys([key])

    _await(app, _press)
    return {"status": "pressed", "key": key}


def run_command(app: "TauiApp", args: dict[str, Any]) -> dict[str, Any]:
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


def query_widget(app: "TauiApp", args: dict[str, Any]) -> dict[str, Any]:
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


def wait_idle(app: "TauiApp", args: dict[str, Any]) -> dict[str, Any]:
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
}
