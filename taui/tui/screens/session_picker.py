"""Session picker modal screen."""

from __future__ import annotations

import time
from datetime import datetime

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option


class SessionPickerScreen(ModalScreen[str | None]):
    """Modal for selecting a previous session to resume."""

    DEFAULT_CSS = """
    SessionPickerScreen {
        align: center middle;
    }
    #session-picker-dialog {
        width: 90;
        max-width: 95%;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick #586069;
        padding: 1 2;
    }
    #session-picker-dialog .dialog-title {
        width: 100%;
        content-align: center middle;
        padding: 0 0 1 0;
        color: cyan;
        text-style: bold;
    }
    #session-picker-dialog OptionList {
        height: auto;
        max-height: 18;
    }
    #session-picker-dialog .hint {
        padding: 1 0 0 0;
        color: $text-muted;
    }
    """

    def __init__(self, sessions: list[dict]) -> None:
        super().__init__()
        self._sessions = sessions[:20]

    def compose(self) -> ComposeResult:
        with Container(id="session-picker-dialog"):
            yield Label("[bold]Resume Session[/bold]", classes="dialog-title")
            yield OptionList(
                *[
                    Option(_session_prompt(session), id=str(session["session_id"]))
                    for session in self._sessions
                ],
                id="session-options",
            )
            yield Label("Enter to resume, Esc to cancel", classes="hint")

    def on_mount(self) -> None:
        self.query_one("#session-options", OptionList).focus()

    @on(OptionList.OptionSelected)
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if option_id is None:
            option_id = str(self._sessions[event.option_index]["session_id"])
        self.dismiss(str(option_id))

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)


def _session_prompt(session: dict) -> Text:
    sid = str(session.get("session_id", ""))
    desc = str(
        session.get("description")
        or _fallback_name(session)
    )[:40]
    mode = str(session.get("mode", "normal"))
    msgs = int(session.get("message_count", 0) or 0)
    ago = _time_ago(float(session.get("last_active", 0) or 0))
    mode_tag = " [ext]" if mode == "extensions" else ""

    text = Text()
    text.append(sid, style="bold cyan")
    text.append(f"  {desc:<40s}  ", style="white")
    text.append(f"{msgs:>3} msgs  {ago}{mode_tag}", style="dim")
    return text


def _fallback_name(session: dict) -> str:
    """Label for sessions that never called session_name — their created time."""
    ts = float(session.get("created_at", 0) or 0)
    if ts <= 0:
        return "(unnamed)"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _time_ago(ts: float) -> str:
    if ts <= 0:
        return "unknown"
    delta = time.time() - ts
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    return f"{int(delta / 86400)}d ago"
