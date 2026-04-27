"""Base types for the tool system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class ToolCategory(str, Enum):
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
    """

    name: str
    description: str
    schema: dict[str, Any]
    category: ToolCategory

    async def execute(self, arguments: dict[str, Any]) -> ToolResult: ...
