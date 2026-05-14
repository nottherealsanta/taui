"""Output truncation store — holds full tool outputs behind peek handles."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(slots=True)
class TruncatedOutput:
    """Full output stored behind a handle."""

    handle: str
    tool_name: str
    full_content: str
    truncated_preview: str


class TruncationStore:
    """In-memory store for truncated tool outputs within a session."""

    DEFAULT_MAX_INLINE_BYTES = 8 * 1024  # 8 KiB
    DEFAULT_PEEK_WINDOW = 4 * 1024  # 4 KiB per peek

    def __init__(self, max_inline_bytes: int = DEFAULT_MAX_INLINE_BYTES) -> None:
        self._max_inline_bytes = max_inline_bytes
        self._store: dict[str, TruncatedOutput] = {}

    def maybe_truncate(self, content: str, tool_name: str = "") -> str:
        """Truncate content if over the limit. Returns possibly truncated string.

        If truncated, the full content is stored and a peek handle is appended.
        """
        if len(content.encode("utf-8", errors="replace")) <= self._max_inline_bytes:
            return content

        handle = f"tr_{uuid.uuid4().hex[:8]}"
        # Truncate at byte boundary respecting utf-8
        preview_bytes = content.encode("utf-8", errors="replace")[: self._max_inline_bytes]
        preview = preview_bytes.decode("utf-8", errors="replace")

        remaining = len(content.encode("utf-8", errors="replace")) - self._max_inline_bytes
        remaining_kb = remaining / 1024

        truncated_preview = (
            f"{preview}\n\n"
            f"[truncated; {remaining_kb:.0f} KiB more — "
            f'use peek tool with handle="{handle}" offset=0]'
        )

        self._store[handle] = TruncatedOutput(
            handle=handle,
            tool_name=tool_name,
            full_content=content,
            truncated_preview=truncated_preview,
        )

        return truncated_preview

    def peek(self, handle: str, offset: int = 0, limit: int | None = None) -> str | None:
        """Retrieve a window of a truncated output by handle.

        Returns None if handle not found.
        """
        entry = self._store.get(handle)
        if entry is None:
            return None

        window = limit or self.DEFAULT_PEEK_WINDOW
        content = entry.full_content

        # offset is in bytes
        content_bytes = content.encode("utf-8", errors="replace")
        chunk = content_bytes[offset : offset + window]
        text = chunk.decode("utf-8", errors="replace")

        total = len(content_bytes)
        end = offset + window
        remaining = max(0, total - end)

        if remaining > 0:
            text += (
                f"\n\n[{remaining / 1024:.0f} KiB more — "
                f'peek(handle="{handle}", offset={end})]'
            )

        return text

    def clear(self) -> None:
        self._store.clear()

    @property
    def handles(self) -> list[str]:
        return list(self._store.keys())
