"""Left sidebar — tabbed Sessions / Files panel."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import DirectoryTree, ListItem, ListView, Static


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


def _fallback_name(session: dict) -> str:
    ts = float(session.get("created_at", 0) or 0)
    if ts <= 0:
        return "(unnamed)"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


class _SessionRow(ListItem):
    """One row in the sessions list."""

    def __init__(self, session: dict, *, is_current: bool) -> None:
        text = Text()
        indicator = "●" if is_current else "○"
        indicator_style = "#3fb950" if is_current else "#6e7681"
        text.append(f"{indicator} ", style=indicator_style)
        sid = str(session.get("session_id", ""))
        desc = str(session.get("description") or _fallback_name(session))
        if len(desc) > 24:
            desc = desc[:23] + "…"
        msgs = int(session.get("message_count", 0) or 0)
        ago = _time_ago(float(session.get("last_active", 0) or 0))
        text.append(sid, style="bold #58a6ff" if is_current else "bold #c9d1d9")
        text.append(f"\n   {desc}\n   ", style="#8b949e")
        text.append(f"{msgs}m · {ago}", style="dim #6e7681")
        super().__init__(Static(text, markup=False))
        self.session_id = sid
        self.styles.height = 3


class Sidebar(Vertical):
    """Left sidebar with tabbed Sessions / Files panels."""

    DEFAULT_CSS = """
    Sidebar {
        width: 36;
        height: 100%;
        display: none;
        background: $surface;
        border-right: solid $surface-lighten-1;
        padding: 0;
    }
    Sidebar.visible {
        display: block;
    }
    Sidebar .sidebar-tabs {
        height: 1;
        padding: 0 1;
        background: $surface-darken-1;
    }
    Sidebar .tab {
        width: 1fr;
        height: 1;
        content-align: center middle;
        color: $text-muted;
    }
    Sidebar .tab.active {
        color: #e6edf3;
        text-style: bold;
        background: $surface;
    }
    Sidebar .sidebar-body {
        height: 1fr;
        padding: 0;
    }
    Sidebar .panel-empty {
        padding: 1 2;
        color: $text-muted;
    }
    Sidebar DirectoryTree {
        height: 1fr;
        padding: 0 1;
        background: $surface;
    }
    Sidebar ListView {
        height: 1fr;
        background: $surface;
        padding: 0;
    }
    Sidebar ListView > ListItem {
        background: $surface;
        padding: 0 1;
    }
    Sidebar ListView > ListItem.--highlight {
        background: $surface-lighten-1;
    }
    """

    BINDINGS = [
        ("escape", "dismiss", "Dismiss sidebar"),
        ("tab", "cycle_tab", "Switch tab"),
        ("shift+tab", "cycle_tab", "Switch tab"),
        ("1", "show_tab('sessions')", ""),
        ("2", "show_tab('files')", ""),
    ]

    class Dismiss(Message):
        pass

    class SessionSelected(Message):
        def __init__(self, session_id: str) -> None:
            super().__init__()
            self.session_id = session_id

    def __init__(self, working_dir: Path | None = None) -> None:
        super().__init__()
        self._working_dir = working_dir or Path.cwd()
        self._active_tab: str = "sessions"
        self._sessions: list[dict] = []
        self._current_session_id: str = ""

    def compose(self) -> ComposeResult:
        with Horizontal(classes="sidebar-tabs", id="sidebar-tabs-row"):
            yield Static("Sessions", classes="tab active", id="tab-sessions")
            yield Static("Files", classes="tab", id="tab-files")
        with Vertical(classes="sidebar-body", id="sidebar-body"):
            yield ListView(id="sessions-list")
            tree = DirectoryTree(str(self._working_dir), id="dir-tree")
            tree.display = False
            yield tree

    def on_mount(self) -> None:
        self.trap_focus()
        self._render_sessions()

    # ── public API ───────────────────────────────────────────────────

    def toggle(self) -> None:
        if self.has_class("visible"):
            self.remove_class("visible")
        else:
            self.add_class("visible")
            self._focus_active()

    def set_sessions(self, sessions: list[dict], current_session_id: str) -> None:
        """Replace the session list and highlight the active session."""
        # Sort by last_active desc (most recently used first)
        self._sessions = sorted(
            sessions,
            key=lambda s: float(s.get("last_active", 0) or 0),
            reverse=True,
        )
        self._current_session_id = current_session_id or ""
        self._render_sessions()

    # ── internal rendering ───────────────────────────────────────────

    def _render_sessions(self) -> None:
        try:
            listview = self.query_one("#sessions-list", ListView)
        except Exception:
            return
        listview.clear()
        if not self._sessions:
            listview.append(
                ListItem(Static("No sessions yet", classes="panel-empty"))
            )
            return
        for session in self._sessions:
            sid = str(session.get("session_id", ""))
            listview.append(
                _SessionRow(session, is_current=(sid == self._current_session_id))
            )

    def _set_tab(self, name: str) -> None:
        self._active_tab = name
        try:
            sessions_tab = self.query_one("#tab-sessions", Static)
            files_tab = self.query_one("#tab-files", Static)
            sessions_list = self.query_one("#sessions-list", ListView)
            dir_tree = self.query_one("#dir-tree", DirectoryTree)
        except Exception:
            return
        if name == "sessions":
            sessions_tab.add_class("active")
            files_tab.remove_class("active")
            sessions_list.display = True
            dir_tree.display = False
        else:
            sessions_tab.remove_class("active")
            files_tab.add_class("active")
            sessions_list.display = False
            dir_tree.display = True
        self._focus_active()

    def _focus_active(self) -> None:
        try:
            if self._active_tab == "sessions":
                self.query_one("#sessions-list", ListView).focus()
            else:
                self.query_one("#dir-tree", DirectoryTree).focus()
        except Exception:
            pass

    # ── actions ──────────────────────────────────────────────────────

    def action_dismiss(self) -> None:
        self.remove_class("visible")
        self.post_message(self.Dismiss())

    def action_cycle_tab(self) -> None:
        self._set_tab("files" if self._active_tab == "sessions" else "sessions")

    def action_show_tab(self, name: str) -> None:
        self._set_tab(name)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        sid = getattr(item, "session_id", None)
        if sid:
            self.post_message(self.SessionSelected(sid))
