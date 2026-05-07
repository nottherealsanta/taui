"""Completion dropdown overlay for slash command autocomplete."""

from __future__ import annotations

from typing import TypeAlias

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


Completion: TypeAlias = tuple[str, str, bool]


class CompletionItem(Static):
    """A single completion item in the dropdown."""

    DEFAULT_CSS = """
    CompletionItem {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    CompletionItem.highlighted {
        background: $surface-lighten-1;
        color: $text;
    }
    """


class CompletionDropdown(Widget):
    """Floating dropdown showing slash command completions."""

    DEFAULT_CSS = """
    CompletionDropdown {
        layer: overlay;
        dock: bottom;
        width: 60;
        max-height: 10;
        height: auto;
        background: $surface-darken-1;
        border: tall $surface-lighten-1;
        padding: 0;
        margin: 0 2;
        display: none;
    }
    CompletionDropdown.visible {
        display: block;
    }
    """

    selected_index: reactive[int] = reactive(0)

    class Selected(Message):
        """Posted when user selects a completion."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._items: list[Completion] = []  # (name, description, accepts_args)
        self._prefix: str = "/"

    def compose(self) -> ComposeResult:
        yield Vertical(id="completion-items")

    def set_items(self, items: list[Completion]) -> None:
        """Update dropdown items: list of (name, description, accepts_args)."""
        self._items = items
        self.selected_index = 0
        self._rebuild()

    def _rebuild(self) -> None:
        """Rebuild the item widgets."""
        container = self.query_one("#completion-items", Vertical)
        container.remove_children()
        for i, (name, desc, _accepts_args) in enumerate(self._items):
            label = f"{self._prefix}{name:<14s} {desc}"
            item = CompletionItem(label)
            if i == self.selected_index:
                item.add_class("highlighted")
            container.mount(item)

    def show(self, items: list[Completion], offset_y: int = -7, prefix: str = "/") -> None:
        """Show dropdown with given items positioned above the chat input."""
        if not items:
            self.hide()
            return
        self._prefix = prefix
        self.set_items(items)
        self.styles.offset = (0, offset_y)
        self.add_class("visible")

    def hide(self) -> None:
        """Hide the dropdown."""
        self.remove_class("visible")
        self._items = []

    @property
    def is_visible(self) -> bool:
        return self.has_class("visible")

    @property
    def current_value(self) -> str | None:
        if self._items and 0 <= self.selected_index < len(self._items):
            return self._items[self.selected_index][0]
        return None

    @property
    def current_accepts_args(self) -> bool:
        if self._items and 0 <= self.selected_index < len(self._items):
            return self._items[self.selected_index][2]
        return True

    def move_up(self) -> None:
        if self._items:
            self.selected_index = (self.selected_index - 1) % len(self._items)
            self._update_highlight()

    def move_down(self) -> None:
        if self._items:
            self.selected_index = (self.selected_index + 1) % len(self._items)
            self._update_highlight()

    def _update_highlight(self) -> None:
        items = self.query(CompletionItem)
        for i, item in enumerate(items):
            if i == self.selected_index:
                item.add_class("highlighted")
            else:
                item.remove_class("highlighted")
