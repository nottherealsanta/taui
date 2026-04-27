"""
taui.commands — slash command system.

Provides a registry of user-facing commands (``/help``, ``/cost``, etc.)
and built-in implementations.
"""

from taui.commands.registry import CommandContext, CommandRegistry, CommandResult

__all__ = ["CommandContext", "CommandRegistry", "CommandResult"]
