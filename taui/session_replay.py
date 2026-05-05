"""Replay stored session events into agent history and TUI transcript items."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from taui.agent.types import Message
from taui.llm_provider.types import ProviderToolCall
from taui.store.events import Event, EventType


ReplayKind = Literal["user", "assistant", "tool_call", "tool_result", "error"]


@dataclass(frozen=True, slots=True)
class ReplayItem:
    """A compact transcript item for frontends to render after session resume."""

    kind: ReplayKind
    text: str = ""
    name: str = ""
    call_id: str = ""
    arguments: dict[str, Any] | None = None
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class ReplayTranscript:
    """Replay output for both the agent loop and TUI."""

    messages: list[Message]
    items: list[ReplayItem]


@dataclass(frozen=True, slots=True)
class ToolPair:
    """A matched tool call and its result (result is None if not yet returned)."""

    call: ReplayItem
    result: ReplayItem | None


def replay_events(events: list[Event]) -> ReplayTranscript:
    """Convert persisted stream events into loop messages and replay items.

    New streams store assistant tool calls on ASSISTANT_MESSAGE events. Older streams
    only have TOOL_CALL/TOOL_RESULT pairs, so a minimal assistant tool-call message is
    reconstructed when needed before the matching tool result.
    """
    messages: list[Message] = []
    items: list[ReplayItem] = []
    represented_tool_calls: set[str] = set()

    for event in events:
        data = event.data
        if event.type == EventType.USER_MESSAGE:
            text = str(data.get("text", ""))
            messages.append(Message(role="user", content=text))
            items.append(ReplayItem(kind="user", text=text))
        elif event.type == EventType.ASSISTANT_MESSAGE:
            text = str(data.get("text") or "")
            tool_calls = [_tool_call_from_data(raw) for raw in data.get("tool_calls", [])]
            tool_calls = [tc for tc in tool_calls if tc is not None]
            if text or tool_calls:
                messages.append(
                    Message(
                        role="assistant",
                        content=text or None,
                        tool_calls=tool_calls or None,
                    )
                )
            for tc in tool_calls:
                represented_tool_calls.add(tc.call_id)
            if text:
                items.append(ReplayItem(kind="assistant", text=text))
        elif event.type == EventType.TOOL_CALL:
            tc = _tool_call_from_data(data)
            if tc is not None and tc.call_id not in represented_tool_calls:
                messages.append(Message(role="assistant", content=None, tool_calls=[tc]))
                represented_tool_calls.add(tc.call_id)
            items.append(
                ReplayItem(
                    kind="tool_call",
                    name=str(data.get("name", "")),
                    call_id=str(data.get("call_id", "")),
                    arguments=_dict_or_empty(data.get("arguments")),
                )
            )
        elif event.type == EventType.TOOL_RESULT:
            content = str(data.get("content", ""))
            name = str(data.get("name", ""))
            call_id = str(data.get("call_id", ""))
            is_error = bool(data.get("error", False))
            messages.append(
                Message(
                    role="tool",
                    content=content,
                    tool_call_id=call_id or None,
                    name=name or None,
                )
            )
            items.append(
                ReplayItem(
                    kind="tool_result",
                    text=content,
                    name=name,
                    call_id=call_id,
                    is_error=is_error,
                )
            )
        elif event.type == EventType.ERROR:
            items.append(ReplayItem(kind="error", text=str(data.get("error", ""))))

    return ReplayTranscript(messages=messages, items=items)


def serialize_tool_call(tc: ProviderToolCall) -> dict[str, Any]:
    """Serialize a provider tool call in the store's canonical replay shape."""
    return {
        "call_id": tc.call_id,
        "name": tc.name,
        "arguments": tc.arguments,
    }


def _tool_call_from_data(data: Any) -> ProviderToolCall | None:
    if not isinstance(data, dict):
        return None

    if "function" in data and isinstance(data["function"], dict):
        function = data["function"]
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        return ProviderToolCall(
            call_id=str(data.get("id", "")),
            name=str(function.get("name", "")),
            arguments=_dict_or_empty(arguments),
        )

    return ProviderToolCall(
        call_id=str(data.get("call_id", "")),
        name=str(data.get("name", "")),
        arguments=_dict_or_empty(data.get("arguments")),
    )


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
