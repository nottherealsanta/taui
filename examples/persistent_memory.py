"""Example: cross-session memory using the memory tool.

The built-in memory tool stores key-value pairs in
.taui/memory.json. This example shows how to use it
from an extension to persist data across sessions.
"""

from __future__ import annotations


def register(ctx):
    """Register hooks that save/restore session context."""

    def on_session_start(session):
        """Load previous session summary on start."""
        memory_path = session.working_dir / ".taui" / "memory.json"
        if memory_path.exists():
            import json
            data = json.loads(memory_path.read_text())
            summary = data.get("last_session_summary", "")
            if summary:
                return  # Memory tool handles injection

    ctx.hooks.add("on_session_start", on_session_start)
