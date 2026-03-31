from __future__ import annotations

from dataclasses import dataclass

import pytest

from taui.tools.base import ToolContext, ToolResult
from taui.tools.builtins import register_builtin_tools
from taui.tools.registry import Tool, ToolRegistry


@dataclass(slots=True)
class FakeMcpTool(Tool):
    name: str = "mcp__test__do_thing"
    description: str = "fake mcp tool"
    schema: dict[str, object] | None = None
    origin: str = "mcp:test"

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {"type": "object", "properties": {}}

    async def execute(
        self, arguments: dict[str, object], context: ToolContext
    ) -> ToolResult:
        del arguments, context
        return ToolResult.ok("ok")


def test_builtin_origin() -> None:
    registry = ToolRegistry()
    register_builtin_tools(registry)

    for name in registry.names():
        assert registry.get(name).origin == "builtin"


def test_unregister_removes_tool() -> None:
    registry = ToolRegistry()
    register_builtin_tools(registry)

    registry.unregister("glob")
    with pytest.raises(ValueError):
        registry.get("glob")


def test_unregister_unknown_raises() -> None:
    registry = ToolRegistry()
    with pytest.raises(ValueError):
        registry.unregister("unknown")


def test_names_by_origin_builtin() -> None:
    registry = ToolRegistry()
    register_builtin_tools(registry)

    builtin_names = registry.names_by_origin("builtin")
    # All registered tools should have origin="builtin"
    assert len(builtin_names) == len(registry.names())
    # Spot-check some core tools are present
    for name in ("read", "edit", "write", "bash", "glob", "grep", "git", "lsp", "task"):
        assert name in builtin_names, f"Expected '{name}' in builtin tools"


def test_names_by_origin_mcp_prefix() -> None:
    registry = ToolRegistry()
    register_builtin_tools(registry)
    registry.register(FakeMcpTool())

    assert registry.names_by_origin("mcp:") == ("mcp__test__do_thing",)
    assert "mcp__test__do_thing" not in registry.names_by_origin("builtin")
