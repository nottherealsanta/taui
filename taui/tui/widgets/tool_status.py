"""Tool status widget for tool execution."""

from __future__ import annotations

from typing import Any

from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Static

try:
    from textual.content import Content
    from textual_diff_view import DiffView as _BaseDiffView  # type: ignore

    class DiffView(_BaseDiffView):  # type: ignore[misc, valid-type]
        """DiffView without the built-in '📄 <path> (+N, -M)' title — we
        already render an equivalent header in the tool row above."""

        def get_title(self) -> Content:  # type: ignore[override]
            return Content("")
except Exception:  # pragma: no cover — optional dep
    DiffView = None  # type: ignore

from taui.tui.widgets.tool_formatters import (
    format_args,
    format_output,
    is_slow_tool,
)

# Unified tool colors: everything tool-related (including errors) is gray.
_TOOL_NAME_COLOR = "#8b949e"
_TOOL_DETAIL_COLOR = "#6e7681"
_TOOL_ERROR_COLOR = "#6e7681"
_TOOL_ICON_COLOR = "#6e7681"

# Diff colors used for the edit tool. Kept subdued so they don't dominate
# the gray tool palette.
_DIFF_ADD_COLOR = "#3fb950"
_DIFF_DEL_COLOR = "#f85149"

_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_STATIC_ICON = "✦"


class ToolStatusWidget(Widget):
    """Status display for a single tool execution.

    Layout:
        <icon> <tool_name> <args>  <summary>
                            <body line 1>
                            <body line 2>
                            ...
    """

    DEFAULT_CSS = """
    ToolStatusWidget {
        width: 100%;
        height: auto;
        layout: vertical;
        padding: 0 0;
    }
    ToolStatusWidget #header {
        width: 100%;
        height: auto;
    }
    ToolStatusWidget .tool-icon {
        width: 2;
        height: 1;
    }
    ToolStatusWidget .tool-info {
        width: 1fr;
        height: auto;
    }
    ToolStatusWidget #body {
        width: 1fr;
        height: auto;
        padding: 0 0 0 2;
    }
    ToolStatusWidget .tool-diff-view {
        width: 1fr;
        height: auto;
        max-height: 24;
        margin: 0 0 0 2;
    }
    ToolStatusWidget .tool-diff-view .title {
        display: none;
    }
    """

    def __init__(
        self,
        tool_name: str,
        args_str: str = "",
        arguments: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self.tool_name = tool_name
        self.arguments: dict[str, Any] = arguments or {}
        # Prefer structured formatting when arguments are available; fall back
        # to the raw string for backward compatibility (older call sites).
        if arguments is not None:
            self.args_str = format_args(tool_name, arguments)
        else:
            self.args_str = " ".join(args_str.split())
        self._spinner_timer: Timer | None = None
        self._spinner_index = 0

    # ── lifecycle ──────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Horizontal(id="header"):
            yield Static(
                Text.from_markup(
                    f"[{_TOOL_ICON_COLOR}]{_STATIC_ICON}[/{_TOOL_ICON_COLOR}] "
                ),
                classes="tool-icon",
                id="icon",
            )
            yield Static(
                self._header_markup(),
                classes="tool-info",
                id="info",
            )
        yield Static("", id="body")

    def on_mount(self) -> None:
        if is_slow_tool(self.tool_name):
            self._start_spinner()

    def on_unmount(self) -> None:
        self._stop_spinner()

    # ── header / body rendering ────────────────────────────────────────────

    def _header_markup(self, suffix: str = "") -> Text:
        parts = (
            f"[{_TOOL_NAME_COLOR}]{escape(self.tool_name)}[/{_TOOL_NAME_COLOR}]"
        )
        if self.args_str:
            parts += (
                f" [{_TOOL_DETAIL_COLOR}]{escape(self.args_str)}"
                f"[/{_TOOL_DETAIL_COLOR}]"
            )
        if suffix:
            parts += suffix
        return Text.from_markup(parts)

    def _set_icon(self, char: str, color: str = _TOOL_ICON_COLOR) -> None:
        if not self.is_mounted:
            return
        try:
            self.query_one("#icon", Static).update(
                Text.from_markup(f"[{color}]{char}[/{color}] ")
            )
        except Exception:
            pass

    def _set_body(self, lines: list[Text]) -> None:
        if not self.is_mounted:
            return
        try:
            body = self.query_one("#body", Static)
        except Exception:
            return
        if not lines:
            body.update("")
            body.styles.display = "none"
            return
        body.styles.display = "block"
        combined = Text("\n").join(lines)
        body.update(combined)

    # ── spinner ────────────────────────────────────────────────────────────

    def _start_spinner(self) -> None:
        if self._spinner_timer is not None:
            return
        self._spinner_index = 0
        self._tick_spinner()
        self._spinner_timer = self.set_interval(0.1, self._tick_spinner)

    def _stop_spinner(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    def _tick_spinner(self) -> None:
        frame = _SPINNER_FRAMES[self._spinner_index % len(_SPINNER_FRAMES)]
        self._spinner_index += 1
        self._set_icon(frame)

    # ── DiffView mounting ──────────────────────────────────────────────────

    async def _mount_diff_view(self, data: dict) -> None:
        if DiffView is None or not self.is_mounted:
            return
        path = data.get("path") or "edit"
        before = data.get("before") or ""
        after = data.get("after") or ""
        try:
            view = DiffView(
                path, path, before, after,
                split=False,
                annotations=True,
                wrap=False,
                classes="tool-diff-view",
            )
            await self.mount(view)
        except Exception:
            # Fall back silently — the +N/-N summary is already shown.
            pass

    # ── completion / failure ───────────────────────────────────────────────

    async def complete(self, output: str = "") -> None:
        self._stop_spinner()
        if not self.is_mounted:
            return
        self._set_icon(_STATIC_ICON)

        formatted = format_output(self.tool_name, self.arguments, output)
        suffix = ""
        if formatted["summary"]:
            suffix = (
                f"  [{_TOOL_DETAIL_COLOR}]{escape(formatted['summary'])}"
                f"[/{_TOOL_DETAIL_COLOR}]"
            )
        self.query_one("#info", Static).update(self._header_markup(suffix))

        body_lines: list[Text] = []
        for line in formatted["body"]:
            body_lines.append(
                Text.from_markup(
                    f"[{_TOOL_DETAIL_COLOR}]{escape(line)}[/{_TOOL_DETAIL_COLOR}]"
                )
            )
        self._set_body(body_lines)

        diff_view_data = formatted.get("diff_view")
        if diff_view_data:
            await self._mount_diff_view(diff_view_data)

    async def fail(self, error: str = "") -> None:
        self._stop_spinner()
        if not self.is_mounted:
            return
        self._set_icon(_STATIC_ICON)

        err_line = ""
        if error:
            collapsed = " ".join(error.strip().split())
            err_line = collapsed[:200] + ("…" if len(collapsed) > 200 else "")
        suffix = f"  [{_TOOL_ERROR_COLOR}]Failed[/{_TOOL_ERROR_COLOR}]"
        self.query_one("#info", Static).update(self._header_markup(suffix))

        body_lines: list[Text] = []
        if err_line:
            body_lines.append(
                Text.from_markup(
                    f"[{_TOOL_ERROR_COLOR}]{escape(err_line)}[/{_TOOL_ERROR_COLOR}]"
                )
            )
        self._set_body(body_lines)
