"""
taui.tools — tool registration, execution, and policy enforcement.

Tools are the primary way agents interact with the outside world.
The system is designed to be extensible: register any callable that
accepts arguments and returns a ToolResult.
"""

from taui.tools.base import Tool, ToolResult
from taui.tools.executor import ToolExecutor
from taui.tools.registry import ToolRegistry

__all__ = [
    "Tool",
    "ToolExecutor",
    "ToolRegistry",
    "ToolResult",
]
