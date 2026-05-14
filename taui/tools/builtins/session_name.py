"""Session name tool — let the agent assign a short label to the current session.

Called by the agent after the first user message, the tool stores a short
human-readable name as the session's description, so the /sessions picker can
distinguish past sessions at a glance. If never called, the picker falls back
to the session's created time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from taui.tools.base import ToolCategory, ToolResult


@dataclass
class SessionNameTool:
    """Assign a short, descriptive name to the current session."""

    name: str = "session_name"
    description: str = (
        "Set a short (2-6 word) descriptive name for the current session. "
        "Call this exactly once, right after the user's first message, to "
        "summarize what the session is about. If you don't call it the "
        "session will be labeled by its created time."
    )
    category: ToolCategory = ToolCategory.AGENT
    guidelines: str = (
        "Call `session_name` once after the user's first message with a "
        "short (2-6 word) label that captures the task. Examples: "
        "'fix /sessions crash', 'add session_name tool', "
        "'investigate flaky test'. Do not call it again later."
    )
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    # Injected by Session.create()
    _set_name: Any = None  # async (name: str) -> None

    def __post_init__(self):
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "Short descriptive name for this session "
                            "(2-6 words, max 80 chars)."
                        ),
                    },
                },
                "required": ["name"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        raw = arguments.get("name")
        if not isinstance(raw, str):
            return ToolResult.fail("'name' must be a string.")
        name = raw.strip().splitlines()[0].strip() if raw.strip() else ""
        if not name:
            return ToolResult.fail("'name' cannot be empty.")
        if len(name) > 80:
            name = name[:80].rstrip()

        if self._set_name is None:
            return ToolResult.fail("Session naming is not wired up.")

        await self._set_name(name)
        return ToolResult.ok(f"Session named: {name}", name=name)
