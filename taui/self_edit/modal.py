"""Modal editors used by self-edit mode."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, TextArea

from taui.config import Config


class FileEditModal(ModalScreen[bool]):
    """Generic file editor modal."""

    CSS = """
    FileEditModal {
        align: center middle;
    }
    FileEditModal > Vertical {
        width: 92%;
        height: 88%;
        background: $surface;
        border: solid #586069;
        padding: 1 2;
    }
    #file-edit-title {
        height: 1;
        color: $text;
    }
    #file-edit-text {
        height: 1fr;
        border: solid $surface-lighten-1;
    }
    .file-edit-actions {
        height: 3;
        align-horizontal: right;
    }
    """

    def __init__(
        self,
        path: Path,
        *,
        language: str | None = None,
        read_only: bool = False,
    ) -> None:
        super().__init__()
        self._path = path
        self._language = language
        self._read_only = read_only
        self._original = ""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(str(self._path), id="file-edit-title")
            yield TextArea(
                self._original,
                id="file-edit-text",
                language=self._language,
                read_only=self._read_only,
            )
            with Horizontal(classes="file-edit-actions"):
                yield Button("Cancel", id="file-edit-cancel")
                if not self._read_only:
                    yield Button("Save", id="file-edit-save", variant="primary")

    def on_mount(self) -> None:
        try:
            self._original = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            self._original = f"# Error reading file\n{exc}\n"
        self.query_one("#file-edit-text", TextArea).text = self._original
        self.query_one("#file-edit-text", TextArea).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "file-edit-cancel":
            self.dismiss(False)
            return
        if event.button.id == "file-edit-save" and not self._read_only:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                self.query_one("#file-edit-text", TextArea).text,
                encoding="utf-8",
            )
            self.dismiss(True)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.prevent_default()
            self.dismiss(False)
        elif event.key == "ctrl+s" and not self._read_only:
            event.prevent_default()
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                self.query_one("#file-edit-text", TextArea).text,
                encoding="utf-8",
            )
            self.dismiss(True)


class ConfigEditModal(ModalScreen[Config | None]):
    """Small structured editor for runtime config."""

    CSS = """
    ConfigEditModal {
        align: center middle;
    }
    ConfigEditModal > Vertical {
        width: 86%;
        height: 76%;
        background: $surface;
        border: solid #586069;
        padding: 1 2;
    }
    .cfg-row {
        height: 3;
    }
    .cfg-label {
        width: 14;
    }
    #cfg-system-prompt {
        height: 1fr;
        border: solid $surface-lighten-1;
    }
    .cfg-actions {
        height: 3;
        align-horizontal: right;
    }
    """

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("config", id="cfg-title")
            with Horizontal(classes="cfg-row"):
                yield Label("provider", classes="cfg-label")
                yield Input(self._config.provider, id="cfg-provider-input")
            with Horizontal(classes="cfg-row"):
                yield Label("model", classes="cfg-label")
                yield Input(self._config.model, id="cfg-model-input")
            with Horizontal(classes="cfg-row"):
                yield Label("max_turns", classes="cfg-label")
                yield Input(str(self._config.max_turns), id="cfg-max-turns-input")
            yield Label("system_prompt")
            yield TextArea(self._config.system_prompt, id="cfg-system-prompt")
            with Horizontal(classes="cfg-actions"):
                yield Button("Cancel", id="cfg-cancel")
                yield Button("Save", id="cfg-save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cfg-cancel":
            self.dismiss(None)
            return
        if event.button.id == "cfg-save":
            try:
                max_turns = int(self.query_one("#cfg-max-turns-input", Input).value)
            except ValueError:
                self.notify("max_turns must be an integer", severity="error")
                return
            self._config.provider = self.query_one("#cfg-provider-input", Input).value
            self._config.model = self.query_one("#cfg-model-input", Input).value
            self._config.max_turns = max_turns
            self._config.system_prompt = self.query_one("#cfg-system-prompt", TextArea).text
            self.dismiss(self._config)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.prevent_default()
            self.dismiss(None)
