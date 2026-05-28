"""Custom message classes for TUI events."""

from textual.message import Message


class ToolStarted(Message):
    """Posted when a tool starts executing."""

    def __init__(
        self, tool_key: str, tool_name: str, args_str: str,
        *, session_id: str = "", arguments: dict | None = None,
    ) -> None:
        super().__init__()
        self.tool_key = tool_key
        self.tool_name = tool_name
        self.args_str = args_str
        self.session_id = session_id
        self.arguments = arguments or {}


class ToolEnded(Message):
    """Posted when a tool finishes executing."""

    def __init__(
        self, tool_key: str, tool_name: str, result: str, is_error: bool,
        *, session_id: str = "",
    ) -> None:
        super().__init__()
        self.tool_key = tool_key
        self.tool_name = tool_name
        self.result = result
        self.is_error = is_error
        self.session_id = session_id


class ToolOutputDelta(Message):
    """Posted when a running tool emits stdout/stderr output."""

    def __init__(
        self, tool_key: str, tool_name: str, chunk: str, *, session_id: str = "",
    ) -> None:
        super().__init__()
        self.tool_key = tool_key
        self.tool_name = tool_name
        self.chunk = chunk
        self.session_id = session_id


class StreamTextDelta(Message):
    """Posted when a text chunk arrives from streaming."""

    def __init__(self, text: str, *, session_id: str = "") -> None:
        super().__init__()
        self.text = text
        self.session_id = session_id


class StreamReasoningDelta(Message):
    """Posted when a reasoning text chunk arrives from streaming."""

    def __init__(self, text: str, *, session_id: str = "") -> None:
        super().__init__()
        self.text = text
        self.session_id = session_id


class AgentBusy(Message):
    """Posted when agent starts processing."""


class AgentIdle(Message):
    """Posted when agent finishes processing."""


class CompactionOccurred(Message):
    """Posted when auto-compaction runs during agent loop."""

    def __init__(
        self, removed: int, before_tokens: int, after_tokens: int,
        *, session_id: str = "", summary_text: str = "", kind: str = "auto",
    ) -> None:
        super().__init__()
        self.removed = removed
        self.before_tokens = before_tokens
        self.after_tokens = after_tokens
        self.session_id = session_id
        self.summary_text = summary_text
        self.kind = kind


class AgentConfigChanged(Message):
    """Posted when the session's system prompt, tools, or policy change.

    Triggers a refresh of the in-chat context banner so the rendered system
    prompt and tool list stay in sync with hot-reloaded extensions, variant
    switches, and self-edit toggles.
    """

    def __init__(self, *, session_id: str = "") -> None:
        super().__init__()
        self.session_id = session_id
