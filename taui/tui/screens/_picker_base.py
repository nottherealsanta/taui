"""Shared base for the fuzzy-search modal pickers.

The model, agent, skill, and prompt pickers were near-identical copies of one
another — same layout, same fuzzy filter, same key handling, and the same block
of hardcoded-gray CSS pasted into each file. They had quietly drifted apart
(different borders, widths, and no shared affordances).

``FuzzyPickerScreen`` is the single source of truth for that pattern:

* one tokenized stylesheet (``$taui-*``) so every picker matches and renders
  correctly in both light and dark themes;
* one fuzzy filter (substring hits first, then subsequence hits);
* a consistent title bar and ``Enter select · Esc cancel`` hint.

A concrete picker only declares *what* it shows (rows, ids, the fields to match
against) — never *how* the modal looks or behaves.
"""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

#: Cap on how many items a picker renders at once — fuzzy search narrows the
#: rest. Shared so every picker behaves identically.
MAX_ITEMS = 50


def subseq_match(query: str, target: str) -> bool:
    """Return True if every char in ``query`` appears in ``target`` in order."""
    i = 0
    for ch in target:
        if i < len(query) and ch == query[i]:
            i += 1
    return i == len(query)


class FuzzyPickerScreen[T](ModalScreen[str | None]):
    """Modal: a search box over a fuzzy-filtered option list.

    Subclasses override the small hooks below; everything visual and
    interactive is handled here.
    """

    #: Dialog width in cells. Subclasses widen this for longer rows.
    DIALOG_WIDTH = 90
    #: Placeholder shown in the empty search box.
    SEARCH_PLACEHOLDER = "Search…"
    #: Title shown above the search box. Subclasses may set an instance
    #: attribute of the same name for a dynamic title.
    TITLE = ""

    DEFAULT_CSS = """
    FuzzyPickerScreen {
        align: center middle;
        background: $taui-scrim;
    }
    FuzzyPickerScreen #picker-dialog {
        width: 90;
        max-width: 95%;
        height: auto;
        max-height: 80%;
        background: $taui-dialog-bg;
        border: none;
        padding: 0;
    }
    FuzzyPickerScreen .picker-title {
        width: 100%;
        padding: 0 1;
        margin: 0 0 1 0;
        color: $text-muted;
        text-style: bold;
    }
    FuzzyPickerScreen #picker-search {
        width: 100%;
        background: $taui-field-bg;
        border: solid $taui-border;
    }
    FuzzyPickerScreen #picker-search:focus {
        border: solid $taui-border-focus;
    }
    FuzzyPickerScreen #picker-options {
        height: 18;
        background: $taui-field-bg;
        border: solid $taui-border;
        color: $text;
    }
    FuzzyPickerScreen #picker-options:focus {
        border: solid $taui-border-focus;
    }
    FuzzyPickerScreen .option-list--option-highlighted {
        background: $taui-option-active;
        color: $foreground;
        text-style: bold;
    }
    FuzzyPickerScreen .picker-hint {
        width: 100%;
        padding: 1 1 0 1;
        color: $text-muted;
    }
    """

    def __init__(self, items: list[T]) -> None:
        super().__init__()
        self._items: list[T] = list(items)[:MAX_ITEMS]

    # ── Hooks for subclasses ────────────────────────────────────────────

    def render_row(self, item: T) -> Text | str:
        """Return the rendered option for ``item``."""
        raise NotImplementedError

    def item_id(self, item: T) -> str:
        """Return the stable id for ``item`` (the dismiss value)."""
        raise NotImplementedError

    def match_text(self, item: T) -> list[str]:
        """Return the strings ``item`` should be fuzzy-matched against."""
        raise NotImplementedError

    # ── Compose / lifecycle ─────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Container(id="picker-dialog"):
            if self.TITLE:
                yield Label(self.TITLE, classes="picker-title")
            yield Input(placeholder=self.SEARCH_PLACEHOLDER, id="picker-search")
            yield OptionList(
                *[Option(self.render_row(it), id=self.item_id(it)) for it in self._items],
                id="picker-options",
            )
            yield Label("Enter select · Esc cancel", classes="picker-hint")

    def on_mount(self) -> None:
        dialog = self.query_one("#picker-dialog", Container)
        dialog.styles.width = self.DIALOG_WIDTH
        self.query_one("#picker-search", Input).focus()

    # ── Filtering ───────────────────────────────────────────────────────

    def _filter(self, query: str) -> list[T]:
        q = query.lower().strip()
        if not q:
            return list(self._items)
        fields = {id(it): [f.lower() for f in self.match_text(it)] for it in self._items}
        substring = [it for it in self._items if any(q in f for f in fields[id(it)])]
        seen = {self.item_id(it) for it in substring}
        subseq = [
            it
            for it in self._items
            if self.item_id(it) not in seen
            and any(subseq_match(q, f) for f in fields[id(it)])
        ]
        return substring + subseq

    @on(Input.Changed, "#picker-search")
    def _on_search_changed(self, event: Input.Changed) -> None:
        try:
            opts = self.query_one("#picker-options", OptionList)
        except Exception:
            return
        opts.clear_options()
        for item in self._filter(event.value):
            opts.add_option(Option(self.render_row(item), id=self.item_id(item)))
        if opts.option_count:
            opts.highlighted = 0

    @on(Input.Submitted, "#picker-search")
    def _on_search_submit(self, _: Input.Submitted) -> None:
        try:
            opts = self.query_one("#picker-options", OptionList)
        except Exception:
            return
        if opts.option_count == 0:
            return
        opt = opts.get_option_at_index(opts.highlighted or 0)
        self.dismiss(opt.id)

    @on(OptionList.OptionSelected)
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option_id) if event.option_id is not None else None)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)
