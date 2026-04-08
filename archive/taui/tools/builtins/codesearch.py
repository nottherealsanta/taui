"""CodeSearch tool — semantic search using the symbols index."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from taui.tools.base import ToolCategory, ToolContext, ToolResult
from taui.tools.builtins._common import normalize_tool_error


@dataclass(slots=True)
class CodeSearchTool:
    """Search the codebase by symbol name, kind, or scope."""

    name: str = "codesearch"
    description: str = (
        "Search the codebase for symbols (functions, classes, variables) by name, "
        "kind, or scope. Returns symbol locations with source context. Requires "
        "the project to be indexed (runs automatically on first use)."
    )
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.SEARCH

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Symbol name or pattern to search for",
                    },
                    "kind": {
                        "type": "string",
                        "description": "Filter by symbol kind: function, class, variable, method, module",
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": "Glob pattern to filter files (e.g. '*.py', 'src/**/*.ts')",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default 20)",
                    },
                },
                "required": ["query"],
            }

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return normalize_tool_error(
                "Invalid codesearch arguments: 'query' must be a non-empty string."
            )

        kind = arguments.get("kind")
        file_pattern = arguments.get("file_pattern")
        limit = arguments.get("limit", 20)
        if not isinstance(limit, int) or limit < 1:
            limit = 20

        try:
            from taui.symbols import SymbolDB, SymbolIndexer

            db = SymbolDB(str(context.working_dir / ".taui" / "symbols.db"))
            db.migrate()

            # Auto-index if empty
            count = db.search(query, limit=1)
            if not count:
                indexer = SymbolIndexer(str(context.working_dir))
                entries = indexer.index_directory(str(context.working_dir))
                for entry in entries:
                    db.upsert(entry)

            results = db.search(
                query,
                kind=kind,
                file_pattern=file_pattern,
                limit=limit,
            )
        except Exception as exc:
            return normalize_tool_error(f"Code search failed: {exc}")

        if not results:
            return ToolResult.ok(
                f"No symbols found matching '{query}'.",
                metadata={"query": query, "count": 0},
            )

        lines: list[str] = []
        for entry in results:
            loc = f"{entry.file_path}:{entry.line_start}"
            if entry.line_end and entry.line_end != entry.line_start:
                loc += f"-{entry.line_end}"
            line = f"{entry.kind:>10} | {entry.name:<40} | {loc}"
            if entry.scope:
                line += f" (in {entry.scope})"
            lines.append(line)
            if entry.value_preview:
                lines.append(f"{'':>10}   {entry.value_preview}")

        header = f"Found {len(results)} symbol(s) matching '{query}':\n"
        return ToolResult.ok(
            header + "\n".join(lines),
            metadata={
                "query": query,
                "count": len(results),
                "kind": kind,
                "file_pattern": file_pattern,
            },
        )
