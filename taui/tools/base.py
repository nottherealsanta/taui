from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol

from taui.config.policies import Policy


class ToolCategory(str, Enum):
    """Tool categories for filtering and permission grouping."""

    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    SEARCH = "search"
    SHELL = "shell"
    LSP = "lsp"
    GIT = "git"
    PLAN = "plan"
    SKILL = "skill"
    AGENT = "agent"
    SPEC = "spec"


@dataclass(slots=True)
class ToolResult:
    content: str
    error: bool = False
    metadata: dict[str, Any] | None = None
    attachments: list[dict[str, Any]] | None = None

    @classmethod
    def ok(
        cls,
        content: str,
        metadata: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> "ToolResult":
        return cls(content=content, error=False, metadata=metadata, attachments=attachments)

    @classmethod
    def fail(cls, content: str, metadata: dict[str, Any] | None = None) -> "ToolResult":
        return cls(content=content, error=True, metadata=metadata)


@dataclass(slots=True)
class ToolContext:
    working_dir: Path
    session: Any
    policy: Policy
    abort: asyncio.Event | None = None
    session_id: str | None = None
    agent_name: str | None = None
    metadata_callback: Callable[[dict[str, Any]], None] | None = None


class Tool(Protocol):
    name: str
    description: str
    schema: dict[str, Any]
    origin: str  # "builtin" | "mcp:<server_name>" | "dynamic:<source>"
    category: ToolCategory

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult: ...
