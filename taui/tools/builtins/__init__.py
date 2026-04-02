"""Built-in tools package."""

from taui.tools.builtins.agents import LaunchMinionTool, LaunchRootTool
from taui.tools.builtins.apply_patch import ApplyPatchTool
from taui.tools.builtins.bash import BashTool
from taui.tools.builtins.codesearch import CodeSearchTool
from taui.tools.builtins.edit import EditTool
from taui.tools.builtins.find import FindTool
from taui.tools.builtins.git import GitTool
from taui.tools.builtins.glob import GlobTool
from taui.tools.builtins.grep import GrepTool
from taui.tools.builtins.lsp import LspTool
from taui.tools.builtins.monty import MontyTool
from taui.tools.builtins.multiedit import MultiEditTool
from taui.tools.builtins.plan import PlanTool
from taui.tools.builtins.question import QuestionTool
from taui.tools.builtins.read import ReadTool
from taui.tools.builtins.skill import SkillTool
from taui.tools.builtins.skill_import import SkillImportTool
from taui.tools.builtins.task import TaskTool
from taui.tools.builtins.todo import TodoWriteTool
from taui.tools.builtins.tool_search import tool_search
from taui.tools.builtins.write import WriteTool
from taui.tools.registry import ToolRegistry


def register_builtin_tools(registry: ToolRegistry) -> None:
    """Register all built-in tools into the given registry."""
    # Core file tools
    registry.register(ReadTool())
    registry.register(EditTool())
    registry.register(WriteTool())
    registry.register(ApplyPatchTool())
    registry.register(MultiEditTool())

    # Search tools
    registry.register(GlobTool())
    registry.register(GrepTool())
    registry.register(FindTool())
    registry.register(CodeSearchTool())

    # Shell
    registry.register(BashTool())

    # Git
    registry.register(GitTool())

    # LSP
    registry.register(LspTool())

    # Planning & coordination
    registry.register(PlanTool())
    registry.register(TodoWriteTool())
    registry.register(QuestionTool())

    # Skills
    registry.register(SkillTool())
    registry.register(SkillImportTool())

    # Agent — sub-agent task tool (for root agents)
    registry.register(TaskTool())

    # Agent — Prime agent-launching tools
    registry.register(LaunchMinionTool())
    registry.register(LaunchRootTool())

    # Programmatic
    registry.register(MontyTool())

    # Tool discovery
    registry.register(tool_search)


__all__ = ["register_builtin_tools"]
