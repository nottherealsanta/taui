"""Streaming agent response widget using Textual's MarkdownStream."""

from __future__ import annotations

import logging

from textual.widgets import Markdown

logger = logging.getLogger(__name__)


class AgentResponse(Markdown):
    """A single streamed LLM response rendered as Markdown.

    Text fragments are forwarded to a Textual ``MarkdownStream``, which
    runs a background task that coalesces pending fragments into one
    ``Markdown.append()`` per render cycle. This keeps the UI smooth even
    when the LLM emits faster than the widget can re-parse markdown.
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
        self._finalized = False
        self._stream = None  # Markdown.get_stream — created on mount
        self._pending_pre_mount = ""

    def _ensure_stream(self) -> bool:
        if self._stream is not None:
            return True
        if not self.is_mounted or self._finalized:
            return False
        self._stream = Markdown.get_stream(self)
        return True

    async def on_mount(self) -> None:
        # Start the background updater and flush anything buffered before mount.
        if self._ensure_stream() and self._pending_pre_mount:
            try:
                await self._stream.write(self._pending_pre_mount)
            except Exception:
                logger.debug("MarkdownStream initial write failed", exc_info=True)
            self._pending_pre_mount = ""

    async def append_text(self, fragment: str) -> None:
        """Append a text fragment to the streamed response."""
        if not fragment or self._finalized:
            return
        self._buffer += fragment
        if self._ensure_stream():
            try:
                await self._stream.write(fragment)
            except Exception:
                logger.debug("MarkdownStream write failed", exc_info=True)
        else:
            # Pre-mount buffering — on_mount will drain.
            self._pending_pre_mount += fragment

    async def finalize(self) -> None:
        """Mark the response as complete and stop the background updater.

        ``MarkdownStream.stop()`` drains any pending fragments through
        ``Markdown.append()`` before it returns, so we do *not* call
        ``update()`` afterwards — that would tear down the rendered DOM
        and re-mount every block, causing a visible flicker.
        """
        if self._finalized:
            return
        self._finalized = True
        if self._stream is not None:
            try:
                await self._stream.stop()
            except Exception:
                logger.debug("MarkdownStream stop failed", exc_info=True)
            self._stream = None
            return
        # Stream was never started (widget never mounted, or only pre-mount
        # writes happened). Render the buffer once so the user sees it.
        if self._buffer:
            try:
                await self.update(self._buffer)
            except Exception:
                logger.debug("AgentResponse final update failed", exc_info=True)
