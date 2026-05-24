"""Embedded MCP debug server for taui.

Run ``taui --debug`` to launch the TUI with an embedded JSON-RPC server
listening on a Unix socket at ``/tmp/taui-debug-{pid}.sock``. External
clients can drive the running TUI — send messages, take screenshots,
inspect state, press keys, run slash commands.
"""

from taui.debug.server import DebugServer

__all__ = ["DebugServer"]
