"""Sub-agent widget: live activity while running, full modal on click."""

from __future__ import annotations

from rich.markup import escape
from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from taui.tui.widgets.tool_status import (
    _STATIC_ICON,
    _TOOL_ERROR_COLOR,
    ToolStatusWidget,
)

_LATEST_COLOR = "#6e7681"
_VALUE_COLOR = "#c9d1d9"
_MUTED = "#8b949e"

_DEFAULT_TOOLS = ["read", "glob", "grep", "bash"]
_DEFAULT_SYSTEM_PROMPT = (
    "You are a focused research agent. "
    "Complete the given task concisely and return your findings."
)
_DEFAULT_MAX_TURNS = 25


def _first_line(text: str, limit: int = 200) -> str:
    """First non-empty line of ``text``, truncated to ``limit`` chars."""
    stripped = (text or "").strip()
    if not stripped:
        return ""
    line = stripped.splitlines()[0].strip()
    if len(line) > limit:
        line = line[:limit] + "…"
    return line


class SubAgentModal(ModalScreen[None]):
    """Live inspector for a sub-agent's context and activity.

    Layout (top → bottom):
      • compact header: agent id · model · live status pill · event counter
      • two-column meta strip: goal | tools / max_turns
      • activity log — the main, live-updating panel
      • collapsible system prompt (long text)
    """

    DEFAULT_CSS = """
    SubAgentModal {
        align: center middle;
    }
    #sub-agent-dialog {
        width: 92%;
        height: 92%;
        background: $surface;
        border: thick $surface-lighten-1;
        padding: 1 2;
        layout: vertical;
    }
    #sub-agent-dialog .modal-title {
        width: 100%;
        padding: 0 0 1 0;
        color: cyan;
        text-style: bold;
    }
    #sub-agent-dialog .meta {
        width: 100%;
        height: auto;
        padding: 0 0 1 0;
        border-bottom: solid $surface-lighten-1;
    }
    #sub-agent-dialog .section-header {
        padding: 1 0 0 0;
        text-style: bold;
        color: #58a6ff;
    }
    #sub-agent-dialog .section-body {
        padding: 0 0 0 2;
    }
    #sub-agent-dialog #activity-section {
        height: 1fr;
        min-height: 8;
        padding: 0 0 1 0;
    }
    #sub-agent-dialog #activity-scroll {
        height: 1fr;
        border: solid $surface-lighten-1;
        padding: 0 1;
    }
    #sub-agent-dialog #sysprompt-section {
        height: auto;
        max-height: 14;
        padding: 0 0 1 0;
    }
    #sub-agent-dialog #sysprompt-scroll {
        height: auto;
        max-height: 10;
        border: solid $surface-lighten-1;
        padding: 0 1;
    }
    #sub-agent-dialog .button-container {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
    }
    """

    def __init__(self, widget: SubAgentWidget) -> None:
        super().__init__()
        self._widget = widget
        # Resolved once on open — context (task, tools, system prompt,
        # profile) is fixed for the lifetime of this sub-agent call, so
        # there's no need to re-read SelfEditStore on every refresh tick.
        self._ctx: dict | None = None

    def _resolve_ctx(self) -> dict:
        if self._ctx is None:
            self._ctx = self._widget.resolve_context(
                getattr(self.app, "_config", None)
            )
        return self._ctx

    def compose(self) -> ComposeResult:
        ctx = self._resolve_ctx()
        # Mirror the agent's context top→bottom: system prompt first, then the
        # task/meta strip, then the live conversation (activity log).
        with Container(id="sub-agent-dialog"):
            yield Static(
                self._title_markup(ctx),
                classes="modal-title",
                markup=True,
                id="modal-title",
            )

            with Container(id="sysprompt-section"):
                yield Static(
                    "System prompt",
                    classes="section-header",
                    markup=False,
                )
                with VerticalScroll(id="sysprompt-scroll"):
                    yield Static(
                        ctx["system_prompt"],
                        classes="section-body",
                        markup=False,
                    )

            yield Static(
                self._meta_renderable(ctx),
                classes="meta",
                id="modal-meta",
            )

            with Container(id="activity-section"):
                yield Static(
                    self._activity_header(),
                    classes="section-header",
                    markup=True,
                    id="activity-header",
                )
                with VerticalScroll(id="activity-scroll"):
                    yield Static(
                        self._activity_renderable(),
                        markup=False,
                        id="activity-body",
                    )

            with Horizontal(classes="button-container"):
                yield Button("Close", variant="primary", id="close-button")

    def _title_markup(self, ctx: dict) -> str:
        aid = ctx.get("agent_id") or "(default)"
        model = ctx.get("model")
        status_pill = self._status_pill()
        right_bits = [status_pill]
        if model:
            right_bits.append(f"[{_MUTED}]{escape(model)}[/{_MUTED}]")
        left = f"[bold]sub_agent[/bold] [{_VALUE_COLOR}]{escape(str(aid))}[/]"
        return f"{left}    {'  '.join(right_bits)}"

    def _status_pill(self) -> str:
        w = self._widget
        if w._failed:
            return f"[{_TOOL_ERROR_COLOR}]● failed[/{_TOOL_ERROR_COLOR}]"
        if w._finished:
            return "[#3fb950]● done[/#3fb950]"
        return "[#d29922]● running…[/#d29922]"

    def _meta_renderable(self, ctx: dict) -> Table:
        table = Table.grid(padding=(0, 2, 0, 0))
        table.add_column(style=_MUTED, no_wrap=True)
        table.add_column(style=_VALUE_COLOR, overflow="fold")
        table.add_row("goal", ctx.get("task") or "(no task)")
        if ctx.get("agent_name"):
            table.add_row("name", ctx["agent_name"])
        max_turns = ctx.get("max_turns", _DEFAULT_MAX_TURNS)
        table.add_row("turns", str(max_turns))
        tools = ctx.get("tools") or []
        table.add_row("tools", ", ".join(tools) if tools else "(none)")
        if ctx.get("profile_resolved") is False and ctx.get("agent_id"):
            table.add_row(
                "warn",
                Text(
                    "profile not found on disk; using built-in defaults.",
                    style=_TOOL_ERROR_COLOR,
                ),
            )
        return table

    def _activity_header(self) -> str:
        n = len(self._widget._activity_log)
        label = "event" if n == 1 else "events"
        return f"Activity log  [{_MUTED}]({n} {label})[/{_MUTED}]"

    def _activity_renderable(self) -> Text:
        log = self._widget._activity_log
        if not log:
            return Text("(no activity yet — waiting for the sub-agent to call a tool)",
                        style=_MUTED)
        return Text("\n".join(log))

    def on_mount(self) -> None:
        self.set_interval(0.25, self._refresh)
        # Jump straight to the tail on open so the most recent events are
        # visible regardless of whether the sub-agent is still running.
        self.call_after_refresh(self._scroll_to_tail)

    def _scroll_to_tail(self) -> None:
        try:
            scroll = self.query_one("#activity-scroll", VerticalScroll)
        except Exception:
            return
        scroll.scroll_end(animate=False)

    def _refresh(self) -> None:
        try:
            title = self.query_one("#modal-title", Static)
            header = self.query_one("#activity-header", Static)
            body = self.query_one("#activity-body", Static)
            scroll = self.query_one("#activity-scroll", VerticalScroll)
        except Exception:
            return
        # Capture whether the user is pinned to the bottom *before* the content
        # grows. If they've scrolled up to read earlier events, we leave their
        # position alone instead of yanking them back to the tail every tick.
        at_bottom = scroll.scroll_offset.y >= scroll.max_scroll_y - 1
        title.update(self._title_markup(self._resolve_ctx()))
        header.update(self._activity_header())
        body.update(self._activity_renderable())
        # Only follow the tail while live if the user was already at the bottom.
        if not self._widget._finished and at_bottom:
            self.call_after_refresh(self._scroll_to_tail)

    def on_button_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


class SubAgentWidget(ToolStatusWidget):
    """A specialised tool widget for ``sub_agent`` calls.

    Header renders ``sub_agent <agent_id>`` and the body is a 2x2 grid:
    ``goal`` and ``status`` (where status is the latest inner tool while
    running and the result preview once finished). Clicking opens a
    modal with the full context plus a live-updating activity log.
    """

    DEFAULT_CSS = """
    SubAgentWidget {
        margin: 1 0 1 0;
    }
    SubAgentWidget:hover {
        background: $surface-lighten-1 5%;
    }
    SubAgentWidget #body {
        padding: 0 0 0 2;
    }
    """

    def __init__(self, tool_name: str, args_str: str = "", arguments=None) -> None:
        super().__init__(tool_name, args_str, arguments=arguments)
        self._activity_log: list[str] = []
        self._finished: bool = False
        self._failed: bool = False
        self._final_preview: str = ""
        # Reasoning streams token-by-token; we accumulate here and show the
        # first line live as the status, flushing one summary line into the
        # activity log when the next discrete event (tool/text) arrives.
        self._reasoning_buf: str = ""
        # Header shows just the agent_id next to "sub_agent"; the body
        # carries goal + status as a 2x2 table.
        aid = self._extract_agent_id()
        self.args_str = aid

    @property
    def task_summary(self) -> str:
        task = (self.arguments or {}).get("task") or "sub-agent"
        task = str(task).strip().splitlines()[0] if str(task).strip() else "sub-agent"
        if len(task) > 80:
            task = task[:80] + "…"
        return task

    def _extract_agent_id(self) -> str:
        args = self.arguments or {}
        aid = args.get("agent_id") or args.get("subagent_type") or ""
        return str(aid).strip()

    @property
    def agent_id(self) -> str:
        return self._extract_agent_id()

    @property
    def goal(self) -> str:
        args = self.arguments or {}
        for key in ("task", "description", "prompt", "goal"):
            v = args.get(key)
            if v:
                return str(v).strip().splitlines()[0]
        return ""

    def record_activity(self, line: str) -> None:
        """Append a live tool activity line and refresh the body."""
        line = line.strip()
        if not line:
            return
        self._flush_reasoning()
        self._activity_log.append(line)
        if not self._finished:
            self._refresh_live_body()

    def record_text(self, text: str) -> None:
        """Record assistant text from the sub-agent.

        The full text is kept in the activity log (the modal shows it in
        full); only the inline status line collapses it to one line.
        """
        body = (text or "").strip()
        if not body:
            return
        self._flush_reasoning()
        self._activity_log.append(f"💬 {body}")
        if not self._finished:
            self._refresh_live_body()

    def record_reasoning_delta(self, fragment: str) -> None:
        """Accumulate a streaming reasoning fragment; show it live as status."""
        if not fragment:
            return
        self._reasoning_buf += fragment
        if not self._finished:
            self._refresh_live_body()

    def _flush_reasoning(self) -> None:
        """Move buffered reasoning into the activity log in full (the modal
        shows the complete text; the status line collapses it to one line)."""
        buf = self._reasoning_buf.strip()
        self._reasoning_buf = ""
        if buf:
            self._activity_log.append(f"🤔 {buf}")

    def full_log_text(self) -> str:
        if not self._activity_log:
            return "(no activity yet)"
        return "\n".join(self._activity_log)

    def resolve_context(self, config) -> dict:
        """Resolve full sub-agent context for the modal.

        Pulls the task / tools / max_turns / model / system prompt from
        the captured tool arguments and, when an ``agent_id`` was given,
        from the on-disk agent profile.
        """
        args = dict(self.arguments or {})
        task = str(args.get("task") or "").strip()
        agent_id = (args.get("agent_id") or "").strip().upper() if args.get(
            "agent_id"
        ) else ""
        max_turns = int(args.get("max_turns", _DEFAULT_MAX_TURNS) or _DEFAULT_MAX_TURNS)
        requested_tools = args.get("tools")

        profile = None
        profile_resolved: bool | None = None
        if agent_id and config is not None:
            try:
                from taui.self_edit.store import SelfEditStore

                profile = SelfEditStore(config.working_dir).load_agents().get(
                    agent_id
                )
                profile_resolved = profile is not None
            except Exception:
                profile_resolved = False

        if requested_tools and isinstance(requested_tools, list):
            tools = [t for t in requested_tools if t != "sub_agent"]
        elif profile is not None and getattr(profile, "allowed_tools", None):
            tools = [t for t in profile.allowed_tools if t != "sub_agent"]
        else:
            tools = list(_DEFAULT_TOOLS)

        if profile is not None and getattr(profile, "prompt", ""):
            system_prompt = profile.prompt
        else:
            system_prompt = _DEFAULT_SYSTEM_PROMPT

        model = ""
        if profile is not None and getattr(profile, "model", ""):
            model = profile.model

        return {
            "task": task,
            "agent_id": agent_id,
            "agent_name": getattr(profile, "name", "") if profile else "",
            "tools": tools,
            "max_turns": max_turns,
            "model": model,
            "system_prompt": system_prompt,
            "profile_resolved": profile_resolved,
        }

    def _status_line(self) -> str:
        """The single line shown in the body — first line of the latest event
        (tool, reasoning, or assistant text), or the final preview."""
        if self._failed:
            return _first_line(self._final_preview) or "failed"
        if self._finished:
            return _first_line(self._final_preview) or "finished"
        # Reasoning currently streaming — surface the latest thought.
        if self._reasoning_buf.strip():
            return _first_line(self._reasoning_buf)
        if self._activity_log:
            return _first_line(self._activity_log[-1])
        return "starting…"

    def _render_body(self) -> None:
        if not self.is_mounted:
            return
        try:
            body = self.query_one("#body", Static)
        except Exception:
            return

        goal = self.goal or "(no goal)"
        if len(goal) > 200:
            goal = goal[:200] + "…"
        status = self._status_line()
        status_style = _TOOL_ERROR_COLOR if self._failed else _LATEST_COLOR

        table = Table.grid(padding=(0, 2, 0, 0))
        table.add_column(style=_MUTED, no_wrap=True)
        table.add_column(style=_VALUE_COLOR, overflow="fold")
        table.add_row("goal", goal)
        # Status is capped to a single line: never wrap, crop with an ellipsis.
        table.add_row(
            "status",
            Text(status, style=status_style, no_wrap=True, overflow="ellipsis"),
        )

        body.update(table)
        body.styles.display = "block"

    # Backwards-compatible alias used elsewhere.
    def _refresh_live_body(self) -> None:
        self._render_body()

    def on_mount(self) -> None:
        super().on_mount()
        # Defer to after first refresh so the body Static is laid out and
        # the new height (2 rows) actually triggers a re-layout.
        self.call_after_refresh(self._render_body)

    async def complete(self, output: str = "") -> None:
        self._stop_spinner()
        self._flush_reasoning()
        self._finished = True
        self._failed = False
        preview = output.strip().splitlines()[0] if output and output.strip() else ""
        if len(preview) > 200:
            preview = preview[:200] + "…"
        self._final_preview = preview or "finished"
        if not self.is_mounted:
            return
        self._set_icon(_STATIC_ICON)
        # Don't add a header suffix — body carries the status.
        self.query_one("#info", Static).update(self._header_markup())
        self._render_body()

    async def fail(self, error: str = "") -> None:
        self._stop_spinner()
        self._flush_reasoning()
        self._finished = True
        self._failed = True
        err = (error or "").strip().splitlines()[0] if error else ""
        if len(err) > 200:
            err = err[:200] + "…"
        self._final_preview = err or "failed"
        if not self.is_mounted:
            return
        self._set_icon(_STATIC_ICON)
        self.query_one("#info", Static).update(self._header_markup())
        self._render_body()

    async def on_click(self, event: events.Click) -> None:
        event.stop()
        await self.app.push_screen(SubAgentModal(self))
