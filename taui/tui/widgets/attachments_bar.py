"""Attachments bar — displays pills for pending images, files, and other context."""

from __future__ import annotations

from dataclasses import dataclass

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static


class AttachmentPill(Static):
    """A single removable attachment pill rendered as a number badge.

    Shows ``[ N ]`` by default and swaps the number for an ``x`` on hover
    so the same trailing cell doubles as the remove button. When hover
    isn't reported by the terminal, the user can still click that cell —
    ``on_click`` treats clicks on the trailing cell as the remove action
    regardless of hover state.
    """

    DEFAULT_CSS = """
    AttachmentPill {
        height: 1;
        width: auto;
        padding: 0;
        margin: 0 1 0 0;
        background: $background;
        color: $text;
    }
    """

    class Removed(Message):
        """Posted when the user clicks the X to remove this pill."""

        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    class Opened(Message):
        """Posted when the user clicks the pill body (not the X)."""

        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    def __init__(self, index: int, **kwargs) -> None:
        super().__init__("", markup=True, **kwargs)
        self.pill_index = index
        self._hover = False
        self._refresh_render()

    def _refresh_render(self) -> None:
        glyph = "x" if self._hover else str(self.pill_index + 1)
        self.update(f"[bold white on #4a4a4a] {glyph} [/bold white on #4a4a4a]")

    def on_enter(self, event: events.Enter) -> None:
        self._hover = True
        self._refresh_render()

    def on_leave(self, event: events.Leave) -> None:
        self._hover = False
        self._refresh_render()

    def on_click(self, event: events.Click) -> None:
        # Single-cell glyph: any click on the pill removes it. The hover
        # state only flips the rendered character — clicking always means
        # "remove" since that's the only thing this pill can do without
        # cross-pill positional context.
        self.post_message(self.Removed(self.pill_index))


class AttachmentsBar(Widget):
    """Bar of attachment pills shown above the chat input.

    Hidden when empty. Tracks both image attachments (data: URLs) and file
    attachments (absolute paths) — the `kind` field on each Attachment
    tells the app which underlying buffer to sync with on removal.
    """

    DEFAULT_CSS = """
    AttachmentsBar {
        height: auto;
        max-height: 1;
        padding: 0 2;
        margin: 0;
        display: none;
    }
    AttachmentsBar.has-items {
        display: block;
    }
    AttachmentsBar Horizontal {
        height: 1;
        width: 1fr;
    }
    """

    class Cleared(Message):
        """Posted when an attachment is removed.

        Carries the bar index, attachment `kind`, and the underlying `data`
        of the removed attachment so the app can update the matching backing
        list (images / files) by value, not by index — indices in the bar
        shift after removal, but the underlying value is unique.
        """

        def __init__(
            self, index: int, *, kind: str = "image", data: str = ""
        ) -> None:
            super().__init__()
            self.index = index
            self.kind = kind
            self.data = data

    class PasteOpened(Message):
        """Posted when the user clicks a pasted-text pill to view/edit it."""

        def __init__(self, index: int, data: str) -> None:
            super().__init__()
            self.index = index
            self.data = data

    @dataclass(frozen=True, slots=True)
    class Attachment:
        data: str  # data URL for images, absolute path for files, raw text for pastes
        kind: str = "image"
        name: str = ""  # human-readable name (file/folder basename); empty otherwise

    _items: list[Attachment] = []

    def compose(self) -> ComposeResult:
        yield Horizontal()

    def add(self, data: str, *, kind: str = "image", name: str = "") -> int:
        """Add an attachment. Returns its index."""
        self._items = [
            *self._items,
            self.Attachment(data=data, kind=kind, name=name),
        ]
        self._rebuild()
        return len(self._items) - 1

    def remove(self, index: int) -> Attachment | None:
        """Remove attachment at *index*. Returns the removed item, or None."""
        if 0 <= index < len(self._items):
            item = self._items[index]
            self._items = [a for i, a in enumerate(self._items) if i != index]
            self._rebuild()
            return item
        return None

    def find_index(self, *, kind: str, data: str) -> int:
        """Return the index of the first attachment matching kind+data, or -1."""
        for i, item in enumerate(self._items):
            if item.kind == kind and item.data == data:
                return i
        return -1

    def clear_all(self) -> list[Attachment]:
        """Remove all attachments, return the removed items."""
        removed = list(self._items)
        self._items = []
        self._rebuild()
        return removed

    @property
    def items(self) -> list[Attachment]:
        return list(self._items)

    @property
    def count(self) -> int:
        return len(self._items)

    def update_data(self, index: int, data: str) -> None:
        """Replace the underlying data of the pill at *index*."""
        if 0 <= index < len(self._items):
            old = self._items[index]
            self._items = [
                self.Attachment(data=data, kind=old.kind, name=old.name)
                if i == index
                else item
                for i, item in enumerate(self._items)
            ]

    def _rebuild(self) -> None:
        """Rebuild pills from current items."""
        if self.count > 0:
            self.add_class("has-items")
        else:
            self.remove_class("has-items")
        try:
            container = self.query_one(Horizontal)
            container.remove_children()
            for i, _item in enumerate(self._items):
                container.mount(AttachmentPill(i))
        except Exception:
            pass

    def on_attachment_pill_removed(self, event: AttachmentPill.Removed) -> None:
        """Handle pill X click."""
        event.stop()
        removed = self.remove(event.index)
        if removed is not None:
            self.post_message(
                self.Cleared(event.index, kind=removed.kind, data=removed.data)
            )

    def on_attachment_pill_opened(self, event: AttachmentPill.Opened) -> None:
        """Handle pill body click — opens a modal for pasted-text pills only.

        Other kinds (image / file / folder) have no detail view, so the body
        click is a no-op.
        """
        event.stop()
        if 0 <= event.index < len(self._items):
            item = self._items[event.index]
            if item.kind == "paste":
                self.post_message(self.PasteOpened(event.index, item.data))
