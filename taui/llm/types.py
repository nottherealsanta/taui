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
        """Serialize to OpenAI Chat Completions API format."""
        import json as _json

        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": _json.dumps(self.arguments),
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolCall":
        # Support both flat format and nested OpenAI format
        func = data.get("function")
        if isinstance(func, dict):
            import json as _json

            name = str(func.get("name", data.get("name", "")))
            raw_args = func.get("arguments", "{}")
            if isinstance(raw_args, str):
                try:
                    args = _json.loads(raw_args)
                except (ValueError, TypeError):
                    args = {}
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}
        else:
            name = str(data.get("name", ""))
            args = data.get("arguments")
            if not isinstance(args, dict):
                args = {}
        return cls(
            id=str(data["id"]),
            name=name,
            arguments=args,
        )


@dataclass(slots=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            payload["content"] = self.content
        if self.tool_calls is not None:
            payload["tool_calls"] = [call.to_dict() for call in self.tool_calls]
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            payload["name"] = self.name
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
