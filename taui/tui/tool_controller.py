"""Tool call UI tracking — start/end matching and widget lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Vertical, VerticalScroll

from taui.tui.messages import ToolEnded, ToolStarted
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

    async def on_tool_call(
        self, call_id: str, name: str, arguments: dict
    ) -> None:
        self._tool_counter += 1
        tool_key = f"{name}_{self._tool_counter}"
        self._pending_tool_keys.setdefault(name, []).append(tool_key)
        args_short = ", ".join(
            f"{k}={_trunc(str(v))}" for k, v in arguments.items()
        )
        self._app.post_message(ToolStarted(tool_key, name, args_short))

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
        self._app.post_message(ToolEnded(tool_key, name, content, is_error))

        session = self._app._session
        if session:
            await session.hooks.run(
                "on_tool_result", name, content, is_error, session
            )

    async def handle_tool_started(self, event: ToolStarted) -> None:
        await self._app._finalize_response()

        chat_log = self._app.query_one("#chat-log", VerticalScroll)
        if self._current_tool_section is None:
            self._current_tool_section = Vertical(classes="tool-section")
            await chat_log.mount(self._current_tool_section)

        widget = ToolStatusWidget(event.tool_name, event.args_str)
        await self._current_tool_section.mount(widget)
        self._active_tool_widgets[event.tool_key] = widget

    async def handle_tool_ended(self, event: ToolEnded) -> None:
        widget = self._active_tool_widgets.pop(event.tool_key, None)
        if widget:
            if event.is_error:
                await widget.fail(event.result)
            else:
                await widget.complete(event.result)
