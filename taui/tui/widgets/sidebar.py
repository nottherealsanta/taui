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
from textual.widgets._directory_tree import DirEntry
from textual.widgets._tree import TreeNode


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


def _build_session_row_text(session: dict, *, is_current: bool) -> Text:
    """Render a session row's two-line label.

    Line 1: ● / ○ indicator + the session description (the "name").
    Line 2: the session id (dim gray) followed by msg count and time-ago.
    """
    text = Text()
    indicator = "●" if is_current else "○"
    indicator_style = "#3fb950" if is_current else "#6e7681"
    text.append(f"{indicator} ", style=indicator_style)
    sid = str(session.get("session_id", ""))
    desc = str(session.get("description") or _fallback_name(session))
    if len(desc) > 26:
        desc = desc[:25] + "…"
    msgs = int(session.get("message_count", 0) or 0)
    ago = _time_ago(float(session.get("last_active", 0) or 0))
    name_style = "bold #e6edf3" if is_current else "#c9d1d9"
    text.append(desc, style=name_style)
    text.append("\n   ")
    text.append(sid, style="#6e7681")
    text.append(f"   {msgs}m · {ago}", style="dim #6e7681")
    return text


class _FilesTree(DirectoryTree):
    """Folder/file tree where the chevron toggles and the label selects.

    Why a subclass: the stock DirectoryTree (1) decorates folders/files with
    emoji icons we want to replace with chevrons, and (2) auto-expands a
    folder when its label is clicked. Here, the chevron alone toggles
    open/close; clicking a folder/file name posts NodeSelected (with
    auto-expand off), which the sidebar then turns into an "add to context"
    message.
    """

    ICON_NODE = "▶ "
    ICON_NODE_EXPANDED = "▼ "
    ICON_FILE = "  "  # two spaces so file names align under the chevron

    auto_expand = False


class _TabLabel(Static):
    """Clickable tab header — clicking it switches its sidebar to that tab."""

    def __init__(self, label: str, *, tab: str, **kwargs) -> None:
        super().__init__(label, **kwargs)
        self.tab_name = tab

    def on_click(self) -> None:
        # Walk up to the owning Sidebar (defined below in this module).
        parent = self.parent
        while parent is not None and not isinstance(parent, Sidebar):
            parent = parent.parent
        if parent is not None:
            parent.action_show_tab(self.tab_name)


class _SessionRow(ListItem):
    """One row in the sessions list — see _build_session_row_text for layout."""

    def __init__(self, session: dict, *, is_current: bool) -> None:
        self.label_text = _build_session_row_text(session, is_current=is_current)
        super().__init__(Static(self.label_text, markup=False))
        self.session_id = str(session.get("session_id", ""))
        self.styles.height = 2


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
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
        scrollbar-color: #30363d $surface;
        scrollbar-color-hover: #484f58 $surface;
        scrollbar-color-active: #6e7681 $surface;
        scrollbar-background: $surface;
        scrollbar-background-hover: $surface;
        scrollbar-background-active: $surface;
    }
    Sidebar ListView {
        height: 1fr;
        background: $surface;
        padding: 0;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
        scrollbar-color: #30363d $surface;
        scrollbar-color-hover: #484f58 $surface;
        scrollbar-color-active: #6e7681 $surface;
        scrollbar-background: $surface;
        scrollbar-background-hover: $surface;
        scrollbar-background-active: $surface;
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

    class FileToggleRequested(Message):
        """Posted when the user picks a file in the directory tree.

        Listeners should toggle the file's presence in the attachments
        bar — clicking a fresh file adds it, clicking an already-attached
        file removes it.
        """

        def __init__(self, path: Path) -> None:
            super().__init__()
            self.path = path

    class FolderToggleRequested(Message):
        """Posted when the user picks a folder label (not its chevron).

        Toggle semantics mirror FileToggleRequested — second click on the
        same folder removes it from context.
        """

        def __init__(self, path: Path) -> None:
            super().__init__()
            self.path = path

    def __init__(self, working_dir: Path | None = None) -> None:
        super().__init__()
        self._working_dir = working_dir or Path.cwd()
        self._active_tab: str = "sessions"
        self._sessions: list[dict] = []
        self._current_session_id: str = ""

    def compose(self) -> ComposeResult:
        with Horizontal(classes="sidebar-tabs", id="sidebar-tabs-row"):
            yield _TabLabel(
                "Sessions",
                tab="sessions",
                classes="tab active",
                id="tab-sessions",
            )
            yield _TabLabel(
                "Files",
                tab="files",
                classes="tab",
                id="tab-files",
            )
        with Vertical(classes="sidebar-body", id="sidebar-body"):
            yield ListView(id="sessions-list")
            tree = _FilesTree(str(self._working_dir), id="dir-tree")
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

    def on_tree_node_selected(
        self, event: DirectoryTree.NodeSelected
    ) -> None:
        """Forward tree picks up to the app as toggle requests.

        Files emit FileToggleRequested; folders emit FolderToggleRequested.
        The chevron click toggles open/close inside the tree directly — it
        doesn't reach this handler — so a NodeSelected here always means
        the user clicked the *label*.
        """
        event.stop()
        node: TreeNode[DirEntry] = event.node
        data = node.data
        if data is None:
            return
        path = Path(str(data.path))
        if path.is_dir():
            self.post_message(self.FolderToggleRequested(path))
        else:
            self.post_message(self.FileToggleRequested(path))
