"""
Textual-based terminal UI for taui.

Opt-in via ``taui --tui``. Requires the ``textual`` package.
Provides a rich split-pane interface with message history,
live tool output, and input bar.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Input, RichLog, Static

from taui.commands.builtins import register_builtins as register_builtin_commands
from taui.commands.registry import CommandRegistry
from taui.config import Config
from taui.session import Session


class MessageLog(RichLog):
    """Scrollable message history."""

    DEFAULT_CSS = """
    MessageLog {
        border: solid $accent;
        height: 1fr;
    }
    """


class ToolLog(RichLog):
    """Tool call and result display."""

    DEFAULT_CSS = """
    ToolLog {
        border: solid $secondary;
        height: 10;
        dock: bottom;
    }
    """


class StatusBar(Static):
    """Shows provider/model/cwd."""

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """


class TauiApp(App[None]):
    """Textual application for taui."""

    TITLE = "taui"
    CSS = """
    #main {
        height: 1fr;
    }
    #input-bar {
        dock: bottom;
        height: 3;
        padding: 0 1;
    }
    """
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear", "Clear"),
    ]

    def __init__(self, config: Config | None = None) -> None:
        super().__init__()
        self._config = config or Config.load()
        self._session: Session | None = None
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main"):
            yield MessageLog(id="messages", wrap=True, highlight=True, markup=True)
            yield ToolLog(id="tools", wrap=True, highlight=True, markup=True)
        yield StatusBar(id="status")
        yield Input(placeholder="Type a message… (/help for commands)", id="input-bar")
        yield Footer()

    async def on_mount(self) -> None:
        self._session = await Session.create(self._config)
        self._wire_callbacks()
        self._commands = self._build_commands()
        self._update_status()
        self.query_one("#input-bar", Input).focus()

    def _build_commands(self) -> CommandRegistry:
        registry = CommandRegistry()
        register_builtin_commands(
            registry,
            get_session=lambda: self._session,
            get_tracker=lambda: self._session.cost_tracker if self._session else None,
            get_extensions=lambda: self._session._ext_registry if self._session else None,
        )
        return registry

    def _update_status(self) -> None:
        assert self._session is not None
        status = self.query_one("#status", StatusBar)
        p = self._session.provider_name
        m = self._session.model_name
        cwd = self._session.working_dir
        # Collect status hook segments (sync)
        extras: list[str] = []
        for fn in self._session.hooks._hooks.get("status", []):
            try:
                seg = fn(self._session)
                if seg:
                    extras.append(seg)
            except Exception:
                pass
        extra_str = ("  ·  " + "  ·  ".join(extras)) if extras else ""
        if self._session.self_edit:
            status.update(f" ⚙ SELF-EDIT  ·  {p}/{m}  ·  {cwd}{extra_str}")
            status.styles.background = "yellow"
            status.styles.color = "black"
        else:
            status.update(f" {p}/{m}  ·  {cwd}{extra_str}")
            status.styles.background = None
            status.styles.color = None
        self.query_one("#input-bar", Input).focus()

    def _wire_callbacks(self) -> None:
        assert self._session is not None
        loop = self._session._loop
        loop._on_tool_call = self._on_tool_call
        loop._on_tool_result = self._on_tool_result
        loop._on_text = self._on_text

        for name in self._session._registry.names:
            tool = self._session._registry.get(name)
            if hasattr(tool, "_ask") and tool.name == "question":
                tool._ask = self._on_question

    async def _on_tool_call(self, call_id: str, name: str, arguments: dict) -> None:
        tools = self.query_one("#tools", ToolLog)
        args_short = ", ".join(f"{k}={_trunc(str(v))}" for k, v in arguments.items())
        tools.write(f"[cyan]▸ {name}[/cyan]({args_short})")
        if self._session:
            await self._session.hooks.run("on_tool_call", name, arguments, self._session)

    async def _on_tool_result(
        self, call_id: str, name: str, content: str, is_error: bool
    ) -> None:
        tools = self.query_one("#tools", ToolLog)
        if is_error:
            first = content.split("\n")[0][:120]
            tools.write(f"[red]✗ {name}: {first}[/red]")
        else:
            lines = content.split("\n")
            if len(lines) <= 3:
                for line in lines:
                    if line.strip():
                        tools.write(f"  [dim]{line[:150]}[/dim]")
            else:
                tools.write(f"  [dim]({len(lines)} lines)[/dim]")
        if self._session:
            await self._session.hooks.run("on_tool_result", name, content, is_error, self._session)

    async def _on_text(self, text: str) -> None:
        pass  # shown after run completes

    async def _on_question(
        self, question: str, options: list[str] | None
    ) -> str | None:
        messages = self.query_one("#messages", MessageLog)
        messages.write(f"[yellow]? {question}[/yellow]")
        if options:
            for i, opt in enumerate(options, 1):
                messages.write(f"  [dim]{i}. {opt}[/dim]")
        return None  # TUI question support is minimal for now

    @on(Input.Submitted, "#input-bar")
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.clear()
        if not text:
            return
        if self._busy:
            return

        messages = self.query_one("#messages", MessageLog)

        if text.startswith("/"):
            await self._handle_command(text)
            return

        messages.write(f"[green]> {text}[/green]")
        self._send_message(text)

    @work(exclusive=True)
    async def _send_message(self, text: str) -> None:
        assert self._session is not None
        messages = self.query_one("#messages", MessageLog)
        self._busy = True
        try:
            result = await self._session.send(text)
            if result.text:
                messages.write(result.text)

            turns = result.turns
            summary = f"[dim][{turns} turn{'s' if turns != 1 else ''}"
            tracker = self._session.cost_tracker
            if tracker.total_cost_usd > 0:
                summary += f" | ${tracker.total_cost_usd:.4f}"
            # Turn summary hooks (sync)
            for fn in self._session.hooks._hooks.get("turn_summary", []):
                try:
                    extra = fn(result, self._session)
                    if extra:
                        summary += f" | {extra}"
                except Exception:
                    pass
            summary += "][/dim]"
            messages.write(summary)
        except Exception as exc:
            messages.write(f"[red]Error: {exc}[/red]")
        finally:
            self._busy = False

    async def _handle_command(self, cmd: str) -> None:
        messages = self.query_one("#messages", MessageLog)
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()
        if command in ("/quit", "/q", "/exit"):
            self.exit()
            return
        if command == "/clear":
            messages.clear()
            return

        # Dispatch through command registry
        result = await self._commands.execute(cmd)
        if result.error:
            messages.write(f"[yellow]{result.output}[/yellow]")
        elif self._session and self._session.self_edit:
            messages.write(f"[yellow]{result.output}[/yellow]")
        else:
            messages.write(f"[dim]{result.output}[/dim]")

        # Rewire after mode/session changes
        action = result.metadata.get("action") if result.metadata else None
        if action in ("self_edit_on", "self_edit_off", "new_session", "session_resumed"):
            self._wire_callbacks()
            self._update_status()

    def action_clear(self) -> None:
        self.query_one("#messages", MessageLog).clear()

    async def action_quit(self) -> None:
        if self._session:
            await self._session.close()
        self.exit()


def _trunc(s: str, n: int = 40) -> str:
    return s[:n - 3] + "..." if len(s) > n else s


def run_tui(config: Config | None = None) -> None:
    """Launch the Textual TUI (blocking)."""
    app = TauiApp(config)
    app.run()
