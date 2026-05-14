"""notebook_edit — cell-aware edits for .ipynb files."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taui.tools.base import ToolCategory, ToolResult


@dataclass(slots=True)
class NotebookEditTool:
    """Edit Jupyter notebook cells by index."""

    name: str = "notebook_edit"
    description: str = (
        "Edit a Jupyter notebook (.ipynb) cell by index. "
        "Can replace cell source, insert new cells, or delete cells."
    )
    category: ToolCategory = ToolCategory.FILE_WRITE
    schema: dict[str, Any] = field(default=None)
    working_dir: Path = field(default_factory=Path.cwd)

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the .ipynb file",
                    },
                    "cell_index": {
                        "type": "integer",
                        "description": (
                            "0-based index of the cell to edit/delete, "
                            "or insertion point"
                        ),
                    },
                    "action": {
                        "type": "string",
                        "enum": ["replace", "insert", "delete"],
                        "description": (
                            "Action: replace cell content, insert new "
                            "cell, or delete cell"
                        ),
                    },
                    "source": {
                        "type": "string",
                        "description": "New cell source (required for replace/insert)",
                    },
                    "cell_type": {
                        "type": "string",
                        "enum": ["code", "markdown", "raw"],
                        "description": "Cell type for insert (default: code)",
                    },
                },
                "required": ["path", "cell_index", "action"],
                "additionalProperties": False,
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        path_str = arguments.get("path", "")
        cell_index = arguments.get("cell_index")
        action = arguments.get("action", "")
        source = arguments.get("source", "")
        cell_type = arguments.get("cell_type", "code")

        if not path_str:
            return ToolResult.fail("path is required")
        if cell_index is None:
            return ToolResult.fail("cell_index is required")
        if action not in ("replace", "insert", "delete"):
            return ToolResult.fail(f"Unknown action: {action}")

        path = Path(path_str)
        if not path.is_absolute():
            path = self.working_dir / path

        if not path.exists():
            return ToolResult.fail(f"File not found: {path}")
        if not path.suffix == ".ipynb":
            return ToolResult.fail(f"Not a notebook file: {path}")

        try:
            nb = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return ToolResult.fail(f"Failed to read notebook: {exc}")

        cells = nb.get("cells", [])

        if action == "delete":
            if cell_index < 0 or cell_index >= len(cells):
                return ToolResult.fail(
                    f"cell_index {cell_index} out of range (0..{len(cells) - 1})"
                )
            removed = cells.pop(cell_index)
            removed_type = removed.get("cell_type", "unknown")
            path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")
            return ToolResult.ok(
                f"Deleted {removed_type} cell at index {cell_index}. "
                f"Notebook now has {len(cells)} cells."
            )

        if action in ("replace", "insert") and source is None:
            return ToolResult.fail(f"source is required for {action}")

        source_lines = source.split("\n") if source else [""]
        # Ensure each line ends with \n except the last
        formatted = [line + "\n" for line in source_lines[:-1]]
        if source_lines:
            formatted.append(source_lines[-1])

        if action == "replace":
            if cell_index < 0 or cell_index >= len(cells):
                return ToolResult.fail(
                    f"cell_index {cell_index} out of range (0..{len(cells) - 1})"
                )
            cells[cell_index]["source"] = formatted
            path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")
            return ToolResult.ok(
                f"Replaced cell {cell_index} source ({len(source_lines)} lines)."
            )

        # insert
        if cell_index < 0 or cell_index > len(cells):
            return ToolResult.fail(
                f"cell_index {cell_index} out of range for insert (0..{len(cells)})"
            )
        new_cell: dict[str, Any] = {
            "cell_type": cell_type,
            "metadata": {},
            "source": formatted,
        }
        if cell_type == "code":
            new_cell["execution_count"] = None
            new_cell["outputs"] = []
        cells.insert(cell_index, new_cell)
        path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")
        return ToolResult.ok(
            f"Inserted {cell_type} cell at index {cell_index}. "
            f"Notebook now has {len(cells)} cells."
        )
