from __future__ import annotations

from dataclasses import dataclass

from taui.tools.base import ToolCategory, ToolContext, ToolResult
from taui.tools.builtins._common import normalize_tool_error, resolve_path


@dataclass(slots=True)
class GlobTool:
    name: str = "glob"
    description: str = (
        "Find files matching a glob pattern within the workspace. "
        "Results sorted by modification time (newest first)."
    )
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.SEARCH

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["pattern"],
            }

    async def execute(
        self, arguments: dict[str, object], context: ToolContext
    ) -> ToolResult:
        pattern = arguments.get("pattern")
        path_raw = arguments.get("path")
        if not isinstance(pattern, str) or not pattern:
            return normalize_tool_error(
                "Invalid glob arguments: 'pattern' must be a non-empty string."
            )
        if path_raw is not None and not isinstance(path_raw, str):
            return normalize_tool_error(
                "Invalid glob arguments: 'path' must be a string."
            )

        base = context.working_dir
        if isinstance(path_raw, str):
            try:
                base = resolve_path(context, path_raw)
            except ValueError as exc:
                return normalize_tool_error(str(exc))

        if not base.exists() or not base.is_dir():
            return normalize_tool_error(f"Glob base path does not exist: {base}")

        matches = [p for p in base.glob(pattern)]
        matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        rendered = "\n".join(str(path) for path in matches)
        return ToolResult.ok(
            rendered,
            metadata={"count": len(matches), "base": str(base), "pattern": pattern},
        )
