"""Convenience factory for creating tools from functions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from taui.tools.base import ToolCategory, ToolContext, ToolResult


@dataclass(slots=True)
class DefinedTool:
    """A tool created via define_tool(). Implements the Tool protocol."""

    name: str
    description: str
    schema: dict[str, Any]
    origin: str
    category: ToolCategory
    _execute_fn: Callable[[dict[str, Any], ToolContext], Awaitable[ToolResult]]

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        return await self._execute_fn(arguments, context)


def define_tool(
    name: str,
    description: str | Path,
    schema: dict[str, Any],
    execute: Callable[[dict[str, Any], ToolContext], Awaitable[ToolResult]],
    *,
    origin: str = "builtin",
    category: ToolCategory = ToolCategory.SEARCH,
) -> DefinedTool:
    """Create a Tool from a function.

    description can be a string or a Path to a .md/.txt file whose
    contents will be read at construction time.
    """
    if isinstance(description, Path):
        desc_text = description.read_text(encoding="utf-8").strip()
    else:
        desc_text = description

    return DefinedTool(
        name=name,
        description=desc_text,
        schema=schema,
        origin=origin,
        category=category,
        _execute_fn=execute,
    )
