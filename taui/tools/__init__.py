"""Tool contracts, registry, and executor."""

from taui.tools.base import Tool, ToolCategory, ToolContext, ToolResult
from taui.tools.builtins import register_builtin_tools
from taui.tools.define import DefinedTool, define_tool
from taui.tools.executor import (
    ExecutionCompleted,
    ExecutionDenied,
    ExecutionOutcome,
    ExecutionRequiresApproval,
    ToolExecutor,
)
from taui.tools.registry import ToolRegistry

__all__ = [
    "DefinedTool",
    "ExecutionCompleted",
    "ExecutionDenied",
    "ExecutionOutcome",
    "ExecutionRequiresApproval",
    "Tool",
    "ToolCategory",
    "ToolContext",
    "ToolExecutor",
    "ToolRegistry",
    "ToolResult",
    "define_tool",
    "register_builtin_tools",
]
