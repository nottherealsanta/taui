"""Approval prompts and question panel flows."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from rich.markup import escape
from textual.containers import VerticalScroll
from textual.widgets import Static

from taui.tui.widgets.chat_input import ChatInput
from taui.tui.widgets.info2 import Info2
from taui.tui.widgets.questions_panel import QuestionsPanel, QuestionSpec

if TYPE_CHECKING:
    from taui.tui.app import TauiApp

logger = logging.getLogger(__name__)


def _trunc(s: str, n: int = 40) -> str:
    return s[: n - 3] + "..." if len(s) > n else s


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
        self,
        specs: list[
            tuple[str, list[str] | list[dict] | None]
            | tuple[str, list[str] | list[dict] | None, int | None]
        ],
    ) -> list[str | None]:
        q_specs: list[QuestionSpec] = []
        for spec in specs:
            if len(spec) == 3:
                q, opts, recommended = spec  # type: ignore[misc]
            else:
                q, opts = spec  # type: ignore[misc]
                recommended = None
            q_specs.append(QuestionSpec(q, opts, recommended))
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
        info2 = self._app.query_one("#info2", Info2)
        chat_input = self._app.query_one("#chat-input", ChatInput)
        info2.show_approval(name, args_short)
        try:
            result = await info2.wait_for_approval()
        finally:
            if not chat_input.disabled:
                chat_input.focus()
        if result.allow_session:
            self._allow_tool_for_session(name)
        return result.approved

    def _allow_tool_for_session(self, tool_name: str) -> None:
        """Auto-approve all future calls to this tool for the rest of the session.

        Adds an agent-layer "allow" rule to the live permission ruleset. The
        ruleset is consulted before a tool's ``requires_approval``, so this is
        what actually suppresses the prompt (a per-tool AUTO *override* does
        not beat ``requires_approval``). The active loop's executor shares this
        policy object, so the change takes effect on the next call without a
        restart. ``add_rules(layer="agent")`` replaces the agent layer, so we
        accumulate the allowed tools and rebuild the whole layer each time.
        Switching agent profiles re-applies the profile and clears these.
        """
        from taui.permissions import PermissionRuleset

        session = getattr(self._app, "_session", None)
        if session is None:
            return
        allowed = getattr(self, "_session_allowed_tools", None)
        if allowed is None:
            allowed = set()
            self._session_allowed_tools = allowed
        allowed.add(tool_name)
        try:
            policy = session._executor.policy
            ruleset = policy._ruleset or PermissionRuleset()
            ruleset.add_rules(
                {tool: {"*": "allow"} for tool in allowed}, layer="agent"
            )
            policy.set_ruleset(ruleset)
        except Exception:
            logger.exception(
                "Failed to allowlist tool for session: %s", tool_name
            )

    async def debug_questions(self, chat_log: VerticalScroll) -> None:
        try:
            answers = await self.on_questions_batch(
                [
                    (
                        "Choose a deployment target",
                        [
                            {
                                "label": "Local dev server",
                                "description": "fastest, no remote impact",
                            },
                            {
                                "label": "Staging environment",
                                "description": "mirrors prod, safe",
                            },
                            {
                                "label": "Production with dry-run",
                                "description": "no writes, just plan",
                            },
                        ],
                        1,
                    ),
                    (
                        "Pick a follow-up action",
                        [
                            {"label": "Open the diff"},
                            {
                                "label": "Run tests",
                                "description": "verifies the change before merge",
                            },
                            {
                                "label": "Skip verification",
                                "description": "risky — only for trivial edits",
                            },
                        ],
                        2,
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
