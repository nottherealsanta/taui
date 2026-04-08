from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile

from taui.tools.base import ToolCategory, ToolContext, ToolResult
from taui.tools.builtins._common import normalize_tool_error, resolve_path


@dataclass(slots=True)
class WriteTool:
    name: str = "write"
    description: str = (
        "Write full file content. The file must have been read first (or attempted "
        "with 'missing' result for new files). Uses atomic write via temp file."
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
                    "content": {"type": "string"},
                    "create_if_missing": {"type": "boolean"},
                },
                "required": ["filePath", "content"],
            }

    async def execute(
        self, arguments: dict[str, object], context: ToolContext
    ) -> ToolResult:
        file_path_raw = arguments.get("filePath")
        content = arguments.get("content")
        create_if_missing = arguments.get("create_if_missing", False)

        if not isinstance(file_path_raw, str):
            return normalize_tool_error(
                "Invalid write arguments: 'filePath' must be a string."
            )
        if not isinstance(content, str):
            return normalize_tool_error(
                "Invalid write arguments: 'content' must be a string."
            )
        if not isinstance(create_if_missing, bool):
            return normalize_tool_error(
                "Invalid write arguments: 'create_if_missing' must be a boolean."
            )

        try:
            path = resolve_path(context, file_path_raw)
        except ValueError as exc:
            return normalize_tool_error(str(exc))

        read_status = context.session.read_status(path)
        if not context.session.has_read(path):
            return normalize_tool_error(f"Error: must read {path} before writing it.")

        if path.exists():
            if not path.is_file():
                return normalize_tool_error(f"Path is not a file: {path}")
        else:
            if not create_if_missing:
                return normalize_tool_error(
                    "Target file is missing. Set 'create_if_missing' to true and read the missing path first."
                )
            if read_status != "missing":
                return normalize_tool_error(
                    f"Creating {path} requires a prior read attempt that returned missing."
                )
            path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, delete=False
            ) as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)
            tmp_path.replace(path)
        except OSError as exc:
            return normalize_tool_error(f"Could not write file: {path} ({exc})")

        return ToolResult.ok(
            f"Wrote {path}",
            metadata={"path": str(path), "bytes": len(content.encode("utf-8"))},
        )
