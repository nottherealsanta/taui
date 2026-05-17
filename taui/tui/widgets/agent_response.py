"""Streaming agent response widget using incremental Markdown updates."""

from __future__ import annotations

from textual.widgets import Markdown


class AgentResponse(Markdown):
    """A single streamed LLM response rendered as Markdown.

    Text fragments are buffered and rendered at most once per Textual
    render frame (~16 ms at 60 fps) to avoid flooding the event loop
    with full Markdown re-parses on every token.
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
        self._render_pending = False

    async def append_text(self, fragment: str) -> None:
        """Append a text fragment and schedule a throttled re-render."""
        self._buffer += fragment
        if not self._render_pending:
            self._render_pending = True
            self.call_after_refresh(self._flush_buffer)

    def _flush_buffer(self) -> None:
        """Render the accumulated buffer (called once per frame)."""
        self._render_pending = False
        if self._buffer:
            self.update(self._buffer)

    async def finalize(self) -> None:
        """Mark the response as complete."""
        if self._finalized:
            return
        self._finalized = True
        self._render_pending = False
        # Final render to ensure completeness
        if self._buffer:
            await self.update(self._buffer)
