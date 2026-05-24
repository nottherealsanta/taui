"""Sub-agent widget: live activity while running, full modal on click."""

from __future__ import annotations

from rich.markup import escape
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from taui.tui.widgets.tool_status import ToolStatusWidget

_LATEST_COLOR = "#6e7681"
_VALUE_COLOR = "#c9d1d9"
_MUTED = "#8b949e"

_DEFAULT_TOOLS = ["read", "glob", "grep", "bash"]
_DEFAULT_SYSTEM_PROMPT = (
    "You are a focused research agent. "
    "Complete the given task concisely and return your findings."
)
_DEFAULT_MAX_TURNS = 10


class SubAgentModal(ModalScreen[None]):
    """Modal showing the full sub-agent context plus its live activity log.

    The modal renders:
      • the task description the parent gave the sub-agent
      • the resolved agent id / model / max-turns
      • the allowed tool list
      • the system prompt the sub-agent runs with
      • the activity log (auto-refreshed every 0.5s while the sub-agent
        is still running)
    """

    DEFAULT_CSS = """
    SubAgentModal {
        align: center middle;
    }
    #sub-agent-dialog {
        width: 90%;
        height: 90%;
        background: $surface;
        border: thick $surface-lighten-1;
        padding: 1 2;
    }
    #sub-agent-dialog .dialog-title {
        width: 100%;
        content-align: center middle;
        padding: 0 0 1 0;
        color: cyan;
        text-style: bold;
    }
    #sub-agent-dialog #sub-agent-scroll {
        height: 1fr;
        border-top: solid $surface-lighten-1;
        padding: 1 0 0 0;
    }
    #sub-agent-dialog .section-header {
        padding: 1 0 0 0;
        text-style: bold;
        color: #58a6ff;
    }
    #sub-agent-dialog .section-body {
        padding: 0 0 0 2;
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

    def compose(self) -> ComposeResult:
        ctx = self._widget.resolve_context(getattr(self.app, "_config", None))
        with Container(id="sub-agent-dialog"):
            yield Static(
                f"[bold]Sub-agent: {escape(self._widget.task_summary)}[/bold]",
                classes="dialog-title",
                markup=True,
            )
            with VerticalScroll(id="sub-agent-scroll"):
                yield Static("Task", classes="section-header", markup=False)
                yield Static(
                    ctx["task"] or "(no task)",
                    classes="section-body",
                    markup=False,
                )

                yield Static(
                    "Configuration", classes="section-header", markup=False,
                )
                yield Static(
                    self._format_config(ctx),
                    classes="section-body",
                    markup=True,
                )

                yield Static("Tools", classes="section-header", markup=False)
                yield Static(
                    self._format_tools(ctx["tools"]),
                    classes="section-body",
                    markup=True,
                )

                yield Static(
                    "System prompt", classes="section-header", markup=False,
                )
                yield Static(
                    ctx["system_prompt"],
                    classes="section-body",
                    markup=False,
                )

                yield Static(
                    "Activity log", classes="section-header", markup=False,
                )
                yield Static(
                    self._widget.full_log_text(),
                    markup=False,
                    classes="section-body",
                    id="sub-agent-body",
                )
            with Horizontal(classes="button-container"):
                yield Button("Close", variant="primary", id="close-button")

    @staticmethod
    def _format_config(ctx: dict) -> str:
        parts: list[str] = []
        agent = ctx.get("agent_id") or "(default)"
        parts.append(
            f"[{_MUTED}]agent_id:[/{_MUTED}]  [{_VALUE_COLOR}]{escape(str(agent))}[/]"
        )
        if ctx.get("agent_name"):
            parts.append(
                f"[{_MUTED}]name:[/{_MUTED}]      "
                f"[{_VALUE_COLOR}]{escape(ctx['agent_name'])}[/]"
            )
        if ctx.get("model"):
            parts.append(
                f"[{_MUTED}]model:[/{_MUTED}]     "
                f"[{_VALUE_COLOR}]{escape(ctx['model'])}[/]"
            )
        parts.append(
            f"[{_MUTED}]max_turns:[/{_MUTED}] "
            f"[{_VALUE_COLOR}]{ctx.get('max_turns', _DEFAULT_MAX_TURNS)}[/]"
        )
        if ctx.get("profile_resolved") is False and ctx.get("agent_id"):
            parts.append(
                "[red]Profile not found on disk; using built-in defaults.[/red]"
            )
        return "\n".join(parts)

    @staticmethod
    def _format_tools(tools: list[str]) -> str:
        if not tools:
            return f"[{_MUTED}](none)[/]"
        return ", ".join(f"[{_VALUE_COLOR}]{escape(t)}[/]" for t in tools)

    def on_mount(self) -> None:
        # Refresh every 0.5s so a live sub-agent keeps the activity-log updated.
        self.set_interval(0.5, self._refresh)

    def _refresh(self) -> None:
        try:
            body = self.query_one("#sub-agent-body", Static)
        except Exception:
            return
        body.update(self._widget.full_log_text())

    def on_button_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


class SubAgentWidget(ToolStatusWidget):
    """A specialised tool widget for ``sub_agent`` calls.

    While the sub-agent runs, the body shows the most recent activity
    line (e.g., the latest tool the child called). When the call
    completes, the body collapses to ``✓ Finished`` and the widget
    becomes clickable to open a modal with the full sub-agent context
    (task, system prompt, allowed tools, model) and activity log.
    """

    DEFAULT_CSS = """
    SubAgentWidget:hover {
        background: $surface-lighten-1 5%;
    }
    """

    def __init__(self, tool_name: str, args_str: str = "", arguments=None) -> None:
        super().__init__(tool_name, args_str, arguments=arguments)
        self._activity_log: list[str] = []
        self._finished: bool = False

    @property
    def task_summary(self) -> str:
        task = (self.arguments or {}).get("task") or self.args_str or "sub-agent"
        task = str(task).strip().splitlines()[0] if str(task).strip() else "sub-agent"
        if len(task) > 80:
            task = task[:80] + "…"
        return task

    def record_activity(self, line: str) -> None:
        """Append a live activity line and refresh the body."""
        line = line.strip()
        if not line:
            return
        self._activity_log.append(line)
        if not self._finished:
            self._refresh_live_body()

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

    def _refresh_live_body(self) -> None:
        if not self.is_mounted:
            return
        try:
            body = self.query_one("#body", Static)
        except Exception:
            return
        latest = self._activity_log[-1]
        if len(latest) > 200:
            latest = latest[:200] + "…"
        text = Text.from_markup(
            f"[{_LATEST_COLOR}]└ {escape(latest)}[/{_LATEST_COLOR}]"
        )
        body.update(text)
        body.styles.display = "block"

    async def complete(self, output: str = "") -> None:
        await super().complete(output)
        self._finished = True
        if output:
            preview = output.strip().splitlines()[0] if output.strip() else ""
            if len(preview) > 80:
                preview = preview[:80] + "…"
            self._activity_log.append(f"== Finished: {preview}")
        else:
            self._activity_log.append("== Finished")

    async def fail(self, error: str = "") -> None:
        await super().fail(error)
        self._finished = True
        self._activity_log.append(f"== Failed: {error}" if error else "== Failed")

    async def on_click(self, event: events.Click) -> None:
        event.stop()
        await self.app.push_screen(SubAgentModal(self))
