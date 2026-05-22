"""Model picker modal screen with fuzzy search."""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList
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
        border: none;
        padding: 0;
    }
    #model-picker-dialog #model-search {
        width: 100%;
        background: #121212;
        border: solid #2a2a2a;
    }
    #model-picker-dialog #model-search:focus {
        border: solid #5a5a5a;
    }
    #model-picker-dialog OptionList {
        height: 18;
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
    """

    def __init__(self, provider: str, models: list[dict], *, current: str) -> None:
        super().__init__()
        self._provider = provider
        self._models = models[:50]
        self._current = current

    def compose(self) -> ComposeResult:
        with Container(id="model-picker-dialog"):
            yield Input(placeholder="Search models…", id="model-search")
            yield OptionList(
                *[
                    Option(_model_prompt(model, current=self._current), id=str(model["id"]))
                    for model in self._models
                ],
                id="model-options",
            )


    def on_mount(self) -> None:
        self.query_one("#model-search", Input).focus()

    def _filter(self, query: str) -> list[dict]:
        q = query.lower().strip()
        if not q:
            return list(self._models)
        substring = [m for m in self._models if q in str(m["id"]).lower()]
        seen_ids = {str(m["id"]) for m in substring}
        subseq = [
            m for m in self._models
            if str(m["id"]) not in seen_ids and _subseq_match(q, str(m["id"]).lower())
        ]
        return substring + subseq

    @on(Input.Changed, "#model-search")
    def _on_search_changed(self, event: Input.Changed) -> None:
        try:
            opts = self.query_one("#model-options", OptionList)
        except Exception:
            return
        opts.clear_options()
        for model in self._filter(event.value):
            mid = str(model["id"])
            opts.add_option(Option(_model_prompt(model, current=self._current), id=mid))
        if opts.option_count:
            opts.highlighted = 0

    @on(Input.Submitted, "#model-search")
    def _on_search_submit(self, _: Input.Submitted) -> None:
        try:
            opts = self.query_one("#model-options", OptionList)
        except Exception:
            return
        if opts.option_count == 0:
            return
        idx = opts.highlighted or 0
        opt = opts.get_option_at_index(idx)
        self.dismiss(opt.id)

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


def _subseq_match(query: str, target: str) -> bool:
    """Return True if every char in `query` appears in `target` in order."""
    i = 0
    for ch in target:
        if i < len(query) and ch == query[i]:
            i += 1
    return i == len(query)


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
