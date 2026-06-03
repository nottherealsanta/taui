"""Left sidebar — file attachment panel."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import DirectoryTree, Static


class FileTreeSelected(Message):
    """Top-level message posted by the files tree when a label is clicked.

    Defined at module scope (not nested) so Textual's name-based handler
    dispatch (`on_file_tree_selected`) works cleanly when the message
    bubbles up to the parent Sidebar.
    """

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path


class _FilesTree(DirectoryTree):
    """Folder/file tree where the chevron toggles and the label selects.

    Why a subclass: the stock DirectoryTree (1) decorates folders/files with
    emoji icons we want to replace with chevrons, and (2) auto-expands a
    folder when its label is clicked. Here, the chevron alone toggles
    open/close; clicking a folder/file name fires FileTreeSelected so the
    parent Sidebar can add it to context.

    We override ``action_select_cursor`` rather than rely on Tree's built-in
    ``NodeSelected`` bubbling because that message is a parametrized
    Generic[EventTreeDataType], which Textual's name-based handler dispatch
    on a non-Tree parent doesn't pick up reliably.
    """

    ICON_NODE = "▶ "
    ICON_NODE_EXPANDED = "▼ "
    ICON_FILE = "  "  # two spaces so file names align under the chevron

    auto_expand = False

    def action_select_cursor(self) -> None:  # type: ignore[override]
        if self.cursor_line < 0:
            return
        try:
            line = self._tree_lines[self.cursor_line]
        except IndexError:
            return
        node = line.path[-1]
        data = node.data
        if data is None:
            return
        self.post_message(FileTreeSelected(Path(str(data.path))))


class Sidebar(Vertical):
    """Left sidebar for browsing files into the prompt context."""

    DEFAULT_CSS = """
    Sidebar {
        width: 36;
        height: 100%;
        display: none;
        background: $surface;
        border-right: solid $taui-border-subtle;
        padding: 0;
    }
    Sidebar.visible {
        display: block;
    }
    Sidebar:focus-within {
        border-right: solid $secondary;
    }
    Sidebar:focus-within .sidebar-title {
        background: $surface-lighten-1;
    }
    Sidebar:focus-within .sidebar-title {
        color: $secondary;
    }
    Sidebar .sidebar-title {
        height: 1;
        padding: 0 1;
        background: $surface-darken-1;
        content-align: center middle;
        color: $foreground;
        text-style: bold;
    }
    Sidebar .sidebar-body {
        height: 1fr;
        padding: 0;
    }
    Sidebar DirectoryTree {
        height: 1fr;
        padding: 0 1;
        background: $surface;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
        scrollbar-color: $scrollbar-color $surface;
        scrollbar-color-hover: $scrollbar-color-hover $surface;
        scrollbar-color-active: $scrollbar-color-active $surface;
        scrollbar-background: $surface;
        scrollbar-background-hover: $surface;
        scrollbar-background-active: $surface;
    }
    Sidebar DirectoryTree:focus > .tree--cursor {
        background: $secondary-darken-1;
        color: $foreground;
    }
    """

    BINDINGS = [
        ("escape", "dismiss", "Dismiss sidebar"),
    ]

    class Dismiss(Message):
        pass

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
        self._active_tab: str = "files"

    def compose(self) -> ComposeResult:
        yield Static("Files", classes="sidebar-title", id="sidebar-title")
        with Vertical(classes="sidebar-body", id="sidebar-body"):
            tree = _FilesTree(str(self._working_dir), id="dir-tree")
            yield tree

    def on_mount(self) -> None:
        self.trap_focus()

    # ── public API ───────────────────────────────────────────────────

    def toggle(self) -> None:
        if self.has_class("visible"):
            self.remove_class("visible")
        else:
            self.add_class("visible")
            self._focus_active()

    def _set_tab(self, name: str) -> None:
        self._active_tab = "files"
        try:
            dir_tree = self.query_one("#dir-tree", DirectoryTree)
        except Exception:
            return
        dir_tree.display = True
        self._focus_active()

    def _focus_active(self) -> None:
        try:
            self.query_one("#dir-tree", DirectoryTree).focus()
        except Exception:
            pass

    # ── actions ──────────────────────────────────────────────────────

    def action_dismiss(self) -> None:
        self.remove_class("visible")
        self.post_message(self.Dismiss())

    def action_cycle_tab(self) -> None:
        self._set_tab("files")

    def action_show_tab(self, name: str) -> None:
        self._set_tab("files")

    def on_file_tree_selected(self, event: FileTreeSelected) -> None:
        """Forward the tree's label-click into the right toggle message."""
        event.stop()
        path = event.path
        if path.is_dir():
            self.post_message(self.FolderToggleRequested(path))
        else:
            self.post_message(self.FileToggleRequested(path))
