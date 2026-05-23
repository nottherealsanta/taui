"""
taui.tools.builtins — built-in tool implementations.

These are the core tools that ship with Taui. Each tool is a dataclass
implementing the Tool protocol from taui.tools.base.
"""

from taui.tools.builtins.apply_patch import ApplyPatchTool
from taui.tools.builtins.bash import BashKillTool, BashStatusTool, BashTool
from taui.tools.builtins.edit import EditTool
from taui.tools.builtins.files import GlobTool, GrepTool, ReadTool, WriteTool
from taui.tools.builtins.git import GitTool
from taui.tools.builtins.lsp import LspTool
from taui.tools.builtins.mcp import McpTool
from taui.tools.builtins.memory import MemoryTool
from taui.tools.builtins.peek import PeekTool
from taui.tools.builtins.question import QuestionTool
from taui.tools.builtins.repo_overview import RepoOverviewTool
from taui.tools.builtins.session_name import SessionNameTool
from taui.tools.builtins.skills import SkillsTool
from taui.tools.builtins.sub_agent import SubAgentTool
from taui.tools.builtins.task import TaskTool
from taui.tools.builtins.webfetch import WebfetchTool
from taui.tools.builtins.worktree import WorktreeTool
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
        BashStatusTool(),
        BashKillTool(),
        GitTool(),
        McpTool(),
        MemoryTool(),
        PeekTool(),
        QuestionTool(),
        SessionNameTool(),
        SkillsTool(),
        SubAgentTool(),
        TaskTool(),
        WebfetchTool(),
        ApplyPatchTool(),
        LspTool(),
        RepoOverviewTool(),
        WorktreeTool(),
    ]:
        registry.register(tool)


__all__ = [
    "ApplyPatchTool",
    "LspTool",
    "BashKillTool",
    "BashStatusTool",
    "BashTool",
    "EditTool",
    "GitTool",
    "GlobTool",
    "GrepTool",
    "McpTool",
    "MemoryTool",
    "PeekTool",
    "QuestionTool",
    "ReadTool",
    "RepoOverviewTool",
    "SessionNameTool",
    "SkillsTool",
    "SubAgentTool",
    "TaskTool",
    "WebfetchTool",
    "WorktreeTool",
    "WriteTool",
    "register_builtins",
]
