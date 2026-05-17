"""Git diff modal screen."""

from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Markdown, Static


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
        border: thick #586069;
        padding: 1 1;
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
    #git-diff-body {
        height: 1fr;
        scrollbar-size: 1 1;
    }
    #git-diff-dialog .file-title {
        color: $text;
        background: $surface-lighten-1;
        padding: 0 1;
        margin: 1 0 0 0;
        text-style: bold;
    }
    #git-diff-dialog Markdown {
        background: #111827;
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
                yield Label("Esc to close", classes="hint")
                yield Button("Close", id="close-button", variant="primary")
            with VerticalScroll(id="git-diff-body"):
                yield from self._compose_diff_body()

    def _compose_diff_body(self) -> ComposeResult:
        try:
            from textual_diff_view import DiffView
        except ImportError:
            yield Markdown(f"```diff\n{self._unified_diff}\n```")
            return

        if not self._files:
            yield Markdown(f"```diff\n{self._unified_diff}\n```")
            return

        for file in self._files:
            path = file.get("path", "")
            old_path = file.get("old_path", path)
            new_path = file.get("new_path", path)
            yield Static(f"[bold]{escape(path)}[/bold]", classes="file-title", markup=True)
            diff_view = DiffView(
                old_path,
                new_path,
                file.get("old_text", ""),
                file.get("new_text", ""),
            )
            diff_view.split = False
            diff_view.annotations = True
            diff_view.wrap = True
            yield diff_view

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)
