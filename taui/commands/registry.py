"""Slash command registry — inspired by claw-code's command surface.

Slash commands are user-facing actions invoked by name (e.g. ``/cost``,
``/compact``, ``/help``).  Each command is a callable that receives a
``CommandContext`` and returns a ``CommandResult``.

Commands can be registered statically (built-ins) or dynamically
(plugins, skills).

Usage::

    registry = CommandRegistry()
    registry.register(CostCommand())
    result = await registry.execute("/cost", context)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CommandContext:
    """Context passed to slash command handlers."""

    raw_input: str  # full input string including /command
    args: list[str]  # parsed arguments after the command name
    session_id: str | None = None
    agent_id: str | None = None
    working_dir: str = ""
    # Extensible metadata
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CommandResult:
    """Result of executing a slash command."""

    output: str
    error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, output: str, **metadata: Any) -> "CommandResult":
        return cls(output=output, metadata=metadata)

    @classmethod
    def fail(cls, output: str, **metadata: Any) -> "CommandResult":
        return cls(output=output, error=True, metadata=metadata)


@runtime_checkable
class SlashCommand(Protocol):
    """Protocol for slash command implementations."""

    name: str
    description: str
    usage: str  # e.g. "/cost [--detailed]"

    async def execute(self, ctx: CommandContext) -> CommandResult: ...


class CommandRegistry:
    """Central registry for slash commands."""

    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}
        self._aliases: dict[str, str] = {}  # alias → canonical name

    def register(self, command: SlashCommand) -> None:
        """Register a slash command."""
        if command.name in self._commands:
            raise ValueError(f"Command '/{command.name}' is already registered")
        self._commands[command.name] = command

    def register_alias(self, alias: str, command_name: str) -> None:
        """Register an alias for an existing command."""
        if command_name not in self._commands:
            raise ValueError(f"Cannot alias unknown command '/{command_name}'")
        self._aliases[alias] = command_name

    def get(self, name: str) -> SlashCommand | None:
        """Look up a command by name or alias."""
        canonical = self._aliases.get(name, name)
        return self._commands.get(canonical)

    def list_commands(self) -> list[SlashCommand]:
        return list(self._commands.values())

    def names(self) -> list[str]:
        return sorted(self._commands.keys())

    async def execute(self, raw_input: str, context: CommandContext) -> CommandResult:
        """Parse and execute a slash command.

        ``raw_input`` should start with ``/``.  Returns a CommandResult.
        """
        if not raw_input.startswith("/"):
            return CommandResult.fail(f"Not a slash command: {raw_input}")

        parts = raw_input[1:].split(None, 1)
        if not parts:
            return CommandResult.fail("Empty command")

        name = parts[0].lower()
        context.args = parts[1].split() if len(parts) > 1 else []
        context.raw_input = raw_input

        command = self.get(name)
        if command is None:
            available = ", ".join(f"/{n}" for n in self.names())
            return CommandResult.fail(
                f"Unknown command: /{name}\nAvailable commands: {available}"
            )

        try:
            return await command.execute(context)
        except Exception as exc:
            logger.exception("Command /%s failed", name)
            return CommandResult.fail(f"Command error: {exc}")

    def help_text(self) -> str:
        """Generate help text listing all commands."""
        lines = ["Available commands:"]
        for cmd in sorted(self._commands.values(), key=lambda c: c.name):
            lines.append(f"  {cmd.usage:<30s} {cmd.description}")
        return "\n".join(lines)
