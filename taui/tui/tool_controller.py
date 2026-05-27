"""Tool call UI tracking — start/end matching and widget lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Vertical

from taui.session_replay import ReplayItem
from taui.tui.messages import ToolEnded, ToolStarted
from taui.tui.widgets.sub_agent_widget import SubAgentWidget
from taui.tui.widgets.tool_status import ToolStatusWidget

if TYPE_CHECKING:
    from taui.tui.app import TauiApp
    from taui.tui.session_state import SessionState
    from taui.tui.widgets.turn_container import TurnContainer


def _trunc(s: str, n: int = 40) -> str:
    return s[: n - 3] + "..." if len(s) > n else s


def _format_activity(tool_name: str, arguments: dict | None, is_result: bool = False) -> str:
    args = arguments or {}
    args_short = ", ".join(
        f"{k}={_trunc(str(v))}" for k, v in args.items()
    )
    prefix = "✓" if is_result else "▸"
    if args_short:
        return f"{prefix} {tool_name}  {args_short}"
    return f"{prefix} {tool_name}"


class ToolController:
    def __init__(self, app: TauiApp) -> None:
        self._app = app
        self._tool_counter = 0
        self._pending_tool_keys: dict[str, list[str]] = {}
        self._active_tool_widgets: dict[str, ToolStatusWidget] = {}
        self._current_tool_section: Vertical | None = None
        # Stack of active SubAgentWidgets. While non-empty, inner tool
        # events (those that were forwarded by SubAgentTool from the
        # child loop) are recorded on the top widget instead of being
        # mounted inline as new ToolStatusWidgets.
        self._active_sub_agents: list[SubAgentWidget] = []
        # Track which inner tool_keys are recorded against a sub-agent
        # so the matching result event also routes to it.
        self._inner_to_sub_agent: dict[str, SubAgentWidget] = {}
        self._tool_replay_turns: dict[str, TurnContainer] = {}

    def reset_section(self) -> None:
        self._current_tool_section = None

    async def cancel_active(self, reason: str = "Cancelled") -> None:
        """Mark every in-flight tool widget as cancelled.

        Stops the spinner, clears the `└ …` progress line, and shows the
        given reason. Called when the user cancels the current request
        (Escape / Ctrl+C) so sub-agents and other long-running tools
        don't keep spinning after their parent worker has been killed.
        """
        widgets = list(self._active_tool_widgets.items())
        self._active_tool_widgets.clear()
        self._pending_tool_keys.clear()
        self._active_sub_agents.clear()
        self._inner_to_sub_agent.clear()
        self._tool_replay_turns.clear()
        for _, widget in widgets:
            try:
                await widget.fail(reason)
            except Exception:
                pass

    def reset(self) -> None:
        """Drop all in-flight tool state. Used when a session is reset and
        the widgets pointed at by `_active_tool_widgets` are about to be
        unmounted by a chat-log clear."""
        self._tool_counter = 0
        self._pending_tool_keys.clear()
        self._active_tool_widgets.clear()
        self._current_tool_section = None
        self._active_sub_agents.clear()
        self._inner_to_sub_agent.clear()
        self._tool_replay_turns.clear()

    def _owning_state(self) -> SessionState | None:
        sessions = getattr(self._app, "_sessions", None)
        if sessions:
            for st in sessions.all_states.values():
                if st.tool_ctrl is self:
                    return st
        return None

    async def on_tool_call(
        self, call_id: str, name: str, arguments: dict
    ) -> None:
        self._tool_counter += 1
        tool_key = f"{name}_{self._tool_counter}"
        self._pending_tool_keys.setdefault(name, []).append(tool_key)
        args_short = ", ".join(
            f"{k}={_trunc(str(v))}" for k, v in arguments.items()
        )
        # Determine session_id for routing
        sid = ""
        sessions = getattr(self._app, "_sessions", None)
        if sessions:
            for s_id, st in sessions.all_states.items():
                if st.tool_ctrl is self:
                    sid = s_id
                    break
        self._app.post_message(
            ToolStarted(
                tool_key, name, args_short, session_id=sid, arguments=arguments,
            )
        )

        record_edit = getattr(self._app, "_record_edit", None)
        if record_edit is not None:
            try:
                record_edit(name, arguments)
            except Exception:
                pass

        session = self._app._session
        if session:
            await session.hooks.run("on_tool_call", name, arguments, session)

    async def on_tool_result(
        self, call_id: str, name: str, content: str, is_error: bool
    ) -> None:
        keys = self._pending_tool_keys.get(name, [])
        if keys:
            tool_key = keys.pop(0)
        else:
            tool_key = next(
                (k for k in self._active_tool_widgets if k.startswith(name)),
                f"{name}_unknown",
            )
        self._app.post_message(
            ToolEnded(tool_key, name, content, is_error)
        )

        session = self._app._session
        if session:
            await session.hooks.run(
                "on_tool_result", name, content, is_error, session
            )

    async def handle_tool_started(self, event: ToolStarted) -> None:
        # Find the session state this tool belongs to
        st: SessionState | None = None
        if hasattr(event, "session_id") and event.session_id:
            sessions = getattr(self._app, "_sessions", None)
            if sessions:
                st = sessions.get(event.session_id)
        if st is None:
            st = self._owning_state()
        if st is None:
            sessions = getattr(self._app, "_sessions", None)
            if sessions is not None:
                st = sessions.active

        arguments = getattr(event, "arguments", None) or None

        # When a sub-agent is running, route inner tool events into its
        # widget rather than mounting a new ToolStatusWidget inline.
        if self._active_sub_agents and event.tool_name != "sub_agent":
            sub = self._active_sub_agents[-1]
            sub.record_activity(_format_activity(event.tool_name, arguments))
            self._inner_to_sub_agent[event.tool_key] = sub
            return

        await self._app._finalize_response(st)

        if self._current_tool_section is None:
            self._current_tool_section = Vertical(classes="tool-section")
            await self._app._mount_in_reply(self._current_tool_section, state=st)

        if event.tool_name == "sub_agent":
            widget = SubAgentWidget(
                event.tool_name,
                event.args_str,
                arguments=arguments,
            )
            self._active_sub_agents.append(widget)
        else:
            widget = ToolStatusWidget(
                event.tool_name,
                event.args_str,
                arguments=arguments,
            )
        await self._current_tool_section.mount(widget)
        self._active_tool_widgets[event.tool_key] = widget
        if st is not None and st.current_turn is not None:
            agent_id = str(getattr(st.session._loop, "agent_id", "") or "")
            model = getattr(st.session, "model_name", "") or getattr(
                st.session._loop, "_model", ""
            )
            st.current_turn.append_replay_item(
                ReplayItem(
                    kind="tool_call",
                    name=event.tool_name,
                    call_id=event.tool_key,
                    arguments=arguments,
                    agent_id=agent_id,
                    model=model,
                )
            )
            self._tool_replay_turns[event.tool_key] = st.current_turn

    async def handle_tool_ended(self, event: ToolEnded) -> None:
        # Inner tool results from a sub-agent are recorded on the sub-agent
        # widget rather than completing a top-level ToolStatusWidget.
        sub = self._inner_to_sub_agent.pop(event.tool_key, None)
        if sub is not None:
            preview = (event.result or "").strip().splitlines()
            first = preview[0] if preview else ""
            sub.record_activity(
                _format_activity(event.tool_name, None, is_result=True)
                + (f"  {first}" if first else "")
            )
            return

        widget = self._active_tool_widgets.pop(event.tool_key, None)
        turn = self._tool_replay_turns.pop(event.tool_key, None)
        if turn is not None:
            turn.append_replay_item(
                ReplayItem(
                    kind="tool_result",
                    name=event.tool_name,
                    call_id=event.tool_key,
                    text=event.result,
                    is_error=event.is_error,
                )
            )
        if widget:
            if isinstance(widget, SubAgentWidget) and widget in self._active_sub_agents:
                self._active_sub_agents.remove(widget)
            if event.is_error:
                await widget.fail(event.result)
            else:
                await widget.complete(event.result)
