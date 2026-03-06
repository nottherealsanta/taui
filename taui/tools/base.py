from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from taui.config.policies import Policy


@dataclass(slots=True)
class ToolResult:
    content: str
    error: bool = False
    metadata: dict[str, Any] | None = None

    @classmethod
    def ok(cls, content: str, metadata: dict[str, Any] | None = None) -> "ToolResult":
        return cls(content=content, error=False, metadata=metadata)

    @classmethod
    def fail(cls, content: str, metadata: dict[str, Any] | None = None) -> "ToolResult":
        return cls(content=content, error=True, metadata=metadata)


@dataclass(slots=True)
class ToolContext:
    working_dir: Path
    session: Any
    policy: Policy


class Tool(Protocol):
    name: str
    description: str
    schema: dict[str, Any]
    origin: str  # "builtin" | "mcp:<server_name>"

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult: ...
