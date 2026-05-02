"""Approval and question inline widgets."""

from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Label, OptionList, Static
from textual.widgets.option_list import Option


class ApprovalPrompt(Widget):
    """Inline approval prompt for tool execution confirmation."""

    DEFAULT_CSS = """
    ApprovalPrompt {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    ApprovalPrompt .approval-question {
        color: yellow;
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
        self.post_message(self.Responded(approved))
        if self._future and not self._future.done():
            self._future.set_result(approved)

    async def wait_for_response(self) -> bool:
        """Wait for user to respond. Returns True if approved."""
        loop = asyncio.get_event_loop()
        self._future = loop.create_future()
        return await self._future


class QuestionPrompt(Widget):
    """Inline question prompt with selectable options."""

    DEFAULT_CSS = """
    QuestionPrompt {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    QuestionPrompt .question-text {
        color: yellow;
        padding: 0 0 0 0;
    }
    QuestionPrompt OptionList {
        height: auto;
        max-height: 10;
        margin: 0 0 0 3;
        background: $surface;
        border: solid $accent;
    }
    """

    class Answered(Message):
        """Posted when user selects an answer."""

        def __init__(self, answer: str | None) -> None:
            super().__init__()
            self.answer = answer

    def __init__(self, question: str, options: list[str] | None = None) -> None:
        super().__init__()
        self._question = question
        self._options = options or []
        self._future: asyncio.Future[str | None] | None = None

    def compose(self) -> ComposeResult:
        yield Label(
            f"[yellow]? {self._question}[/yellow]",
            classes="question-text",
            markup=True,
        )
        if self._options:
            opts = [Option(f"{i}. {opt}") for i, opt in enumerate(self._options, 1)]
            yield OptionList(*opts, id="question-options")

    def on_mount(self) -> None:
        if self._options:
            self.query_one("#question-options", OptionList).focus()

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        idx = event.option_index
        answer = self._options[idx] if idx < len(self._options) else None
        self.post_message(self.Answered(answer))
        if self._future and not self._future.done():
            self._future.set_result(answer)

    async def wait_for_answer(self) -> str | None:
        """Wait for user to answer. Returns selected option text or None."""
        if not self._options:
            return None
        loop = asyncio.get_event_loop()
        self._future = loop.create_future()
        return await self._future
