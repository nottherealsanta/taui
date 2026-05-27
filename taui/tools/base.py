"""Base types for the tool system."""

from __future__ import annotations

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
