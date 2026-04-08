"""Find tool — recursive file finder with filters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import fnmatch
from typing import Any

from taui.tools.base import ToolCategory, ToolContext, ToolResult
from taui.tools.builtins._common import normalize_tool_error, resolve_path


@dataclass(slots=True)
class FindTool:
    """Recursively find files with name, type, and size filters."""

    name: str = "find"
    description: str = (
        "Recursively search for files and directories by name pattern, file type, "
        "or size. Like the 'find' command. Results sorted by path."
    )
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.SEARCH

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory to search in (default: workspace root)",
                    },
                    "name": {
                        "type": "string",
                        "description": "Filename glob pattern (e.g. '*.py', 'test_*')",
                    },
                    "type": {
                        "type": "string",
                        "description": "'file' or 'directory' to filter by type",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum directory depth to recurse (default: unlimited)",
                    },
                    "exclude": {
                        "type": "string",
                        "description": "Glob pattern to exclude (e.g. 'node_modules')",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default 200)",
                    },
                },
                "required": [],
            }

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        path_raw = arguments.get("path")
        name_pattern = arguments.get("name")
        type_filter = arguments.get("type")
        max_depth = arguments.get("max_depth")
        exclude_pattern = arguments.get("exclude")
        limit = arguments.get("limit", 200)

        if not isinstance(limit, int) or limit < 1:
            limit = 200

        base = context.working_dir
        if isinstance(path_raw, str):
            try:
                base = resolve_path(context, path_raw)
            except ValueError as exc:
                return normalize_tool_error(str(exc))

        if not base.exists() or not base.is_dir():
            return normalize_tool_error(f"Search path does not exist or is not a directory: {base}")

        results: list[str] = []
        base_depth = len(base.parts)

        # Common directories to skip
        _SKIP_DIRS = {
            ".git", "__pycache__", "node_modules", ".venv", "venv",
            ".mypy_cache", ".pytest_cache", ".tox", "dist", "build",
            ".next", ".nuxt", "target",
        }

        def _walk(directory: Path, current_depth: int) -> None:
            if len(results) >= limit:
                return
            if max_depth is not None and current_depth > max_depth:
                return
            try:
                entries = sorted(directory.iterdir(), key=lambda p: p.name)
            except PermissionError:
                return

            for entry in entries:
                if len(results) >= limit:
                    return

                if entry.name in _SKIP_DIRS and entry.is_dir():
                    continue

                if exclude_pattern and fnmatch.fnmatch(entry.name, exclude_pattern):
                    continue

                matches_name = name_pattern is None or fnmatch.fnmatch(entry.name, name_pattern)
                matches_type = True
                if type_filter == "file":
                    matches_type = entry.is_file()
                elif type_filter == "directory":
                    matches_type = entry.is_dir()

                if matches_name and matches_type:
                    suffix = "/" if entry.is_dir() else ""
                    results.append(str(entry) + suffix)

                if entry.is_dir():
                    _walk(entry, current_depth + 1)

        _walk(base, 0)

        if not results:
            return ToolResult.ok(
                "No files found matching the criteria.",
                metadata={"count": 0, "base": str(base)},
            )

        truncated = len(results) >= limit
        output = "\n".join(results)
        if truncated:
            output += f"\n\n(Results limited to {limit}. Narrow your search.)"

        return ToolResult.ok(
            output,
            metadata={
                "count": len(results),
                "base": str(base),
                "truncated": truncated,
            },
        )
