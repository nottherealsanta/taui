"""Built-in slash commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from taui.commands.registry import CommandContext, CommandResult


@dataclass(slots=True)
class HelpCommand:
    """Display available commands."""

    name: str = "help"
    description: str = "Show available slash commands"
    usage: str = "/help"
    _registry: Any = None  # CommandRegistry — set after creation

    def set_registry(self, registry: Any) -> None:
        self._registry = registry

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if self._registry is None:
            return CommandResult.ok("No command registry available.")
        return CommandResult.ok(self._registry.help_text())


@dataclass(slots=True)
class CostCommand:
    """Display cost and token usage for the current session."""

    name: str = "cost"
    description: str = "Show token usage and cost for the current session"
    usage: str = "/cost"
    _get_tracker: Any = None  # Callable → CostTracker

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if self._get_tracker is None:
            return CommandResult.fail("Cost tracking not available.")
        try:
            tracker = self._get_tracker()
            return CommandResult.ok(tracker.summary(), **tracker.to_dict())
        except Exception as exc:
            return CommandResult.fail(f"Error retrieving cost: {exc}")


@dataclass(slots=True)
class CompactCommand:
    """Trigger conversation compaction."""

    name: str = "compact"
    description: str = "Compact conversation history to reduce token usage"
    usage: str = "/compact"

    async def execute(self, ctx: CommandContext) -> CommandResult:
        # This command signals the agent runner to compact
        return CommandResult.ok(
            "Compaction requested. The conversation will be compacted before the next turn.",
            action="compact_requested",
        )


@dataclass(slots=True)
class StatusCommand:
    """Show agent status."""

    name: str = "status"
    description: str = "Show current agent status and task progress"
    usage: str = "/status"

    async def execute(self, ctx: CommandContext) -> CommandResult:
        info: list[str] = []
        if ctx.agent_id:
            info.append(f"Agent: {ctx.agent_id}")
        if ctx.session_id:
            info.append(f"Session: {ctx.session_id}")
        info.append(f"Working directory: {ctx.working_dir}")
        return CommandResult.ok("\n".join(info) if info else "No active agent.")


def register_builtins(registry: Any) -> None:
    """Register all built-in commands with a CommandRegistry."""
    help_cmd = HelpCommand()
    help_cmd.set_registry(registry)

    registry.register(help_cmd)
    registry.register(CostCommand())
    registry.register(CompactCommand())
    registry.register(StatusCommand())

    # Aliases
    registry.register_alias("h", "help")
    registry.register_alias("?", "help")
