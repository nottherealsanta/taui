"""Approval inline widget."""

from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Label


class ApprovalPrompt(Widget):
    """Inline approval prompt for tool execution confirmation."""

    DEFAULT_CSS = """
    ApprovalPrompt {
        height: auto;
        padding: 0 0 0 1;
        margin: 0 0 1 0;
        border-left: tall #f2cc60;
    }
    ApprovalPrompt.approval-resolved-ok {
        border-left: tall #3fb950;
    }
    ApprovalPrompt.approval-resolved-deny {
        border-left: tall #ff7b72;
    }
    ApprovalPrompt .approval-question {
        color: $foreground;
        padding: 0 0 0 0;
    }
    ApprovalPrompt .approval-buttons {
        height: auto;
        padding: 0 0 0 3;
    }
    ApprovalPrompt Button {
        margin: 0 1 0 0;
        min-width: 8;
    }
    """

    class Responded(Message):
        """Posted when user responds to the approval prompt."""

        def __init__(self, approved: bool) -> None:
            super().__init__()
            self.approved = approved

    def __init__(self, tool_name: str, args_summary: str) -> None:
        super().__init__()
        self.tool_name = tool_name
        self.args_summary = args_summary
        self._future: asyncio.Future[bool] | None = None

    def compose(self) -> ComposeResult:
        yield Label(
            f"Allow [bold]{self.tool_name}[/bold]({self.args_summary})?",
            classes="approval-question",
            markup=True,
        )
        with Horizontal(classes="approval-buttons"):
            yield Button("Allow", variant="success", id="approve-btn")
            yield Button("Deny", variant="error", id="deny-btn")

    def on_mount(self) -> None:
        self.query_one("#approve-btn", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        approved = event.button.id == "approve-btn"
        self.add_class(
            "approval-resolved-ok" if approved else "approval-resolved-deny"
        )
        self.post_message(self.Responded(approved))
        if self._future and not self._future.done():
            self._future.set_result(approved)

    async def wait_for_response(self) -> bool:
        """Wait for user to respond. Returns True if approved."""
        loop = asyncio.get_running_loop()
        self._future = loop.create_future()
        return await self._future
