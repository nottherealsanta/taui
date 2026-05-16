"""Tool status widget for tool execution."""

from __future__ import annotations

from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

# Unified tool colors: everything tool-related (including errors) is gray.
_TOOL_NAME_COLOR = "#8b949e"
_TOOL_DETAIL_COLOR = "#6e7681"
_TOOL_ERROR_COLOR = "#6e7681"
_TOOL_ICON_COLOR = "#6e7681"


class ToolStatusWidget(Widget):
    """Status display for a single tool execution."""

    DEFAULT_CSS = """
    ToolStatusWidget {
        width: 100%;
        height: auto;
        layout: horizontal;
        padding: 0 0;
    }
    ToolStatusWidget .tool-icon {
        width: auto;
        height: 1;
    }
    ToolStatusWidget .tool-info {
        width: 1fr;
        height: 1;
    }
    """

    def __init__(self, tool_name: str, args_str: str) -> None:
        super().__init__()
        self.tool_name = tool_name
        self.args_str = " ".join(args_str.split())

    def compose(self) -> ComposeResult:
        yield Static(
            Text.from_markup(f"[{_TOOL_ICON_COLOR}]✦[/{_TOOL_ICON_COLOR}] "),
            classes="tool-icon",
            id="icon",
        )
        yield Static(
            Text.from_markup(
                f"[{_TOOL_NAME_COLOR}]{escape(self.tool_name)}[/{_TOOL_NAME_COLOR}]"
                f" [{_TOOL_DETAIL_COLOR}]{escape(self.args_str)}[/{_TOOL_DETAIL_COLOR}]"
            ),
            classes="tool-info",
            id="info",
        )

    async def complete(self, output: str = "") -> None:
        if not self.is_mounted:
            return
        preview = ""
        if output:
            line = " ".join(output.strip().split())[:150]
            if len(" ".join(output.strip().split())) > 150:
                line += "..."
            preview = f" [{_TOOL_DETAIL_COLOR}]{escape(line)}[/{_TOOL_DETAIL_COLOR}]"
        self.query_one("#info", Static).update(
            Text.from_markup(
                f"[{_TOOL_NAME_COLOR}]{escape(self.tool_name)}[/{_TOOL_NAME_COLOR}]"
                f"{preview}"
            )
        )

    async def fail(self, error: str = "") -> None:
        if not self.is_mounted:
            return
        err_msg = ""
        if error:
            line = " ".join(error.strip().split())[:200]
            if len(" ".join(error.strip().split())) > 200:
                line += "..."
            err_msg = f" [{_TOOL_ERROR_COLOR}]{escape(line)}[/{_TOOL_ERROR_COLOR}]"
        self.query_one("#info", Static).update(
            Text.from_markup(
                f"[{_TOOL_NAME_COLOR}]{escape(self.tool_name)}[/{_TOOL_NAME_COLOR}]"
                f" [{_TOOL_ERROR_COLOR}]Failed[/{_TOOL_ERROR_COLOR}]{err_msg}"
            )
        )
