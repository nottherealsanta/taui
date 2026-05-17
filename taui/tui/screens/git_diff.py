"""Git diff modal screen."""

from __future__ import annotations

import difflib

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.events import Key
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Label, Markdown, Static


class _DiffFileHeader(Static):
    """Clickable row header for a file diff."""

    can_focus = True

    def __init__(self, panel: _DiffFilePanel, **kwargs) -> None:
        super().__init__("", markup=True, **kwargs)
        self._panel = panel

    async def on_click(self) -> None:
        await self._panel.toggle()

    async def on_key(self, event: Key) -> None:
        if event.key in ("enter", "space"):
            event.stop()
            await self._panel.toggle()


class _DiffFilePanel(Container):
    """A collapsible file diff panel."""

    def __init__(self, file: dict[str, str], *, index: int) -> None:
        super().__init__(classes="file-panel")
        self._file = file
        self._expanded = False
        self._mounted_diff = False
        self._header = _DiffFileHeader(self, classes="file-row")
        self._body = Container(classes="diff-body")
        self._body.display = False

    def compose(self) -> ComposeResult:
        self._header.update(self._row_markup())
        yield self._header
        yield self._body

    async def toggle(self) -> None:
        self._expanded = not self._expanded
        self._header.update(self._row_markup())
        self._header.set_class(self._expanded, "expanded")
        self._body.display = self._expanded
        if self._expanded and not self._mounted_diff:
            await self._body.mount(self._build_diff_widget())
            self._mounted_diff = True

    def _row_markup(self) -> str:
        path = self._file.get("path", "")
        status = _status_label(self._file.get("status", ""))
        added, removed = _line_delta(
            self._file.get("old_text", ""),
            self._file.get("new_text", ""),
            path=path,
        )
        chevron = "▾" if self._expanded else "▸"
        return (
            f"[#58a6ff]{chevron}[/#58a6ff] "
            f"[bold]{escape(path)}[/bold] "
            f"[dim]{escape(status)}[/dim] "
            f"[#7ee787]+{added}[/#7ee787] [#ff7b72]-{removed}[/#ff7b72]"
        )

    def _build_diff_widget(self) -> Widget:
        old_path = self._file.get("old_path") or self._file.get("path", "")
        new_path = self._file.get("new_path") or self._file.get("path", "")
        old_text = self._file.get("old_text", "")
        new_text = self._file.get("new_text", "")
        try:
            from textual_diff_view import DiffView
        except ImportError:
            diff = _unified_file_diff(old_path, new_path, old_text, new_text)
            return Markdown(f"```diff\n{diff}\n```")

        diff_view = DiffView(old_path, new_path, old_text, new_text)
        diff_view.split = False
        diff_view.annotations = True
        diff_view.wrap = True
        return diff_view


class GitDiffScreen(ModalScreen[None]):
    """Modal diff viewer for git workflow commands."""

    DEFAULT_CSS = """
    GitDiffScreen {
        align: center middle;
    }
    #git-diff-dialog {
        width: 96%;
        height: 92%;
        background: $surface;
        border: thick $surface-lighten-1;
        padding: 1;
    }
    #git-diff-dialog .dialog-title {
        width: 1fr;
        color: cyan;
        text-style: bold;
    }
    #git-diff-dialog .header-row {
        width: 100%;
        height: auto;
        padding: 0 0 1 0;
    }
    #git-diff-dialog .hint {
        color: $text-muted;
        padding: 0 1;
    }
    #close-button {
        width: 10;
        height: 3;
    }
    #git-diff-body {
        height: 1fr;
        scrollbar-size: 1 1;
    }
    #git-diff-dialog .file-panel {
        height: auto;
        margin: 0 0 1 0;
    }
    #git-diff-dialog .file-row {
        color: $text;
        background: $surface-lighten-1;
        padding: 0 1;
        height: 1;
        width: 1fr;
        text-style: bold;
    }
    #git-diff-dialog .file-row:hover {
        background: $surface-lighten-1;
    }
    #git-diff-dialog .file-row:focus {
        background: $secondary 35%;
    }
    #git-diff-dialog .file-row.expanded {
        background: $surface-lighten-1;
    }
    #git-diff-dialog .diff-body {
        height: auto;
        border-left: solid $surface-lighten-1;
        margin: 0 0 0 1;
    }
    #git-diff-dialog Markdown {
        background: $background;
        padding: 1;
    }
    """

    BINDINGS = [
        ("escape", "close", "Close"),
    ]

    def __init__(self, title: str, files: list[dict[str, str]], unified_diff: str) -> None:
        super().__init__()
        self._title = title
        self._files = files
        self._unified_diff = unified_diff

    def compose(self) -> ComposeResult:
        with Container(id="git-diff-dialog"):
            with Horizontal(classes="header-row"):
                yield Label(self._title, classes="dialog-title")
                yield Button("Close", id="close-button", variant="primary")
            with VerticalScroll(id="git-diff-body"):
                yield from self._compose_diff_body()

    def _compose_diff_body(self) -> ComposeResult:
        if not self._files:
            yield Markdown(f"```diff\n{self._unified_diff}\n```")
            return

        for index, file in enumerate(self._files):
            yield _DiffFilePanel(file, index=index)

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)


def _status_label(status: str) -> str:
    status = status.strip()
    if status.startswith("R"):
        return "renamed"
    if status.startswith("A"):
        return "added"
    if status.startswith("D"):
        return "deleted"
    if status.startswith("M"):
        return "modified"
    return status or "changed"


def _line_delta(old_text: str, new_text: str, *, path: str) -> tuple[int, int]:
    added = 0
    removed = 0
    for line in _unified_file_diff(path, path, old_text, new_text).splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def _unified_file_diff(
    old_path: str,
    new_path: str,
    old_text: str,
    new_text: str,
) -> str:
    return "".join(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=old_path,
            tofile=new_path,
        )
    )
