"""Custom message classes for TUI events."""

from textual.message import Message


class ToolStarted(Message):
    """Posted when a tool starts executing."""

    def __init__(self, tool_key: str, tool_name: str, args_str: str) -> None:
        super().__init__()
        self.tool_key = tool_key
        self.tool_name = tool_name
        self.args_str = args_str


class ToolEnded(Message):
    """Posted when a tool finishes executing."""

    def __init__(
        self, tool_key: str, tool_name: str, result: str, is_error: bool
    ) -> None:
        super().__init__()
        self.tool_key = tool_key
        self.tool_name = tool_name
        self.result = result
        self.is_error = is_error


class StreamTextDelta(Message):
    """Posted when a text chunk arrives from streaming."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class StreamReasoningDelta(Message):
    """Posted when a reasoning text chunk arrives from streaming."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class AgentBusy(Message):
    """Posted when agent starts processing."""


class AgentIdle(Message):
    """Posted when agent finishes processing."""
