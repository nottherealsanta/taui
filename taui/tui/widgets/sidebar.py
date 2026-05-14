"""Sidebar widget with collapsible project directory tree."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import DirectoryTree, Static


class TaskPanel(Vertical):
    """Collapsible task list panel in the sidebar."""

    DEFAULT_CSS = """
    TaskPanel {
        height: auto;
        max-height: 15;
        padding: 0 1;
        border-top: solid $surface-lighten-1;
    }
    TaskPanel .task-header {
        height: 1;
        text-style: bold;
    }
    TaskPanel .task-item {
        height: 1;
        padding-left: 2;
    }
    TaskPanel .task-done {
        color: $text-muted;
        text-style: strike;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._tasks: list[dict[str, str]] = []

    def compose(self) -> ComposeResult:
        yield Static("Tasks", classes="task-header")

    def update_tasks(self, tasks: list[dict[str, str]]) -> None:
        """Update the task list display.

        Each task is ``{"content": "...", "status": "pending|in_progress|completed"}``.
        """
        self._tasks = tasks
        for child in self.query(".task-item"):
            child.remove()
        for child in self.query(".task-done"):
            child.remove()
        for task in tasks:
            status = task.get("status", "pending")
            content = task.get("content", "")
            if status in ("completed", "done"):
                icon = "✓"
                cls = "task-done"
            elif status == "in_progress":
                icon = "►"
                cls = "task-item"
            else:
                icon = "○"
                cls = "task-item"
            label = f"{icon} {content[:30]}"
            self.mount(Static(label, classes=cls))

    @property
    def has_tasks(self) -> bool:
        return bool(self._tasks)


class Sidebar(Vertical):
    """Collapsible sidebar with project directory tree."""

    DEFAULT_CSS = """
    Sidebar {
        width: 35;
        height: 100%;
        display: none;
        border-right: solid $surface-lighten-1;
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
        color: $text;
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
        yield TaskPanel(id="task-panel")

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

