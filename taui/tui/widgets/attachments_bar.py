"""Attachments bar — displays pills for pending images, files, and other context."""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static


class AttachmentPill(Static):
    """A single removable attachment pill."""

    DEFAULT_CSS = """
    AttachmentPill {
        height: 1;
        width: auto;
        min-width: 12;
        padding: 0;
        margin: 0 1 0 0;
        background: $background;
        color: $text;
    }
    AttachmentPill:hover {
        background: $background-lighten-1;
    }
    """

    class Removed(Message):
        """Posted when the user clicks the X to remove this pill."""

        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    def __init__(self, label: str, index: int, **kwargs) -> None:
        x_btn = "[bold white on #4a4a4a] x [/bold white on #4a4a4a]"
        super().__init__(f" {label} {x_btn}", markup=True, **kwargs)
        self.pill_index = index

    def on_click(self) -> None:
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

    @dataclass(frozen=True, slots=True)
    class Attachment:
        label: str
        data: str  # data URL for images, absolute path for files
        kind: str = "image"

    _items: list[Attachment] = []

    def compose(self) -> ComposeResult:
        yield Horizontal()

    def add(self, label: str, data: str, *, kind: str = "image") -> int:
        """Add an attachment. Returns its index."""
        self._items = [
            *self._items,
            self.Attachment(label=label, data=data, kind=kind),
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

    def _pill_label(self, item: Attachment) -> str:
        if item.kind == "file":
            return f"📄 {item.label}"
        if item.kind == "folder":
            return f"📁 {item.label}/"
        return item.label

    def _rebuild(self) -> None:
        """Rebuild pills from current items."""
        if self.count > 0:
            self.add_class("has-items")
        else:
            self.remove_class("has-items")
        try:
            container = self.query_one(Horizontal)
            container.remove_children()
            for i, item in enumerate(self._items):
                container.mount(AttachmentPill(self._pill_label(item), i))
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
