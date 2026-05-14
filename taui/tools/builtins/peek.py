"""Peek tool — retrieve windows from truncated tool outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from taui.tools.base import ToolCategory, ToolResult


@dataclass
class PeekTool:
    """Retrieve a section of a previously truncated tool output."""

    name: str = "peek"
    description: str = (
        "Retrieve a section of a previously truncated tool output. "
        "Use the handle from the truncation message to access the full content."
    )
    category: ToolCategory = ToolCategory.FILE_READ
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    # Injected by Session.create()
    _truncation_store: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "handle": {
                        "type": "string",
                        "description": "The truncation handle (e.g., 'tr_abc12345').",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Byte offset to start reading from. Default 0.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max bytes to retrieve. Default 4096.",
                    },
                },
                "required": ["handle"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if self._truncation_store is None:
            return ToolResult.fail("Truncation store not available.")

        handle = arguments.get("handle", "")
        offset = arguments.get("offset", 0)
        limit = arguments.get("limit")

        result = self._truncation_store.peek(handle, offset=offset, limit=limit)
        if result is None:
            return ToolResult.fail(
                f"Handle {handle!r} not found. It may have expired with the session."
            )

        return ToolResult.ok(result)
