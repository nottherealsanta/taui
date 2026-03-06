"""Built-in tools package."""

from taui.tools.builtins.bash import BashTool
from taui.tools.builtins.edit import EditTool
from taui.tools.builtins.glob import GlobTool
from taui.tools.builtins.grep import GrepTool
from taui.tools.builtins.read import ReadTool
from taui.tools.builtins.write import WriteTool
from taui.tools.registry import ToolRegistry


def register_builtin_tools(registry: ToolRegistry) -> None:
    registry.register(ReadTool())
    registry.register(EditTool())
    registry.register(WriteTool())
    registry.register(BashTool())
    registry.register(GlobTool())
    registry.register(GrepTool())


__all__ = ["register_builtin_tools"]
