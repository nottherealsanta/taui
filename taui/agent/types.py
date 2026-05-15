"""Shared data types for the agent layer."""

from __future__ import annotations

from dataclasses import dataclass

from taui.llm_provider.types import ProviderToolCall


@dataclass
class Message:
    """A single message in the conversation history."""

    role: str  # system | user | assistant | tool
    content: str | None = None
    tool_calls: list[ProviderToolCall] | None = None
    tool_call_id: str | None = None  # For role="tool" responses
    name: str | None = None  # Tool name for role="tool"
    kind: str = "user"  # "user" | "contextual" | "steer"
    images: list[str] | None = None  # data: URLs for inline images
