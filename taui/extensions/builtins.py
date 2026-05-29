"""Built-in extension lifecycle.

These capabilities ship with Taui, but treating them as extensions keeps
Session wiring small and makes optional systems visible in one catalog.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from taui.hooks import HookRegistry
from taui.tools.builtins.mcp import McpTool
from taui.tools.builtins.skills import SkillsTool
from taui.tools.builtins.sub_agent import SubAgentTool

if TYPE_CHECKING:
    from taui.session import Session
    from taui.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


BUILTIN_EXTENSION_NAMES = (
    "hooks",
    "skills",
    "mcp",
    "lsp",
    "symbols",
    "sub_agents",
)


@dataclass(frozen=True, slots=True)
class BuiltinExtensionSpec:
    """Metadata for a Taui capability that is loaded as a built-in extension."""

    name: str
    description: str


BUILTIN_EXTENSIONS: tuple[BuiltinExtensionSpec, ...] = (
    BuiltinExtensionSpec("hooks", "Hook registry for UI, pipeline, and observer hooks."),
    BuiltinExtensionSpec("skills", "Skill discovery and loading tool."),
    BuiltinExtensionSpec("mcp", "MCP server manager and invocation tool."),
    BuiltinExtensionSpec("lsp", "Language Server Protocol manager."),
    BuiltinExtensionSpec("symbols", "Workspace symbol indexer."),
    BuiltinExtensionSpec("sub_agents", "Scoped child-agent delegation tool."),
)


def ensure_builtin_extension_tools(registry: ToolRegistry) -> None:
    """Ensure tool-backed built-in extensions are present in the registry."""
    for tool_cls in (McpTool, SkillsTool, SubAgentTool):
        tool = tool_cls()
        if tool.name not in registry:
            registry.register(tool)


def configure_builtin_extensions(session: Session) -> None:
    """Wire built-in extension dependencies onto an assembled session."""
    _configure_skills(session)
    _configure_mcp(session)
    _configure_lsp(session)
    _configure_symbols(session)
    _configure_sub_agents(session)
    session._refresh_loop_integrations()


async def close_builtin_extensions(session: Session) -> None:
    """Stop long-lived resources owned by built-in extensions."""
    mcp_manager = getattr(session, "_mcp_manager", None)
    if mcp_manager is not None:
        try:
            await mcp_manager.disconnect_all()
        except Exception:
            logger.debug("Error disconnecting MCP servers", exc_info=True)

    lsp_manager = getattr(session, "_lsp_manager", None)
    if lsp_manager is not None:
        try:
            await lsp_manager.stop_all()
        except Exception:
            logger.debug("Error stopping LSP servers", exc_info=True)


def _configure_skills(session: Session) -> None:
    from taui.skills import SkillRegistry

    skill_registry = SkillRegistry(session.config.working_dir)
    skill_registry.discover()
    session._skill_registry = skill_registry

    try:
        skills_tool = session._registry.get("skills")
    except ValueError:
        return
    if isinstance(skills_tool, SkillsTool):
        skills_tool._skill_registry = skill_registry


def _configure_mcp(session: Session) -> None:
    from taui.mcp import McpManager

    mcp_manager = McpManager(session.config.working_dir)
    mcp_manager.load_configs()
    session._mcp_manager = mcp_manager

    try:
        mcp_tool = session._registry.get("mcp")
    except ValueError:
        return
    if isinstance(mcp_tool, McpTool):
        mcp_tool._manager = mcp_manager


def _configure_lsp(session: Session) -> None:
    from taui.lsp import LspManager

    session._lsp_manager = LspManager(session.config.working_dir)


def _configure_symbols(session: Session) -> None:
    from taui.symbols import SymbolIndexer

    session._symbol_indexer = SymbolIndexer(session.config.working_dir)


def _configure_sub_agents(session: Session) -> None:
    try:
        sub_agent = session._registry.get("sub_agent")
    except ValueError:
        return
    if not isinstance(sub_agent, SubAgentTool):
        return

    # Preferred path: hand the tool the live session so execute() spawns a
    # real sub-session via create_sub_session(). Without this, execute() falls
    # back to the legacy direct-loop path, which can't forward the child's tool
    # events to the TUI — the sub-agent widget would sit at "starting…" with an
    # empty activity log until the result lands. The legacy fields below remain
    # as a fallback for contexts where no session is available (e.g. tests).
    sub_agent._session = session
    sub_agent._llm = session._provider
    sub_agent._stream = session._stream
    sub_agent._parent_executor = session._executor
    sub_agent._model = session.config.model
    sub_agent._system_prompt = ""
    # Advertise the spawnable agent profiles (EXP, …) in the tool schema so the
    # main agent can actually discover and use them.
    sub_agent.refresh_agent_catalog()


def new_hook_registry() -> HookRegistry:
    """Create the hooks capability without leaking its implementation to Session."""
    return HookRegistry()
