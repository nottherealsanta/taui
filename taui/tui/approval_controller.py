"""Approval prompts and question panel flows."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

from rich.markup import escape
from textual.containers import VerticalScroll
from textual.widgets import Static

from taui.extensions.auto_approve import write_auto_approve_extension
from taui.tui.widgets.chat_input import ChatInput
from taui.tui.widgets.info2 import Info2
from taui.tui.widgets.questions_panel import QuestionsPanel, QuestionSpec

if TYPE_CHECKING:
    from taui.tui.app import TauiApp

logger = logging.getLogger(__name__)


def _trunc(s: str, n: int = 40) -> str:
    return s[: n - 3] + "..." if len(s) > n else s


def _make_pattern(tool_name: str, arguments: dict) -> str:
    if tool_name == "bash":
        cmd = arguments.get("command", "")
        parts = cmd.split()
        if len(parts) >= 2:
            return " ".join(parts[:2]) + " *"
        return cmd + " *" if cmd else "*"
    if tool_name in ("write", "edit"):
        path = arguments.get("file_path", "") or arguments.get("filePath", "")
        if path:
            parent = os.path.dirname(path)
            return os.path.join(parent, "*") if parent else "*"
        return "*"
    if tool_name == "git":
        operation = arguments.get("operation", "")
        if isinstance(operation, str) and operation:
            return operation + " *"
        return "*"
    return "*"


class ApprovalController:
    def __init__(self, app: TauiApp) -> None:
        self._app = app
        self._active_questions_panel: QuestionsPanel | None = None

    def _from_active_session(self) -> bool:
        """Return whether this per-session controller belongs to the visible session."""
        sessions = getattr(self._app, "_sessions", None)
        if sessions is None:
            return True
        active = getattr(sessions, "active", None)
        if active is None:
            return True
        return getattr(active, "approval_ctrl", None) is self

    def has_active_panel(self) -> bool:
        return self._active_questions_panel is not None

    def cancel_active_panel(self) -> None:
        panel = self._active_questions_panel
        if panel and panel._future and not panel._future.done():
            panel._future.cancel()

    def cancel_active_approval(self) -> None:
        """Cancel any pending info2 approval."""
        try:
            info2 = self._app.query_one("#info2", Info2)
            from taui.tui.widgets.info2 import Info2Mode
            if info2.mode == Info2Mode.APPROVAL:
                info2.dismiss()
        except Exception:
            pass

    async def on_questions_batch(
        self, specs: list[tuple[str, list[str] | None]]
    ) -> list[str | None]:
        q_specs = [QuestionSpec(q, opts) for q, opts in specs]
        chat_input = self._app.query_one("#chat-input", ChatInput)
        info2 = self._app.query_one("#info2", Info2)
        chat_input.disabled = True
        panel = info2.show_questions(q_specs)
        self._active_questions_panel = panel
        try:
            self._app._smart_scroll()
            # Notify the user — they need to answer before the agent can
            # continue, so this is a "please look at me" moment.
            try:
                first = specs[0][0] if specs else "Question"
                self._app._notify_user(
                    "Question",
                    first,
                    kind="question",
                    from_active_session=self._from_active_session(),
                )
            except Exception:
                pass
            return await panel.wait_for_answers()
        finally:
            if self._active_questions_panel is panel:
                self._active_questions_panel = None
            info2.hide()
            chat_input.disabled = False
            chat_input.focus()

    async def on_approval(
        self, call_id: str, name: str, arguments: dict
    ) -> bool:
        args_short = ", ".join(
            f"{k}={_trunc(str(v))}" for k, v in arguments.items()
        )
        pattern = _make_pattern(name, arguments)
        info2 = self._app.query_one("#info2", Info2)
        chat_input = self._app.query_one("#chat-input", ChatInput)
        info2.show_approval(name, args_short, pattern)
        try:
            result = await info2.wait_for_approval()
        finally:
            if not chat_input.disabled:
                chat_input.focus()
        if result.pattern is not None and self._app._session:
            try:
                self._app._session._executor._policy.add_pattern(name, result.pattern)
            except Exception:
                pass
        if result.tool_scope is not None and self._app._session:
            try:
                path = write_auto_approve_extension(
                    name,
                    self._app._session.config.working_dir,
                    result.tool_scope,
                )
                self._app._session.reload_extensions()
                logger.info(
                    "Created auto-approve extension for %s at %s",
                    name,
                    path,
                )
            except Exception:
                logger.exception("Failed to create auto-approve extension for %s", name)
        return result.approved

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
