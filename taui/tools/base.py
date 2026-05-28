"""Base types for the tool system."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class ToolCategory(StrEnum):
    """Broad categories for filtering and default policy grouping."""

    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    SEARCH = "search"
    SHELL = "shell"
    GIT = "git"
    AGENT = "agent"
    MEMORY = "memory"
    QUESTION = "question"


ToolOutputDeltaCallback = Callable[[str], Awaitable[None] | None]

_TOOL_OUTPUT_DELTA_CALLBACK: ContextVar[ToolOutputDeltaCallback | None] = (
    ContextVar("tool_output_delta_callback", default=None)
)


def set_tool_output_delta_callback(
    callback: ToolOutputDeltaCallback | None,
) -> Token[ToolOutputDeltaCallback | None]:
    """Install a per-execution callback for live tool output chunks."""
    return _TOOL_OUTPUT_DELTA_CALLBACK.set(callback)


def reset_tool_output_delta_callback(
    token: Token[ToolOutputDeltaCallback | None],
) -> None:
    _TOOL_OUTPUT_DELTA_CALLBACK.reset(token)


async def emit_tool_output_delta(chunk: str) -> None:
    """Emit a live output chunk for tools that support streaming output."""
    callback = _TOOL_OUTPUT_DELTA_CALLBACK.get()
    if callback is None or not chunk:
        return
    maybe_awaitable = callback(chunk)
    if maybe_awaitable is not None:
        await maybe_awaitable


@dataclass(slots=True)
class ToolResult:
    """The output of a tool execution."""

    content: str
    error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, content: str, **metadata: Any) -> ToolResult:
        return cls(content=content, error=False, metadata=metadata)

    @classmethod
    def fail(cls, content: str, **metadata: Any) -> ToolResult:
        return cls(content=content, error=True, metadata=metadata)


class Tool(Protocol):
    """Interface every tool must satisfy.

    Tools can be plain classes, dataclasses, or anything that has
    these attributes and an async execute method.

    `group` is optional; tools without a group are treated as their own
    single-member group by the registry's grouping helpers.
    """

    name: str
    description: str
    schema: dict[str, Any]
    category: ToolCategory
    group: str | None

    async def execute(self, arguments: dict[str, Any]) -> ToolResult: ...


def tool_group(tool: Any) -> str:
    """Return a tool's group, falling back to its name for solo tools."""
    g = getattr(tool, "group", None)
    return str(g).strip() if g else str(getattr(tool, "name", ""))
