"""Tool call UI tracking — start/end matching and widget lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Vertical

from taui.tui.messages import ToolEnded, ToolProgress, ToolStarted
from taui.tui.widgets.tool_status import ToolStatusWidget

if TYPE_CHECKING:
    from taui.tui.app import TauiApp


def _trunc(s: str, n: int = 40) -> str:
    return s[: n - 3] + "..." if len(s) > n else s


class ToolController:
    def __init__(self, app: TauiApp) -> None:
        self._app = app
        self._tool_counter = 0
        self._pending_tool_keys: dict[str, list[str]] = {}
        self._active_tool_widgets: dict[str, ToolStatusWidget] = {}
        self._current_tool_section: Vertical | None = None

    def reset_section(self) -> None:
        self._current_tool_section = None

    def reset(self) -> None:
        """Drop all in-flight tool state. Used when a session is reset and
        the widgets pointed at by `_active_tool_widgets` are about to be
        unmounted by a chat-log clear."""
        self._tool_counter = 0
        self._pending_tool_keys.clear()
        self._active_tool_widgets.clear()
        self._current_tool_section = None

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
        from taui.tui.session_state import SessionState

        st: SessionState | None = None
        if hasattr(event, "session_id") and event.session_id:
            sessions = getattr(self._app, "_sessions", None)
            if sessions:
                st = sessions.get(event.session_id)
        if st is None:
            st = getattr(self._app, "_sessions", None)
            if st is not None:
                st = st.active

        await self._app._finalize_response(st)

        if self._current_tool_section is None:
            self._current_tool_section = Vertical(classes="tool-section")
            await self._app._mount_in_reply(self._current_tool_section, state=st)

        widget = ToolStatusWidget(
            event.tool_name,
            event.args_str,
            arguments=getattr(event, "arguments", None) or None,
        )
        await self._current_tool_section.mount(widget)
        self._active_tool_widgets[event.tool_key] = widget

    def latest_active_widget(self, name: str) -> ToolStatusWidget | None:
        """Return the most recently mounted still-active widget for `name`.

        Used by long-running tools (e.g. sub_agent) that want to surface
        an in-flight progress line on their tool row without knowing
        their own tool_key.
        """
        for key in reversed(list(self._active_tool_widgets.keys())):
            if key.startswith(name + "_"):
                return self._active_tool_widgets[key]
        return None

    async def handle_tool_progress(self, event: ToolProgress) -> None:
        widget: ToolStatusWidget | None = None
        if event.tool_key:
            widget = self._active_tool_widgets.get(event.tool_key)
        if widget is None:
            widget = self.latest_active_widget(event.tool_name)
        if widget is not None:
            widget.set_progress(event.text)

    async def handle_tool_ended(self, event: ToolEnded) -> None:
        widget = self._active_tool_widgets.pop(event.tool_key, None)
        if widget:
            if event.is_error:
                await widget.fail(event.result)
            else:
                await widget.complete(event.result)
