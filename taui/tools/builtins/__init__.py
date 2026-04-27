"""
taui.tools.builtins — built-in tool implementations.

These are the core tools that ship with Taui. Each tool is a dataclass
implementing the Tool protocol from taui.tools.base.
"""

from taui.tools.builtins.bash import BashTool
from taui.tools.builtins.edit import EditTool
from taui.tools.builtins.files import GlobTool, GrepTool, ReadTool, WriteTool
from taui.tools.registry import ToolRegistry


def register_builtins(registry: ToolRegistry) -> None:
    """Register all built-in tools into a registry."""
    for tool in [
        ReadTool(),
        WriteTool(),
        EditTool(),
        GlobTool(),
        GrepTool(),
        BashTool(),
    ]:
        registry.register(tool)


__all__ = [
    "BashTool",
    "EditTool",
    "GlobTool",
    "GrepTool",
    "ReadTool",
    "WriteTool",
    "register_builtins",
]
