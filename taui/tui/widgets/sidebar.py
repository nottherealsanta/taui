"""Sidebar widget with collapsible project directory tree."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Collapsible, DirectoryTree, Static


class Sidebar(Vertical):
    """Collapsible sidebar with project directory tree."""

    DEFAULT_CSS = """
    Sidebar {
        width: 35;
        height: 100%;
        display: none;
        border-right: solid $accent;
        padding: 0;
    }
    Sidebar.visible {
        display: block;
    }
    Sidebar DirectoryTree {
        height: 1fr;
        padding: 0 1;
    }
    Sidebar .sidebar-header {
        height: 1;
        padding: 0 1;
        color: cyan;
        text-style: bold;
    }
    """

    BINDINGS = [("escape", "dismiss", "Dismiss sidebar")]

    class Dismiss(Message):
        pass

    def __init__(self, working_dir: Path | None = None) -> None:
        super().__init__()
        self._working_dir = working_dir or Path.cwd()

    def compose(self) -> ComposeResult:
        yield Static(f" {self._working_dir.name}/", classes="sidebar-header")
        yield DirectoryTree(str(self._working_dir), id="dir-tree")

    def on_mount(self) -> None:
        self.trap_focus()

    def toggle(self) -> None:
        if self.has_class("visible"):
            self.remove_class("visible")
        else:
            self.add_class("visible")
            try:
                self.query_one("#dir-tree", DirectoryTree).focus()
            except Exception:
                pass

    def action_dismiss(self) -> None:
        self.remove_class("visible")
        self.post_message(self.Dismiss())
