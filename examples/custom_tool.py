"""Example: custom tool as a taui extension.

A simple tool that counts lines in a file, demonstrating
the tool protocol and extension registration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taui.tools.base import ToolCategory, ToolResult


@dataclass(slots=True)
class LineCountTool:
    name: str = "line_count"
    description: str = "Count lines in a file."
    category: ToolCategory = ToolCategory.FILE_READ
    working_dir: Path = field(default_factory=Path.cwd)
    schema: dict[str, Any] = field(default=None)

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to count",
                    },
                },
                "required": ["path"],
            }

    async def execute(
        self, arguments: dict[str, Any]
    ) -> ToolResult:
        path = Path(arguments.get("path", ""))
        if not path.is_absolute():
            path = self.working_dir / path
        if not path.is_file():
            return ToolResult.fail(f"Not a file: {path}")
        try:
            lines = path.read_text().count("\n")
            return ToolResult.ok(
                f"{path.name}: {lines} lines",
                lines=lines,
            )
        except Exception as exc:
            return ToolResult.fail(str(exc))


def register(ctx):
    ctx.tools.register(LineCountTool())
