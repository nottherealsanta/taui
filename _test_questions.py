"""Standalone test app for QuestionsPanel — no LLM needed.

Launch: uv run python _test_questions.py
Serves a self-contained TUI that shows the QuestionsPanel
above the chat input, exactly like the real app.
"""

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static, TextArea

from taui.tui.widgets.questions_panel import QuestionSpec, QuestionsPanel

SCREENSHOT_PATH = Path(__file__).parent / "_screenshot.svg"

SPECS = [
    QuestionSpec(
        "What would be most helpful to focus on right now?",
        [
            "Debug and fix issues",
            "Help implement new features",
            "Review and prepare for commit",
        ],
    ),
    QuestionSpec("What is the project name?"),
]


class QuestionsTestApp(App):
    CSS = """
    #chat-area {
        width: 1fr;
        height: 1fr;
    }
    #chat-log {
        height: 1fr;
    }
    #chat-input {
        height: 3;
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="chat-area"):
            with VerticalScroll(id="chat-log"):
                yield Static("[dim]Chat log area[/dim]", markup=True)
                yield Static("[dim]Some previous messages...[/dim]", markup=True)
            yield TextArea(id="chat-input")

    async def on_mount(self) -> None:
        # Start the question flow as a background task
        # (simulates how the real app triggers from agent loop callback)
        asyncio.create_task(self._show_questions())

    async def _show_questions(self) -> None:
        chat_area = self.query_one("#chat-area", Vertical)
        chat_input = self.query_one("#chat-input", TextArea)
        chat_input.disabled = True

        panel = QuestionsPanel(SPECS)
        await chat_area.mount(panel, before=chat_input)

        answers = await panel.wait_for_answers()
        await panel.remove()
        chat_input.disabled = False

        log = self.query_one("#chat-log", VerticalScroll)
        await log.mount(
            Static(
                f"[green bold]Answers: {answers}[/green bold]",
                markup=True,
            )
        )


if __name__ == "__main__":
    QuestionsTestApp().run()
