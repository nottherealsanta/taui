"""Tool contracts, registry, and executor."""

from taui.tools.base import Tool, ToolContext, ToolResult
from taui.tools.builtins import register_builtin_tools
from taui.tools.executor import (
    ExecutionCompleted,
    ExecutionDenied,
    ExecutionOutcome,
    ExecutionRequiresApproval,
    ToolExecutor,
)
from taui.tools.registry import ToolRegistry

__all__ = [
    "ExecutionCompleted",
    "ExecutionDenied",
    "ExecutionOutcome",
    "ExecutionRequiresApproval",
    "Tool",
    "ToolContext",
    "ToolExecutor",
    "ToolRegistry",
    "ToolResult",
    "register_builtin_tools",
]
