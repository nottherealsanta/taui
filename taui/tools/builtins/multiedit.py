"""MultiEdit tool — batch multiple edits in one call."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any

from taui.tools.base import ToolCategory, ToolContext, ToolResult
from taui.tools.builtins._common import normalize_tool_error, resolve_path
from taui.tools.builtins.fuzzy_match import find_match


@dataclass(slots=True)
class MultiEditTool:
    """Apply multiple edit operations in a single tool call."""

    name: str = "multiedit"
    description: str = (
        "Apply multiple text replacements across one or more files in a single call. "
        "More efficient than calling 'edit' multiple times. Each edit is "
        "{filePath, old_string, new_string}. Edits within the same file are applied "
        "sequentially."
    )
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.FILE_WRITE

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "filePath": {"type": "string"},
                                "old_string": {"type": "string"},
                                "new_string": {"type": "string"},
                            },
                            "required": ["filePath", "old_string", "new_string"],
                        },
                        "description": "Array of edit operations to apply",
                    },
                },
                "required": ["edits"],
            }

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        edits = arguments.get("edits")
        if not isinstance(edits, list) or not edits:
            return normalize_tool_error(
                "Invalid multiedit arguments: 'edits' must be a non-empty array."
            )

        # Group edits by file path
        by_file: dict[str, list[dict[str, str]]] = {}
        for i, edit in enumerate(edits):
            if not isinstance(edit, dict):
                return normalize_tool_error(f"Edit #{i} is not an object.")
            fp = edit.get("filePath")
            if not isinstance(fp, str):
                return normalize_tool_error(f"Edit #{i}: 'filePath' must be a string.")
            old_s = edit.get("old_string")
            new_s = edit.get("new_string")
            if not isinstance(old_s, str) or not isinstance(new_s, str):
                return normalize_tool_error(
                    f"Edit #{i}: 'old_string' and 'new_string' must be strings."
                )
            by_file.setdefault(fp, []).append({"old": old_s, "new": new_s})

        results: list[str] = []
        total_replacements = 0

        for file_path_raw, file_edits in by_file.items():
            try:
                path = resolve_path(context, file_path_raw)
            except ValueError as exc:
                results.append(f"SKIP {file_path_raw}: {exc}")
                continue

            if context.session.read_status(path) != "success":
                results.append(f"SKIP {file_path_raw}: must read file before editing")
                continue

            if not path.exists():
                results.append(f"SKIP {file_path_raw}: file not found")
                continue

            try:
                content = path.read_text(encoding="utf-8")
            except OSError as exc:
                results.append(f"SKIP {file_path_raw}: {exc}")
                continue

            file_ok = True
            replacements = 0
            for edit in file_edits:
                match = find_match(content, edit["old"])
                if match is None:
                    results.append(f"FAIL {file_path_raw}: no match for old_string")
                    file_ok = False
                    break
                matched_text, count = match
                if count > 1:
                    results.append(
                        f"FAIL {file_path_raw}: multiple matches ({count}). Add more context."
                    )
                    file_ok = False
                    break
                content = content.replace(matched_text, edit["new"], 1)
                replacements += 1

            if not file_ok:
                continue

            try:
                with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", dir=path.parent, delete=False
                ) as tmp:
                    tmp.write(content)
                    tmp_path = Path(tmp.name)
                tmp_path.replace(path)
                results.append(f"OK {path} ({replacements} edits)")
                total_replacements += replacements
            except OSError as exc:
                results.append(f"FAIL {file_path_raw}: could not write: {exc}")

        return ToolResult.ok(
            "\n".join(results),
            metadata={
                "files": len(by_file),
                "total_replacements": total_replacements,
                "results": results,
            },
        )
