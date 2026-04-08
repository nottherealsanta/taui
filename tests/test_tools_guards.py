from __future__ import annotations

import asyncio
from pathlib import Path

from taui.agent.session import Session
from taui.config.policies import Policy
from taui.config.settings import Settings
from taui.tools.base import ToolContext
from taui.tools.builtins.edit import EditTool
from taui.tools.builtins.read import ReadTool
from taui.tools.builtins.write import WriteTool


def _context(workspace: Path) -> ToolContext:
    return ToolContext(
        working_dir=workspace,
        session=Session(),
        policy=Policy.from_settings(Settings()),
    )


def test_edit_requires_prior_read(tmp_path: Path) -> None:
    file_path = tmp_path / "a.txt"
    file_path.write_text("hello", encoding="utf-8")

    result = asyncio.run(
        EditTool().execute(
            {"filePath": str(file_path), "old_string": "hello", "new_string": "world"},
            _context(tmp_path),
        )
    )

    assert result.error is True
    assert "must read" in result.content


def test_edit_succeeds_after_read(tmp_path: Path) -> None:
    file_path = tmp_path / "b.txt"
    file_path.write_text("hello", encoding="utf-8")
    context = _context(tmp_path)

    read_result = asyncio.run(ReadTool().execute({"filePath": str(file_path)}, context))
    assert read_result.error is False

    edit_result = asyncio.run(
        EditTool().execute(
            {"filePath": str(file_path), "old_string": "hello", "new_string": "world"},
            context,
        )
    )
    assert edit_result.error is False
    assert file_path.read_text(encoding="utf-8") == "world"


def test_write_create_requires_missing_read(tmp_path: Path) -> None:
    file_path = tmp_path / "missing.txt"
    context = _context(tmp_path)

    without_read = asyncio.run(
        WriteTool().execute(
            {
                "filePath": str(file_path),
                "content": "new file",
                "create_if_missing": True,
            },
            context,
        )
    )
    assert without_read.error is True

    read_missing = asyncio.run(ReadTool().execute({"filePath": str(file_path)}, context))
    assert read_missing.error is True

    with_read = asyncio.run(
        WriteTool().execute(
            {
                "filePath": str(file_path),
                "content": "new file",
                "create_if_missing": True,
            },
            context,
        )
    )
    assert with_read.error is False
    assert file_path.read_text(encoding="utf-8") == "new file"
