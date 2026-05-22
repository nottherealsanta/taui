"""Prompt picker modal screen with fuzzy search."""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option


class PromptPickerScreen(ModalScreen[str | None]):
    """Modal for selecting a prompt."""

    DEFAULT_CSS = """
    PromptPickerScreen {
        align: center middle;
        background: $background 70%;
    }
    #prompt-picker-dialog {
        width: 100;
        max-width: 95%;
        height: auto;
        max-height: 80%;
        background: #0d0d0d;
        border: none;
        padding: 0;
    }
    #prompt-picker-dialog #prompt-search {
        width: 100%;
        background: #121212;
        border: solid #2a2a2a;
    }
    #prompt-picker-dialog #prompt-search:focus {
        border: solid #5a5a5a;
    }
    #prompt-picker-dialog OptionList {
        height: 18;
        background: #121212;
        border: solid #2a2a2a;
        color: #c8c8c8;
    }
    #prompt-picker-dialog OptionList:focus {
        border: solid #5a5a5a;
    }
    #prompt-picker-dialog .option-list--option-highlighted {
        background: #2a2a2a;
        color: #e8e8e8;
        text-style: bold;
    }
    """

    def __init__(self, prompts: list) -> None:
        super().__init__()
        self._prompts = prompts[:50]

    def compose(self) -> ComposeResult:
        with Container(id="prompt-picker-dialog"):
            yield Input(placeholder="Search prompts…", id="prompt-search")
            yield OptionList(
                *[
                    Option(_prompt_row(p), id=_get(p, "identifier"))
                    for p in self._prompts
                ],
                id="prompt-options",
            )


    def on_mount(self) -> None:
        self.query_one("#prompt-search", Input).focus()

    def _filter(self, query: str) -> list:
        q = query.lower().strip()
        if not q:
            return list(self._prompts)
        substring = [
            p for p in self._prompts
            if q in _get(p, "label").lower() or q in _get(p, "summary").lower()
        ]
        seen = {_get(p, "identifier") for p in substring}
        subseq = [
            p for p in self._prompts
            if _get(p, "identifier") not in seen
            and (
                _subseq_match(q, _get(p, "label").lower())
                or _subseq_match(q, _get(p, "summary").lower())
            )
        ]
        return substring + subseq

    @on(Input.Changed, "#prompt-search")
    def _on_search_changed(self, event: Input.Changed) -> None:
        try:
            opts = self.query_one("#prompt-options", OptionList)
        except Exception:
            return
        opts.clear_options()
        for p in self._filter(event.value):
            opts.add_option(Option(_prompt_row(p), id=_get(p, "identifier")))
        if opts.option_count:
            opts.highlighted = 0

    @on(Input.Submitted, "#prompt-search")
    def _on_search_submit(self, _: Input.Submitted) -> None:
        try:
            opts = self.query_one("#prompt-options", OptionList)
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
            option_id = _get(self._prompts[event.option_index], "identifier")
        self.dismiss(str(option_id))

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)


def _get(obj: object, attr: str) -> str:
    """Get an attribute from a dataclass instance or dict, returning '' if missing."""
    if isinstance(obj, dict):
        return str(obj.get(attr, ""))
    return str(getattr(obj, attr, ""))


def _subseq_match(query: str, target: str) -> bool:
    """Return True if every char in `query` appears in `target` in order."""
    i = 0
    for ch in target:
        if i < len(query) and ch == query[i]:
            i += 1
    return i == len(query)


_SUMMARY_MAX = 40


def _prompt_row(p: object) -> Text:
    label = _get(p, "label")
    summary = _get(p, "summary")
    scope = _get(p, "scope")
    if len(summary) > _SUMMARY_MAX:
        summary = summary[:_SUMMARY_MAX - 1] + "…"
    text = Text()
    text.append(f"{label:<28s}", style="white")
    text.append(f"  {summary:<{_SUMMARY_MAX}s}", style="dim")
    text.append(f"  {scope}", style="dim")
    return text
