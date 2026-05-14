"""Tests for LspTool."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import pytest

from taui.lsp.types import HoverResult, Location, Position, Range, SymbolInfo
from taui.tools.builtins.lsp import LspTool, _detect_language

# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("foo.py", "python"),
        ("app.ts", "typescript"),
        ("app.tsx", "typescript"),
        ("index.js", "javascript"),
        ("index.jsx", "javascript"),
        ("main.rs", "rust"),
        ("main.go", "go"),
        ("foo.c", "c"),
        ("foo.h", "c"),
        ("foo.cpp", "cpp"),
        ("foo.hpp", "cpp"),
        ("foo.cc", "cpp"),
        ("foo.unknown", None),
        ("no_extension", None),
    ],
)
def test_detect_language(filename: str, expected: str | None) -> None:
    assert _detect_language(filename) == expected


# ---------------------------------------------------------------------------
# No LspManager wired
# ---------------------------------------------------------------------------


async def test_no_lsp_manager_returns_fail() -> None:
    tool = LspTool()
    result = await tool.execute(
        {"action": "goto_definition", "file": "foo.py", "line": 1, "character": 1}
    )
    assert result.error
    assert "not available" in result.content


# ---------------------------------------------------------------------------
# Mock LspManager helpers
# ---------------------------------------------------------------------------


def _make_location() -> Location:
    return Location(
        uri="file:///project/foo.py",
        range=Range(start=Position(line=9, character=4), end=Position(line=9, character=10)),
    )


def _make_symbol() -> SymbolInfo:
    return SymbolInfo(
        name="MyClass",
        kind=5,  # Class
        location=_make_location(),
        container_name=None,
    )


def _make_hover() -> HoverResult:
    return HoverResult(
        contents="```python\ndef foo() -> None\n```",
        range=Range(start=Position(line=9, character=4), end=Position(line=9, character=7)),
    )


@dataclass(slots=True)
class MockLspManager:
    go_to_definition: Any = field(
        default_factory=lambda: AsyncMock(return_value=[_make_location()])
    )
    find_references: Any = field(
        default_factory=lambda: AsyncMock(return_value=[_make_location()])
    )
    hover: Any = field(default_factory=lambda: AsyncMock(return_value=_make_hover()))
    document_symbols: Any = field(
        default_factory=lambda: AsyncMock(return_value=[_make_symbol()])
    )
    workspace_symbols: Any = field(
        default_factory=lambda: AsyncMock(return_value=[_make_symbol()])
    )


# ---------------------------------------------------------------------------
# goto_definition
# ---------------------------------------------------------------------------


async def test_goto_definition() -> None:
    mgr = MockLspManager()
    tool = LspTool()
    tool._lsp_manager = mgr

    result = await tool.execute(
        {"action": "goto_definition", "file": "foo.py", "line": 10, "character": 5}
    )
    assert not result.error
    mgr.go_to_definition.assert_awaited_once_with("python", "foo.py", 10, 5)
    import json
    data = json.loads(result.content)
    assert isinstance(data, list)
    assert data[0]["line"] == 10  # 0-indexed 9 + 1


async def test_goto_definition_missing_params() -> None:
    mgr = MockLspManager()
    tool = LspTool()
    tool._lsp_manager = mgr

    result = await tool.execute({"action": "goto_definition", "file": "foo.py", "line": 1})
    assert result.error
    assert "character" in result.content


# ---------------------------------------------------------------------------
# find_references
# ---------------------------------------------------------------------------


async def test_find_references() -> None:
    mgr = MockLspManager()
    tool = LspTool()
    tool._lsp_manager = mgr

    result = await tool.execute(
        {"action": "find_references", "file": "foo.py", "line": 5, "character": 3}
    )
    assert not result.error
    mgr.find_references.assert_awaited_once_with("python", "foo.py", 5, 3)


# ---------------------------------------------------------------------------
# hover
# ---------------------------------------------------------------------------


async def test_hover() -> None:
    mgr = MockLspManager()
    tool = LspTool()
    tool._lsp_manager = mgr

    result = await tool.execute(
        {"action": "hover", "file": "foo.py", "line": 10, "character": 5}
    )
    assert not result.error
    import json
    data = json.loads(result.content)
    assert "contents" in data


async def test_hover_returns_null_when_no_result() -> None:
    mgr = MockLspManager()
    mgr.hover = AsyncMock(return_value=None)
    tool = LspTool()
    tool._lsp_manager = mgr

    result = await tool.execute(
        {"action": "hover", "file": "foo.py", "line": 1, "character": 1}
    )
    assert not result.error
    import json
    assert json.loads(result.content) is None


# ---------------------------------------------------------------------------
# document_symbols
# ---------------------------------------------------------------------------


async def test_document_symbols() -> None:
    mgr = MockLspManager()
    tool = LspTool()
    tool._lsp_manager = mgr

    result = await tool.execute({"action": "document_symbols", "file": "foo.py"})
    assert not result.error
    mgr.document_symbols.assert_awaited_once_with("python", "foo.py")
    import json
    data = json.loads(result.content)
    assert data[0]["name"] == "MyClass"
    assert data[0]["kind"] == "Class"


async def test_document_symbols_missing_file() -> None:
    mgr = MockLspManager()
    tool = LspTool()
    tool._lsp_manager = mgr

    result = await tool.execute({"action": "document_symbols"})
    assert result.error


# ---------------------------------------------------------------------------
# workspace_symbols
# ---------------------------------------------------------------------------


async def test_workspace_symbols() -> None:
    mgr = MockLspManager()
    tool = LspTool()
    tool._lsp_manager = mgr

    result = await tool.execute(
        {"action": "workspace_symbols", "file": "foo.py", "query": "MyClass"}
    )
    assert not result.error
    mgr.workspace_symbols.assert_awaited_once_with("python", "MyClass")


async def test_workspace_symbols_explicit_language() -> None:
    mgr = MockLspManager()
    tool = LspTool()
    tool._lsp_manager = mgr

    result = await tool.execute(
        {"action": "workspace_symbols", "language": "typescript", "query": "Foo"}
    )
    assert not result.error
    mgr.workspace_symbols.assert_awaited_once_with("typescript", "Foo")


# ---------------------------------------------------------------------------
# Unknown action
# ---------------------------------------------------------------------------


async def test_unknown_action() -> None:
    mgr = MockLspManager()
    tool = LspTool()
    tool._lsp_manager = mgr

    result = await tool.execute({"action": "explode", "file": "foo.py"})
    assert result.error
    assert "Unknown action" in result.content


# ---------------------------------------------------------------------------
# ValueError (unknown language) propagated as fail
# ---------------------------------------------------------------------------


async def test_unknown_language_from_manager() -> None:
    mgr = MockLspManager()
    mgr.go_to_definition = AsyncMock(side_effect=ValueError("No LSP server configured"))
    tool = LspTool()
    tool._lsp_manager = mgr

    result = await tool.execute(
        {"action": "goto_definition", "file": "foo.py", "line": 1, "character": 1}
    )
    assert result.error
    assert "No LSP server" in result.content


# ---------------------------------------------------------------------------
# TimeoutError propagated as fail
# ---------------------------------------------------------------------------


async def test_timeout_error() -> None:
    mgr = MockLspManager()
    mgr.hover = AsyncMock(side_effect=TimeoutError("request timed out"))
    tool = LspTool()
    tool._lsp_manager = mgr

    result = await tool.execute(
        {"action": "hover", "file": "foo.py", "line": 1, "character": 1}
    )
    assert result.error
    assert "timed out" in result.content


# ---------------------------------------------------------------------------
# Auto-language detection failure (no extension, no language param)
# ---------------------------------------------------------------------------


async def test_no_language_detection_fails_gracefully() -> None:
    mgr = MockLspManager()
    tool = LspTool()
    tool._lsp_manager = mgr

    result = await tool.execute(
        {"action": "document_symbols", "file": "Makefile"}
    )
    assert result.error
    assert "language" in result.content.lower()
