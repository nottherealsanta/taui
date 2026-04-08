from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any

from taui.tools.base import ToolCategory, ToolContext, ToolResult
from taui.tools.builtins._common import normalize_tool_error, resolve_path
from taui.tools.builtins.fuzzy_match import find_match


@dataclass(slots=True)
class EditTool:
    name: str = "edit"
    description: str = (
        "Replace text in a file. Uses fuzzy matching to find the target text "
        "even with minor whitespace or indentation differences. The file must "
        "have been read first. Set replace_all=true to replace all occurrences."
    )
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.FILE_WRITE

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "filePath": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                },
                "required": ["filePath", "old_string", "new_string"],
            }

    async def execute(
        self, arguments: dict[str, object], context: ToolContext
    ) -> ToolResult:
        file_path_raw = arguments.get("filePath")
        old_string = arguments.get("old_string")
        new_string = arguments.get("new_string")
        replace_all = arguments.get("replace_all", False)

        if not isinstance(file_path_raw, str):
            return normalize_tool_error(
                "Invalid edit arguments: 'filePath' must be a string."
            )
        if not isinstance(old_string, str):
            return normalize_tool_error(
                "Invalid edit arguments: 'old_string' must be a string."
            )
        if not isinstance(new_string, str):
            return normalize_tool_error(
                "Invalid edit arguments: 'new_string' must be a string."
            )
        if not isinstance(replace_all, bool):
            return normalize_tool_error(
                "Invalid edit arguments: 'replace_all' must be a boolean."
            )

        try:
            path = resolve_path(context, file_path_raw)
        except ValueError as exc:
            return normalize_tool_error(str(exc))

        if context.session.read_status(path) != "success":
            return normalize_tool_error(f"Error: must read {path} before editing it.")
        if not path.exists():
            return normalize_tool_error(f"Cannot edit missing file: {path}")

        try:
            original = path.read_text(encoding="utf-8")
        except OSError as exc:
            return normalize_tool_error(f"Could not read file: {path} ({exc})")

        # Use fuzzy matching chain to find old_string
        match_result = find_match(original, old_string)
        if match_result is None:
            return normalize_tool_error(
                "No match found for 'old_string'. Ensure the text exists in the file.\n"
                "Tip: include enough surrounding context to make the match unique."
            )

        matched_text, match_count = match_result
        if match_count > 1 and not replace_all:
            return normalize_tool_error(
                f"Multiple matches ({match_count}) found for 'old_string'. "
                "Set 'replace_all' to true or add more context to make it unique."
            )

        if replace_all:
            updated = original.replace(matched_text, new_string)
            replaced = original.count(matched_text)
        else:
            updated = original.replace(matched_text, new_string, 1)
            replaced = 1

        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, delete=False
            ) as tmp:
                tmp.write(updated)
                tmp_path = tmp.name
            Path(tmp_path).replace(path)
        except OSError as exc:
            return normalize_tool_error(f"Could not write edited file: {path} ({exc})")

        return ToolResult.ok(
            f"Updated {path} (replacements={replaced}).",
            metadata={"path": str(path), "replacements": replaced},
        )
