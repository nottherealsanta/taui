"""
Shared types for the LLM provider layer.

These types form the contract between the provider implementations
and the agent loop. Providers convert their wire formats into these
types; the agent loop only sees these.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal


# ── API Format ─────────────────────────────────────────────────────────────────

ApiFormat = Literal["chat_completions", "responses", "messages", "genai"]
"""
Wire format the provider speaks:
- chat_completions: OpenAI /chat/completions (Copilot, OpenAI, OpenRouter, Azure)
- responses: OpenAI /responses (Codex, OpenAI new models)
- messages: Anthropic /messages
- genai: Google GenAI
"""


# ── Reasoning ──────────────────────────────────────────────────────────────────


class ReasoningFormat(str, Enum):
    """How the provider handles reasoning/thinking tokens."""

    NONE = "none"  # No reasoning support
    OPAQUE = "opaque"  # Copilot: reasoning_opaque + reasoning_text in deltas
    ENCRYPTED = "encrypted"  # Codex: reasoning.encrypted_content
    EFFORT_LEVELS = "effort_levels"  # OpenAI: reasoning_effort param
    THINKING_BLOCKS = "thinking_blocks"  # Anthropic: thinking content blocks
    THOUGHT_PARTS = "thought_parts"  # Gemini: parts with thought=true


ThinkingLevel = Literal["minimal", "low", "medium", "high", "max"]


# ── Tool Call ID Formats ───────────────────────────────────────────────────────


class ToolIdFormat(str, Enum):
    """Provider constraints on tool call ID strings."""

    OPENAI_CHAT = "openai_chat"  # max 40, alphanumeric + underscore
    OPENAI_RESPONSES = "openai_responses"  # pipe-separated, very long
    ANTHROPIC = "anthropic"  # max 64, [a-zA-Z0-9_-]+
    MISTRAL = "mistral"  # exactly 9 chars, alphanumeric
    GENERIC = "generic"  # no constraints


_TOOL_ID_MAX_LENGTHS: dict[ToolIdFormat, int] = {
    ToolIdFormat.OPENAI_CHAT: 40,
    ToolIdFormat.OPENAI_RESPONSES: 500,
    ToolIdFormat.ANTHROPIC: 64,
    ToolIdFormat.MISTRAL: 9,
    ToolIdFormat.GENERIC: 256,
}


def normalize_tool_call_id(raw_id: str, target_format: ToolIdFormat) -> str:
    """Normalize a tool call ID for the target provider's constraints."""
    if "|" in raw_id:
        # Responses API pipe-separated format → extract call_id
        raw_id = raw_id.split("|")[0]

    # Sanitize to alphanumeric + underscore + hyphen
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_id)

    # Truncate to provider's max length
    max_len = _TOOL_ID_MAX_LENGTHS.get(target_format, 256)
    if len(sanitized) > max_len:
        sanitized = sanitized[:max_len]

    return sanitized


# ── Stream Events ──────────────────────────────────────────────────────────────

StreamEventType = Literal[
    "text_delta",
    "reasoning_delta",
    "tool_call_start",
    "tool_call_delta",
    "tool_call_done",
    "usage",
    "done",
    "error",
]


@dataclass(slots=True)
class Usage:
    """Token counts and cost for one LLM turn."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ProviderToolCall:
    """A single tool call as returned by the provider."""

    call_id: str
    name: str
    arguments: dict[str, Any]

    def to_chat_completions_format(self) -> dict[str, Any]:
        """Serialize to OpenAI Chat Completions tool_call format."""
        import json

        return {
            "id": self.call_id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments),
            },
        }

    def to_responses_format(self) -> dict[str, Any]:
        """Serialize to OpenAI Responses API function_call format."""
        import json

        return {
            "type": "function_call",
            "call_id": self.call_id,
            "name": self.name,
            "arguments": json.dumps(self.arguments),
        }


@dataclass(slots=True)
class StreamEvent:
    """
    A single event in the normalized stream from any provider.

    The agent loop consumes these uniformly regardless of which
    provider generated them.
    """

    type: StreamEventType
    delta: str | None = None
    tool_call: ProviderToolCall | None = None
    tool_call_index: int | None = None
    tool_call_name: str | None = None
    usage: Usage | None = None
    reasoning_text: str | None = None
    error_message: str | None = None

    # ── Factory methods ────────────────────────────────────────────

    @classmethod
    def text_delta(cls, delta: str) -> StreamEvent:
        return cls(type="text_delta", delta=delta)

    @classmethod
    def reasoning_delta(cls, delta: str) -> StreamEvent:
        return cls(type="reasoning_delta", reasoning_text=delta)

    @classmethod
    def tool_call_start(cls, index: int, call_id: str, name: str) -> StreamEvent:
        return cls(
            type="tool_call_start",
            tool_call_index=index,
            tool_call=ProviderToolCall(call_id=call_id, name=name, arguments={}),
            tool_call_name=name,
        )

    @classmethod
    def tool_call_delta(cls, index: int, arguments_delta: str) -> StreamEvent:
        return cls(type="tool_call_delta", tool_call_index=index, delta=arguments_delta)

    @classmethod
    def tool_call_done(cls, tool_call: ProviderToolCall) -> StreamEvent:
        return cls(type="tool_call_done", tool_call=tool_call)

    @classmethod
    def usage_event(cls, usage: Usage) -> StreamEvent:
        return cls(type="usage", usage=usage)

    @classmethod
    def done(cls, usage: Usage | None = None) -> StreamEvent:
        return cls(type="done", usage=usage)

    @classmethod
    def error(cls, message: str) -> StreamEvent:
        return cls(type="error", error_message=message)


# ── Provider Turn Result ───────────────────────────────────────────────────────


@dataclass(slots=True)
class ProviderTurnResult:
    """
    The complete result of one LLM turn.

    Returned by BaseLLMProvider.create_turn(). Contains the text response,
    any tool calls, token usage, and provider-specific metadata.
    """

    response_id: str | None
    text: str
    tool_calls: list[ProviderToolCall]
    usage: Usage | None = None
    assistant_metadata: dict[str, Any] | None = None
    stop_reason: str = "stop"  # stop | length | tool_use | error

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


# ── Provider Capabilities ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProviderCapabilities:
    """
    Declarative capability matrix for a provider.

    The agent loop checks these to decide what features to use.
    Providers declare these honestly — no runtime probing needed.
    """

    supports_tools: bool = False
    supports_streaming: bool = True
    supports_reasoning: bool = False
    supports_images: bool = False
    supports_cache_control: bool = False
    supports_response_id: bool = False
    supports_developer_role: bool = False  # use "developer" instead of "system"

    reasoning_format: ReasoningFormat = ReasoningFormat.NONE
    tool_call_id_format: ToolIdFormat = ToolIdFormat.GENERIC

    # Provider-specific quirks
    requires_streaming_for_tools: bool = False  # Copilot: non-streaming strips tool_calls
    requires_tool_result_name: bool = False  # Some providers need name on tool results
    requires_assistant_after_tool_result: bool = False  # Anthropic: assistant msg between tool+user
    supports_parallel_tool_calls: bool = True
    supports_strict_tool_schema: bool = False  # OpenAI strict mode


# ── HTTP Request Descriptor ────────────────────────────────────────────────────


@dataclass
class LLMRequest:
    """HTTP request descriptor for a provider API call."""

    url: str
    headers: dict[str, str]
    body: dict[str, Any]  # JSON-serializable


# ── Cost Tracking ──────────────────────────────────────────────────────────────

# Pricing per 1M tokens: (input, output)
_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-opus-4-20250514": (15.00, 75.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "o1": (15.00, 60.00),
    "o1-mini": (3.00, 12.00),
    "o3-mini": (1.10, 4.40),
    "codex-mini": (1.50, 6.00),
    # Google
    "gemini-2.5-pro": (1.25, 5.00),
    "gemini-2.5-flash": (0.15, 0.60),
    # Fallback
    "_default": (3.00, 15.00),
}


def estimate_cost_usd(
    model: str, input_tokens: int, output_tokens: int
) -> float:
    """Estimate cost in USD for a single LLM turn."""
    pricing = _PRICING.get(model)
    if pricing is None:
        for key, val in _PRICING.items():
            if key != "_default" and model.startswith(key):
                pricing = val
                break
    if pricing is None:
        pricing = _PRICING["_default"]

    input_rate, output_rate = pricing
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
