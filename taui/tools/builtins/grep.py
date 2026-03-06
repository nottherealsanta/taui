from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import fnmatch
import re

from taui.tools.base import ToolContext, ToolResult
from taui.tools.builtins._common import normalize_tool_error, resolve_path


@dataclass(slots=True)
class GrepTool:
    name: str = "grep"
    description: str = "Search files by regex pattern"
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                    "include": {"type": "string"},
                },
                "required": ["pattern"],
            }

    async def execute(
        self, arguments: dict[str, object], context: ToolContext
    ) -> ToolResult:
        pattern = arguments.get("pattern")
        path_raw = arguments.get("path")
        include = arguments.get("include")

        if not isinstance(pattern, str) or not pattern:
            return normalize_tool_error(
                "Invalid grep arguments: 'pattern' must be a non-empty string."
            )
        if path_raw is not None and not isinstance(path_raw, str):
            return normalize_tool_error(
                "Invalid grep arguments: 'path' must be a string."
            )
        if include is not None and not isinstance(include, str):
            return normalize_tool_error(
                "Invalid grep arguments: 'include' must be a string."
            )

        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return normalize_tool_error(f"Invalid regex pattern: {exc}")

        base = context.working_dir
        if isinstance(path_raw, str):
            try:
                base = resolve_path(context, path_raw)
            except ValueError as exc:
                return normalize_tool_error(str(exc))

        if not base.exists() or not base.is_dir():
            return normalize_tool_error(f"Grep base path does not exist: {base}")

        results: list[str] = []
        matched_files: set[Path] = set()
        for file_path in base.rglob("*"):
            if not file_path.is_file():
                continue
            if include and not fnmatch.fnmatch(file_path.name, include):
                continue
            try:
                text = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    matched_files.add(file_path)
                    results.append(f"{file_path}:{line_no}| {line}")

        matched_files_sorted = sorted(
            matched_files, key=lambda p: p.stat().st_mtime, reverse=True
        )
        rendered = "\n".join(results)
        return ToolResult.ok(
            rendered,
            metadata={
                "match_count": len(results),
                "file_count": len(matched_files),
                "files": [str(path) for path in matched_files_sorted],
            },
        )
