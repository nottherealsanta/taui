from __future__ import annotations

import os
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from taui.tools.base import ToolCategory, ToolContext, ToolResult
from taui.tools.builtins._common import (
    format_numbered_lines,
    normalize_tool_error,
    resolve_path,
)

DEFAULT_READ_LIMIT = 2000
MAX_LINE_LENGTH = 2000
MAX_BYTES = 50 * 1024  # 50KB


def _is_binary(data: bytes, sample_size: int = 4096) -> bool:
    """Check if file contents look binary (null bytes or >30% non-printable)."""
    sample = data[:sample_size]
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    non_printable = sum(
        1 for b in sample if b < 9 or (13 < b < 32)
    )
    return non_printable / len(sample) > 0.3


def _suggest_files(directory: Path, target_name: str, max_suggestions: int = 3) -> list[str]:
    """Find similar filenames in directory for 'did you mean?' suggestions."""
    try:
        entries = [e.name for e in directory.iterdir()]
    except OSError:
        return []
    matches = get_close_matches(target_name, entries, n=max_suggestions, cutoff=0.4)
    return [str(directory / m) for m in matches]


@dataclass(slots=True)
class ReadTool:
    name: str = "read"
    description: str = (
        "Read file or directory contents. For files, returns numbered lines with "
        "offset/limit pagination. For directories, lists entries. Output is capped "
        "at 2000 lines or 50KB. Use offset to continue reading large files. "
        "Offset is 1-indexed (first line is 1)."
    )
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.FILE_READ

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "filePath": {
                        "type": "string",
                        "description": "Absolute or relative path to the file or directory to read",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Line number to start from (1-indexed, default 1)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of lines to read (default 2000)",
                    },
                },
                "required": ["filePath"],
            }

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        file_path_raw = arguments.get("filePath")
        if not isinstance(file_path_raw, str) or not file_path_raw:
            return normalize_tool_error(
                "Invalid read arguments: 'filePath' must be a string."
            )

        # 1-indexed offset (default 1)
        offset = arguments.get("offset", 1)
        limit = arguments.get("limit", DEFAULT_READ_LIMIT)
        if not isinstance(offset, int) or offset < 1:
            return normalize_tool_error(
                "Invalid read arguments: 'offset' must be >= 1."
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
            suggestions = _suggest_files(path.parent, path.name)
            msg = f"File not found: {path}"
            if suggestions:
                msg += "\n\nDid you mean one of these?\n" + "\n".join(suggestions)
            return normalize_tool_error(
                msg, metadata={"path": str(path), "status": "missing"},
            )

        # ── Directory listing ──
        if path.is_dir():
            return await self._read_directory(path, offset, limit)

        if not path.is_file():
            return normalize_tool_error(f"Path is not a file or directory: {path}")

        # ── Binary detection ──
        try:
            raw = path.read_bytes()
        except OSError as exc:
            return normalize_tool_error(f"Could not read file: {path} ({exc})")

        if _is_binary(raw):
            context.session.mark_read(path, status="success")
            return normalize_tool_error(
                f"Cannot read binary file: {path}",
                metadata={"path": str(path), "binary": True},
            )

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return normalize_tool_error(f"Could not decode file as UTF-8: {path}")

        lines = text.splitlines()
        total_lines = len(lines)

        # Convert 1-indexed to 0-indexed
        start_idx = offset - 1
        if start_idx >= total_lines and total_lines > 0:
            return normalize_tool_error(
                f"Offset {offset} is beyond end of file ({total_lines} lines total)."
            )

        chunk = lines[start_idx : start_idx + limit]

        # Byte-level truncation
        result_lines: list[str] = []
        total_bytes = 0
        truncated_by_bytes = False
        for line in chunk:
            # Truncate individual long lines
            if len(line) > MAX_LINE_LENGTH:
                line = line[:MAX_LINE_LENGTH] + f"... (line truncated to {MAX_LINE_LENGTH} chars)"
            line_bytes = len(line.encode("utf-8")) + 1  # +1 for newline
            if total_bytes + line_bytes > MAX_BYTES:
                truncated_by_bytes = True
                break
            result_lines.append(line)
            total_bytes += line_bytes

        context.session.mark_read(path, status="success")

        if not result_lines:
            return ToolResult.ok(
                f"<path>{path}</path>\n<type>file</type>\n(End of file - total {total_lines} lines)",
                metadata={
                    "path": str(path),
                    "offset": offset,
                    "limit": limit,
                    "returned_lines": 0,
                    "total_lines": total_lines,
                },
            )

        content = format_numbered_lines(result_lines, start_line=offset)
        last_read_line = offset + len(result_lines) - 1
        has_more = last_read_line < total_lines
        next_offset = last_read_line + 1

        if truncated_by_bytes:
            content += f"\n\n(Output capped at {MAX_BYTES // 1024}KB. Showing lines {offset}-{last_read_line}. Use offset={next_offset} to continue.)"
        elif has_more:
            content += f"\n\n(Showing lines {offset}-{last_read_line} of {total_lines}. Use offset={next_offset} to continue.)"
        else:
            content += f"\n\n(End of file - total {total_lines} lines)"

        return ToolResult.ok(
            content,
            metadata={
                "path": str(path),
                "offset": offset,
                "limit": limit,
                "returned_lines": len(result_lines),
                "total_lines": total_lines,
                "truncated": has_more or truncated_by_bytes,
            },
        )

    async def _read_directory(self, path: Path, offset: int, limit: int) -> ToolResult:
        """List directory entries."""
        try:
            entries: list[str] = []
            for entry in sorted(path.iterdir(), key=lambda p: p.name):
                name = entry.name + "/" if entry.is_dir() else entry.name
                entries.append(name)
        except OSError as exc:
            return normalize_tool_error(f"Could not list directory: {path} ({exc})")

        start_idx = offset - 1
        sliced = entries[start_idx : start_idx + limit]
        truncated = start_idx + len(sliced) < len(entries)

        output_parts = [
            f"<path>{path}</path>",
            "<type>directory</type>",
            "<entries>",
            "\n".join(sliced),
        ]
        if truncated:
            output_parts.append(
                f"\n(Showing {len(sliced)} of {len(entries)} entries. "
                f"Use offset={offset + len(sliced)} to see more.)"
            )
        else:
            output_parts.append(f"\n({len(entries)} entries)")
        output_parts.append("</entries>")

        return ToolResult.ok(
            "\n".join(output_parts),
            metadata={
                "path": str(path),
                "type": "directory",
                "total_entries": len(entries),
                "returned_entries": len(sliced),
                "truncated": truncated,
            },
        )
