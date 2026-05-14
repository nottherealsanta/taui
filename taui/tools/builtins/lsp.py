"""LSP tool — expose LSP operations (goto_definition, find_references, hover, symbols)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taui.tools.base import ToolCategory, ToolResult

# Map file extensions to LSP language ids.
_EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
}

_ACTIONS = ("goto_definition", "find_references", "hover", "document_symbols", "workspace_symbols")


def _detect_language(file: str) -> str | None:
    suffix = Path(file).suffix.lower()
    return _EXT_TO_LANGUAGE.get(suffix)


@dataclass
class LspTool:
    """LSP-backed navigation and inspection tool."""

    name: str = "lsp"
    description: str = (
        "Perform LSP operations on source files: goto_definition, find_references, hover, "
        "document_symbols, workspace_symbols. Requires a language server to be installed "
        "for the target language."
    )
    category: ToolCategory = ToolCategory.SEARCH
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    # Injected by Session.create()
    _lsp_manager: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": list(_ACTIONS),
                        "description": (
                            "LSP action to perform: goto_definition, find_references, hover, "
                            "document_symbols, or workspace_symbols."
                        ),
                    },
                    "file": {
                        "type": "string",
                        "description": (
                            "Path to the source file (relative to the working directory). "
                            "Required for all actions except workspace_symbols."
                        ),
                    },
                    "line": {
                        "type": "integer",
                        "description": (
                            "1-indexed line number. Required for position-based actions."
                        ),
                    },
                    "character": {
                        "type": "integer",
                        "description": (
                            "1-indexed character (column) offset. "
                            "Required for position-based actions."
                        ),
                    },
                    "language": {
                        "type": "string",
                        "description": (
                            "Language id (e.g. python, typescript, rust). "
                            "Auto-detected from file extension when omitted."
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": "Symbol query string. Used by workspace_symbols.",
                    },
                },
                "required": ["action"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if self._lsp_manager is None:
            return ToolResult.fail("LSP manager is not available in this session.")

        action = arguments.get("action", "")
        if action not in _ACTIONS:
            return ToolResult.fail(
                f"Unknown action {action!r}. Valid actions: {', '.join(_ACTIONS)}"
            )

        file: str | None = arguments.get("file")
        line: int | None = arguments.get("line")
        character: int | None = arguments.get("character")
        query: str = arguments.get("query", "")
        language: str | None = arguments.get("language")

        # Resolve language
        if not language and file:
            language = _detect_language(file)
        if not language:
            return ToolResult.fail(
                "Could not determine language. Provide the 'language' parameter explicitly or "
                "use a file with a recognised extension (.py, .ts, .js, .rs, .go, .c, .cpp, ...)."
            )

        try:
            if action == "goto_definition":
                if not file or line is None or character is None:
                    return ToolResult.fail(
                        "goto_definition requires 'file', 'line', and 'character'."
                    )
                locations = await self._lsp_manager.go_to_definition(
                    language, file, line, character
                )
                return ToolResult.ok(json.dumps([loc.to_dict() for loc in locations], indent=2))

            elif action == "find_references":
                if not file or line is None or character is None:
                    return ToolResult.fail(
                        "find_references requires 'file', 'line', and 'character'."
                    )
                locations = await self._lsp_manager.find_references(
                    language, file, line, character
                )
                return ToolResult.ok(json.dumps([loc.to_dict() for loc in locations], indent=2))

            elif action == "hover":
                if not file or line is None or character is None:
                    return ToolResult.fail("hover requires 'file', 'line', and 'character'.")
                result = await self._lsp_manager.hover(language, file, line, character)
                if result is None:
                    return ToolResult.ok(json.dumps(None))
                return ToolResult.ok(json.dumps(result.to_dict(), indent=2))

            elif action == "document_symbols":
                if not file:
                    return ToolResult.fail("document_symbols requires 'file'.")
                symbols = await self._lsp_manager.document_symbols(language, file)
                return ToolResult.ok(json.dumps([s.to_dict() for s in symbols], indent=2))

            elif action == "workspace_symbols":
                symbols = await self._lsp_manager.workspace_symbols(language, query)
                return ToolResult.ok(json.dumps([s.to_dict() for s in symbols], indent=2))

        except ValueError as exc:
            return ToolResult.fail(str(exc))
        except TimeoutError as exc:
            return ToolResult.fail(f"LSP request timed out: {exc}")
        except Exception as exc:
            # Catch LspError and any other unexpected server errors.
            return ToolResult.fail(f"LSP error: {exc}")

        # Should never reach here, but satisfy the type checker.
        return ToolResult.fail(f"Unhandled action: {action}")
