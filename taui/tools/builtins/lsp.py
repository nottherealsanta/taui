"""LspTool — LSP operations exposed to the agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from taui.lsp.manager import LspManager
from taui.tools.base import ToolCategory, ToolContext, ToolResult


_OPS = [
    "goToDefinition",
    "findReferences",
    "hover",
    "documentSymbol",
    "workspaceSymbol",
    "goToImplementation",
    "diagnostics",
    "callHierarchy",
]


@dataclass(slots=True)
class LspTool:
    name: str = "lsp"
    description: str = (
        "Interact with a Language Server Protocol server for language-aware code "
        "intelligence. Supported operations:\n"
        "  goToDefinition — jump to the definition of a symbol\n"
        "  findReferences — find all references to a symbol\n"
        "  hover — get type/doc info at a position\n"
        "  documentSymbol — list all symbols in a file\n"
        "  workspaceSymbol — search symbols across the workspace\n"
        "  goToImplementation — jump to implementations of an interface/trait\n"
        "  diagnostics — get compiler errors/warnings for a file\n"
        "  callHierarchy — find callers or callees of a function\n\n"
        "Parameters:\n"
        "  operation (required): one of the operations above\n"
        "  language (required): language id, e.g. 'python', 'typescript', 'rust'\n"
        "  file: relative path to the file (required for most operations)\n"
        "  line: 1-based line number (required for position-based operations)\n"
        "  character: 1-based column (required for position-based operations)\n"
        "  query: search string (for workspaceSymbol)\n"
        "  direction: 'incoming' or 'outgoing' (for callHierarchy, default incoming)"
    )
    schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": _OPS,
                "description": "The LSP operation to perform.",
            },
            "language": {
                "type": "string",
                "description": "Language id (python, typescript, rust, go, c, cpp).",
            },
            "file": {
                "type": "string",
                "description": "Relative file path.",
            },
            "line": {
                "type": "integer",
                "description": "1-based line number.",
            },
            "character": {
                "type": "integer",
                "description": "1-based column number.",
            },
            "query": {
                "type": "string",
                "description": "Search query for workspaceSymbol.",
            },
            "direction": {
                "type": "string",
                "enum": ["incoming", "outgoing"],
                "description": "Direction for callHierarchy.",
            },
        },
        "required": ["operation", "language"],
        "additionalProperties": False,
    })
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.LSP

    # The manager is lazily created per working_dir
    _managers: dict[str, LspManager] = field(default_factory=dict)

    def _get_manager(self, ctx: ToolContext) -> LspManager:
        key = str(ctx.working_dir)
        if key not in self._managers:
            self._managers[key] = LspManager(ctx.working_dir)
        return self._managers[key]

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        op = arguments.get("operation", "")
        lang = arguments.get("language", "")
        file = arguments.get("file", "")
        line = arguments.get("line", 0)
        char = arguments.get("character", 0)
        query = arguments.get("query", "")
        direction = arguments.get("direction", "incoming")

        if op not in _OPS:
            return ToolResult.fail(f"Unknown operation '{op}'. Must be one of: {', '.join(_OPS)}")

        mgr = self._get_manager(context)

        try:
            if op == "goToDefinition":
                locs = await mgr.go_to_definition(lang, file, line, char)
                return _format_locations(locs, "definition")

            elif op == "findReferences":
                locs = await mgr.find_references(lang, file, line, char)
                return _format_locations(locs, "reference")

            elif op == "hover":
                result = await mgr.hover(lang, file, line, char)
                if not result:
                    return ToolResult.ok("No hover information available at this position.")
                return ToolResult.ok(result.contents)

            elif op == "documentSymbol":
                syms = await mgr.document_symbols(lang, file)
                if not syms:
                    return ToolResult.ok("No symbols found.")
                lines = [f"  {s.to_dict()}" for s in syms]
                return ToolResult.ok(f"Symbols in {file}:\n" + "\n".join(lines))

            elif op == "workspaceSymbol":
                syms = await mgr.workspace_symbols(lang, query)
                if not syms:
                    return ToolResult.ok(f"No symbols matching '{query}'.")
                lines = [f"  {s.to_dict()}" for s in syms[:50]]
                return ToolResult.ok(f"Workspace symbols matching '{query}':\n" + "\n".join(lines))

            elif op == "goToImplementation":
                locs = await mgr.go_to_implementation(lang, file, line, char)
                return _format_locations(locs, "implementation")

            elif op == "diagnostics":
                diags = await mgr.diagnostics(lang, file)
                if not diags:
                    return ToolResult.ok(f"No diagnostics for {file}.")
                lines = [d.pretty() for d in diags]
                return ToolResult.ok(f"Diagnostics for {file}:\n" + "\n".join(lines))

            elif op == "callHierarchy":
                calls = await mgr.call_hierarchy(lang, file, line, char, direction=direction)
                if not calls:
                    return ToolResult.ok(f"No {direction} calls found.")
                lines = [f"  {c}" for c in calls]
                return ToolResult.ok(f"{direction.title()} calls:\n" + "\n".join(lines))

            return ToolResult.fail(f"Unhandled operation: {op}")

        except ValueError as exc:
            return ToolResult.fail(str(exc))
        except Exception as exc:
            return ToolResult.fail(f"LSP error: {exc}")


def _format_locations(locs: list, label: str) -> ToolResult:
    if not locs:
        return ToolResult.ok(f"No {label} locations found.")
    lines = [f"  {loc.to_dict()}" for loc in locs]
    return ToolResult.ok(f"Found {len(locs)} {label} location(s):\n" + "\n".join(lines))
