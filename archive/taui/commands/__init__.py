"""Slash command system — extensible command surface.

Provides a registry for slash commands (``/compact``, ``/cost``, ``/help``,
etc.) that can be invoked from the user interface or injected into the
agent's input stream.
"""

from taui.commands.registry import CommandRegistry, SlashCommand

__all__ = ["CommandRegistry", "SlashCommand"]
