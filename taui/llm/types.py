from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

StreamEventType = Literal[
    "text_delta", "tool_call_delta", "tool_call_done", "done", "error"
]
ToolSchema = dict[str, Any]


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolCall":
        args = data.get("arguments")
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            arguments=args if isinstance(args, dict) else {},
        )


@dataclass(slots=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.tool_calls is not None:
            payload["tool_calls"] = [call.to_dict() for call in self.tool_calls]
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        raw_calls = data.get("tool_calls")
        tool_calls = None
        if isinstance(raw_calls, list):
            tool_calls = [
                ToolCall.from_dict(item) for item in raw_calls if isinstance(item, dict)
            ]
        return cls(
            role=data["role"],
            content=data.get("content"),
            tool_calls=tool_calls,
            tool_call_id=data.get("tool_call_id"),
            name=data.get("name"),
        )


@dataclass(slots=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cost_usd: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StreamEvent:
    type: StreamEventType
    delta: str | None = None
    tool_call: ToolCall | None = None
    usage: Usage | None = None

    @classmethod
    def text_delta(cls, delta: str) -> "StreamEvent":
        return cls(type="text_delta", delta=delta)

    @classmethod
    def tool_call_delta(cls, delta: str) -> "StreamEvent":
        return cls(type="tool_call_delta", delta=delta)

    @classmethod
    def tool_call_done(cls, tool_call: ToolCall) -> "StreamEvent":
        return cls(type="tool_call_done", tool_call=tool_call)

    @classmethod
    def done(cls, usage: Usage | None = None) -> "StreamEvent":
        return cls(type="done", usage=usage)

    @classmethod
    def error(cls, message: str) -> "StreamEvent":
        return cls(type="error", delta=message)
