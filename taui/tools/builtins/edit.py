from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile

from taui.tools.base import ToolContext, ToolResult
from taui.tools.builtins._common import normalize_tool_error, resolve_path


@dataclass(slots=True)
class EditTool:
    name: str = "edit"
    description: str = "Replace exact text in a file"
    schema: dict[str, object] = None  # type: ignore[assignment]
    origin: str = "builtin"

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

        count = original.count(old_string)
        if count == 0:
            return normalize_tool_error("No exact match found for 'old_string'.")
        if count > 1 and not replace_all:
            return normalize_tool_error(
                "Multiple matches found for 'old_string'. Set 'replace_all' to true to replace all matches."
            )

        if replace_all:
            updated = original.replace(old_string, new_string)
            replaced = count
        else:
            updated = original.replace(old_string, new_string, 1)
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
