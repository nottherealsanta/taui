from __future__ import annotations

from dataclasses import dataclass

from taui.tools.base import ToolContext, ToolResult
from taui.tools.builtins._common import (
    format_numbered_lines,
    normalize_tool_error,
    resolve_path,
)


@dataclass(slots=True)
class ReadTool:
    name: str = "read"
    description: str = "Read file contents with line numbers"
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "filePath": {"type": "string"},
                    "offset": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
                "required": ["filePath"],
            }

    async def execute(
        self, arguments: dict[str, object], context: ToolContext
    ) -> ToolResult:
        file_path_raw = arguments.get("filePath")
        if not isinstance(file_path_raw, str) or not file_path_raw:
            return normalize_tool_error(
                "Invalid read arguments: 'filePath' must be a string."
            )

        offset = arguments.get("offset", 0)
        limit = arguments.get("limit", 2000)
        if not isinstance(offset, int) or offset < 0:
            return normalize_tool_error(
                "Invalid read arguments: 'offset' must be a non-negative integer."
            )
        if not isinstance(limit, int) or limit <= 0:
            return normalize_tool_error(
                "Invalid read arguments: 'limit' must be a positive integer."
            )

        try:
            path = resolve_path(context, file_path_raw)
        except ValueError as exc:
            return normalize_tool_error(str(exc))

        if not path.exists():
            context.session.mark_read(path, status="missing")
            return normalize_tool_error(
                f"File not found: {path}",
                metadata={"path": str(path), "status": "missing"},
            )
        if not path.is_file():
            return normalize_tool_error(f"Path is not a file: {path}")

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return normalize_tool_error(f"Could not decode file as UTF-8: {path}")
        except OSError as exc:
            return normalize_tool_error(f"Could not read file: {path} ({exc})")

        lines = text.splitlines()
        chunk = lines[offset : offset + limit]
        context.session.mark_read(path, status="success")
        if not chunk:
            return ToolResult.ok(
                "",
                metadata={
                    "path": str(path),
                    "offset": offset,
                    "limit": limit,
                    "returned_lines": 0,
                    "total_lines": len(lines),
                },
            )

        return ToolResult.ok(
            format_numbered_lines(chunk, start_line=offset + 1),
            metadata={
                "path": str(path),
                "offset": offset,
                "limit": limit,
                "returned_lines": len(chunk),
                "total_lines": len(lines),
                "truncated": offset + limit < len(lines),
            },
        )
