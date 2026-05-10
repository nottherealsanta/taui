"""Approval prompts and question panel flows."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rich.markup import escape
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from taui.tui.widgets.approval import ApprovalPrompt
from taui.tui.widgets.chat_input import ChatInput
from taui.tui.widgets.questions_panel import QuestionsPanel, QuestionSpec

if TYPE_CHECKING:
    from taui.tui.app import TauiApp


def _trunc(s: str, n: int = 40) -> str:
    return s[: n - 3] + "..." if len(s) > n else s


class ApprovalController:
    def __init__(self, app: TauiApp) -> None:
        self._app = app
        self._active_questions_panel: QuestionsPanel | None = None

    def has_active_panel(self) -> bool:
        return self._active_questions_panel is not None

    def cancel_active_panel(self) -> None:
        panel = self._active_questions_panel
        if panel and panel._future and not panel._future.done():
            panel._future.cancel()

    async def on_questions_batch(
        self, specs: list[tuple[str, list[str] | None]]
    ) -> list[str | None]:
        q_specs = [QuestionSpec(q, opts) for q, opts in specs]
        chat_area = self._app.query_one("#chat-area", Vertical)
        chat_input = self._app.query_one("#chat-input", ChatInput)
        chat_input.disabled = True
        panel = QuestionsPanel(q_specs)
        self._active_questions_panel = panel
        try:
            await chat_area.mount(panel, before=chat_input)
            self._app._smart_scroll()
            return await panel.wait_for_answers()
        finally:
            if panel.is_mounted:
                await panel.remove()
            if self._active_questions_panel is panel:
                self._active_questions_panel = None
            chat_input.disabled = False
            chat_input.focus()

    async def on_approval(
        self, call_id: str, name: str, arguments: dict
    ) -> bool:
        chat_log = self._app.query_one("#chat-log", VerticalScroll)
        args_short = ", ".join(
            f"{k}={_trunc(str(v))}" for k, v in arguments.items()
        )
        prompt = ApprovalPrompt(name, args_short)
        await chat_log.mount(prompt)
        self._app._smart_scroll()
        return await prompt.wait_for_response()

    async def debug_questions(self, chat_log: VerticalScroll) -> None:
        try:
            answers = await self.on_questions_batch(
                [
                    (
                        "Choose a deployment target",
                        [
                            "Local dev server (Recommended)",
                            "Staging environment",
                            "Production with dry-run",
                        ],
                    ),
                    (
                        "Pick a follow-up action",
                        [
                            "Open the diff",
                            "Run tests (Recommended)",
                            "Skip verification",
                        ],
                    ),
                ]
            )
        except asyncio.CancelledError:
            await chat_log.mount(
                Static("[dim]Debug questions cancelled.[/dim]", markup=True)
            )
            self._app._smart_scroll()
            raise
        else:
            rendered = ", ".join(answer or "<custom empty>" for answer in answers)
            await chat_log.mount(
                Static(
                    f"[dim]Debug answers: {escape(rendered)}[/dim]",
                    markup=True,
                )
            )
            self._app._smart_scroll()
