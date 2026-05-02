"""Tool status widget with animated braille spinner."""

from __future__ import annotations

import asyncio
from typing import Optional

from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


class ToolStatusWidget(Widget):
    """Animated status for a single tool execution."""

    DEFAULT_CSS = """
    ToolStatusWidget {
        width: 100%;
        height: auto;
        layout: horizontal;
        padding: 0 1;
    }
    ToolStatusWidget .tool-icon {
        width: auto;
        height: 1;
    }
    ToolStatusWidget .tool-info {
        width: 1fr;
        height: auto;
    }
    """

    SPINNER_FRAMES = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]

    def __init__(self, tool_name: str, args_str: str) -> None:
        super().__init__()
        self.tool_name = tool_name
        self.args_str = args_str
        self._frame = 0
        self._spinning = True
        self._completed = False
        self._task: Optional[asyncio.Task] = None

    def compose(self) -> ComposeResult:
        yield Static("", classes="tool-icon", id="icon")
        yield Static("", classes="tool-info", id="info")

    async def on_mount(self) -> None:
        self._task = asyncio.create_task(self._spin())

    async def on_unmount(self) -> None:
        self._spinning = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _spin(self) -> None:
        start = asyncio.get_event_loop().time()
        try:
            while self._spinning and not self._completed:
                if asyncio.get_event_loop().time() - start > 300.0:
                    await self.fail("Tool timed out after 5 minutes")
                    return
                frame = self.SPINNER_FRAMES[self._frame % len(self.SPINNER_FRAMES)]
                self.query_one("#icon", Static).update(
                    Text.from_markup(f"   [bold #3fb950]{frame}[/bold #3fb950] ")
                )
                self.query_one("#info", Static).update(
                    Text.from_markup(
                        f"[#6BB6FF]{escape(self.tool_name)}[/#6BB6FF]"
                        f" [dim #8b949e]{escape(self.args_str)}[/dim #8b949e]"
                    )
                )
                self._frame += 1
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

    async def complete(self, output: str = "") -> None:
        if not self.is_mounted:
            return
        self._completed = True
        self._spinning = False
        preview = ""
        if output:
            p = output.strip()[:150]
            if len(output.strip()) > 150:
                p += "..."
            preview = f" [dim #8b949e]{escape(p)}[/dim #8b949e]"
        self.query_one("#icon", Static).update(
            Text.from_markup("   [bold #3fb950]⣿[/bold #3fb950] ")
        )
        self.query_one("#info", Static).update(
            Text.from_markup(
                f"[#6BB6FF]{escape(self.tool_name)}[/#6BB6FF]"
                f"{preview}"
            )
        )
        if self._task and not self._task.done():
            self._task.cancel()

    async def fail(self, error: str = "") -> None:
        if not self.is_mounted:
            return
        self._completed = True
        self._spinning = False
        err_msg = ""
        if error:
            p = error.strip()[:200]
            if len(error.strip()) > 200:
                p += "..."
            err_msg = f" [#f97583]{escape(p)}[/#f97583]"
        self.query_one("#icon", Static).update(
            Text.from_markup("   [bold #f97583]⣿[/bold #f97583] ")
        )
        self.query_one("#info", Static).update(
            Text.from_markup(
                f"[#6BB6FF]{escape(self.tool_name)}[/#6BB6FF]"
                f" [#f97583]Failed[/#f97583]{err_msg}"
            )
        )
        if self._task and not self._task.done():
            self._task.cancel()
