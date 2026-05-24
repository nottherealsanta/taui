"""Streaming agent response widget using incremental Markdown.append()."""

from __future__ import annotations

import asyncio
import logging

from textual.widgets import Markdown

logger = logging.getLogger(__name__)


class AgentResponse(Markdown):
    """A single streamed LLM response rendered as Markdown.

    Text fragments are buffered and flushed once per render frame.
    Each flush sends only the **new** text to ``Markdown.append()``,
    which re-parses from the last stable block boundary and mounts
    only genuinely new widgets — no full DOM teardown.

    An internal ``asyncio.Lock`` serialises ``append()`` calls so that
    ``_last_parsed_line`` stays consistent even when flushes arrive
    faster than the DOM work completes.
    """

    DEFAULT_CSS = """
    AgentResponse {
        margin: 0 1;
        padding: 0;
    }
    """

    def __init__(self) -> None:
        super().__init__("")
        self._buffer = ""
        self._flushed_len = 0
        self._finalized = False
        self._render_pending = False
        self._append_lock = asyncio.Lock()

    async def append_text(self, fragment: str) -> None:
        """Append a text fragment and schedule a throttled re-render."""
        self._buffer += fragment
        if not self._render_pending:
            self._render_pending = True
            self.call_after_refresh(self._flush_buffer)

    def _flush_buffer(self) -> None:
        """Render new content accumulated since the last flush."""
        self._render_pending = False
        buf_len = len(self._buffer)
        if buf_len > self._flushed_len:
            delta = self._buffer[self._flushed_len:]
            self._flushed_len = buf_len
            asyncio.ensure_future(self._safe_append(delta))

    async def _safe_append(self, delta: str) -> None:
        """Serialise ``Markdown.append()`` calls and swallow errors."""
        try:
            async with self._append_lock:
                await self.append(delta)
        except Exception:
            logger.debug("AgentResponse append failed, falling back to full update")
            try:
                async with self._append_lock:
                    await self.update(self._buffer)
            except Exception:
                logger.debug("AgentResponse fallback update also failed", exc_info=True)

    async def finalize(self) -> None:
        """Mark the response as complete."""
        if self._finalized:
            return
        self._finalized = True
        self._render_pending = False
        if self._buffer:
            async with self._append_lock:
                await self.update(self._buffer)
