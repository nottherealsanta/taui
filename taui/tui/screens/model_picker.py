"""Model picker modal screen."""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option


class ModelPickerScreen(ModalScreen[str | None]):
    """Modal for selecting a model in the current provider."""

    DEFAULT_CSS = """
    ModelPickerScreen {
        align: center middle;
        background: $background 70%;
    }
    #model-picker-dialog {
        width: 90;
        max-width: 95%;
        height: auto;
        max-height: 80%;
        background: #0d0d0d;
        border: round #2a2a2a;
        padding: 1 2;
    }
    #model-picker-dialog .dialog-title {
        width: 100%;
        content-align: center middle;
        padding: 0 0 1 0;
        color: #c8c8c8;
        text-style: bold;
    }
    #model-picker-dialog OptionList {
        height: auto;
        max-height: 18;
        background: #121212;
        border: solid #2a2a2a;
        color: #c8c8c8;
    }
    #model-picker-dialog OptionList:focus {
        border: solid #5a5a5a;
    }
    #model-picker-dialog .option-list--option-highlighted {
        background: #2a2a2a;
        color: #e8e8e8;
        text-style: bold;
    }
    #model-picker-dialog .hint {
        padding: 1 0 0 0;
        color: #707070;
    }
    """

    def __init__(self, provider: str, models: list[dict], *, current: str) -> None:
        super().__init__()
        self._provider = provider
        self._models = models[:50]
        self._current = current

    def compose(self) -> ComposeResult:
        with Container(id="model-picker-dialog"):
            yield Label(
                f"[bold]{self._provider}/{self._current}[/bold]",
                classes="dialog-title",
            )
            yield OptionList(
                *[
                    Option(_model_prompt(model, current=self._current), id=str(model["id"]))
                    for model in self._models
                ],
                id="model-options",
            )
            yield Label("Enter to select, Esc to cancel", classes="hint")

    def on_mount(self) -> None:
        self.query_one("#model-options", OptionList).focus()

    @on(OptionList.OptionSelected)
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if option_id is None:
            option_id = str(self._models[event.option_index]["id"])
        self.dismiss(str(option_id))

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)


def _model_prompt(model: dict, *, current: str) -> Text:
    model_id = str(model.get("id", ""))
    context = int(model.get("context", 0) or 0)
    ctx = f"{context // 1000}k" if context else "?"
    reasoning = " reasoning" if model.get("reasoning") else ""
    marker = " ◀" if model_id == current else ""

    text = Text()
    text.append(f"{model_id:<45s}", style="bold" if marker else "default")
    text.append(f"  {ctx:>6s} ctx{reasoning}{marker}", style="dim")
    return text
