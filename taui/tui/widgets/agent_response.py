"""Streaming agent response widget using incremental Markdown updates."""

from __future__ import annotations

from textual.widgets import Markdown


class AgentResponse(Markdown):
    """A single streamed LLM response rendered as Markdown."""

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

    async def append_text(self, fragment: str) -> None:
        """Append a text fragment and re-render."""
        self._buffer += fragment
        await self.update(self._buffer)

    async def finalize(self) -> None:
        """Mark the response as complete."""
        if self._finalized:
            return
        self._finalized = True
        # Final render to ensure completeness
        if self._buffer:
            await self.update(self._buffer)
