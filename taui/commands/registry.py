"""Slash command registry.

Commands are user-facing actions invoked by ``/name`` at the prompt.
Each command is a callable that receives a ``CommandContext`` and returns
a ``CommandResult``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CommandContext:
    """Context passed to slash command handlers."""

    raw_input: str
    args: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CommandResult:
    """Result of executing a slash command."""

    output: str
    error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, output: str, **metadata: Any) -> CommandResult:
        return cls(output=output, metadata=metadata)

    @classmethod
    def fail(cls, output: str, **metadata: Any) -> CommandResult:
        return cls(output=output, error=True, metadata=metadata)


@runtime_checkable
class SlashCommand(Protocol):
    """Protocol for slash command implementations."""

    name: str
    description: str

    async def execute(self, ctx: CommandContext) -> CommandResult: ...


class CommandRegistry:
    """Central registry for slash commands with alias support."""

    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}
        self._aliases: dict[str, str] = {}

    def register(self, command: SlashCommand) -> None:
        if command.name in self._commands:
            raise ValueError(f"Command '/{command.name}' already registered")
        self._commands[command.name] = command

    def alias(self, alias: str, command_name: str) -> None:
        if command_name not in self._commands:
            raise ValueError(f"Cannot alias unknown command '/{command_name}'")
        self._aliases[alias] = command_name

    def get(self, name: str) -> SlashCommand | None:
        canonical = self._aliases.get(name, name)
        return self._commands.get(canonical)

    @property
    def names(self) -> list[str]:
        return sorted(self._commands.keys())

    def help_text(self) -> str:
        """Format all commands into a help string."""
        lines: list[str] = []
        for name in self.names:
            cmd = self._commands[name]
            lines.append(f"  /{name:<14s} {cmd.description}")
        aliases_by_target: dict[str, list[str]] = {}
        for a, target in sorted(self._aliases.items()):
            aliases_by_target.setdefault(target, []).append(a)
        for target, als in aliases_by_target.items():
            lines.append(f"  {'':14s}   aliases: {', '.join('/' + a for a in als)}")
        return "\n".join(lines)

    async def execute(self, raw_input: str) -> CommandResult:
        """Parse and execute a slash command."""
        if not raw_input.startswith("/"):
            return CommandResult.fail(f"Not a slash command: {raw_input}")

        parts = raw_input[1:].split(None, 1)
        if not parts:
            return CommandResult.fail("Empty command")

        name = parts[0].lower()
        args = parts[1].split() if len(parts) > 1 else []
        ctx = CommandContext(raw_input=raw_input, args=args)

        command = self.get(name)
        if command is None:
            available = ", ".join(f"/{n}" for n in self.names)
            return CommandResult.fail(
                f"Unknown command: /{name}\nAvailable: {available}"
            )

        try:
            return await command.execute(ctx)
        except Exception as exc:
            logger.exception("Command /%s failed", name)
            return CommandResult.fail(f"Command error: {exc}")
