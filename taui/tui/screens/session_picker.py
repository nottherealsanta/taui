"""Session picker modal screen with tree view."""

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
        self._sessions = sessions[:50]
        self._ordered = _build_tree_order(self._sessions)

    def compose(self) -> ComposeResult:
        with Container(id="session-picker-dialog"):
            yield Label("[bold]Resume Session[/bold]", classes="dialog-title")
            yield OptionList(
                *[
                    Option(
                        _session_prompt(s["session"], s["depth"]),
                        id=str(s["session"]["session_id"]),
                    )
                    for s in self._ordered
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
            idx = event.option_index
            if idx < len(self._ordered):
                option_id = str(self._ordered[idx]["session"]["session_id"])
        self.dismiss(str(option_id) if option_id else None)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)


def _build_tree_order(sessions: list[dict]) -> list[dict]:
    """Order sessions as a tree based on parent_session_id.

    Returns list of {"session": dict, "depth": int} in display order.
    Root sessions (no parent) come first sorted by last_active desc,
    children are nested under their parent.
    """
    by_id: dict[str, dict] = {}
    children: dict[str, list[dict]] = {}

    for s in sessions:
        sid = str(s.get("session_id", ""))
        by_id[sid] = s
        parent = s.get("parent_session_id")
        if parent and str(parent) != sid:
            children.setdefault(str(parent), []).append(s)

    # Roots: sessions with no parent or parent not in current set
    roots = [
        s
        for s in sessions
        if not s.get("parent_session_id") or str(s.get("parent_session_id")) not in by_id
    ]

    result: list[dict] = []

    def _add(session: dict, depth: int) -> None:
        result.append({"session": session, "depth": depth})
        sid = str(session.get("session_id", ""))
        for child in children.get(sid, []):
            _add(child, depth + 1)

    for root in roots:
        _add(root, 0)

    return result


def _session_prompt(session: dict, depth: int = 0) -> Text:
    sid = str(session.get("session_id", ""))
    desc = str(session.get("description") or _fallback_name(session))[:40]
    mode = str(session.get("mode", "normal"))
    msgs = int(session.get("message_count", 0) or 0)
    ago = _time_ago(float(session.get("last_active", 0) or 0))
    mode_tag = " [ext]" if mode == "extensions" else ""

    # Tree prefix
    prefix = ""
    if depth > 0:
        prefix = "  " * (depth - 1) + "├─ "

    text = Text()
    if prefix:
        text.append(prefix, style="dim")
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
