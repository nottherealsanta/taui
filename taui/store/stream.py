"""
StreamClient — async API for producing and consuming events.

Authoritative producers (AgentLoop) call append(EventType, ...) directly.
Most readers use the semantic projection methods — load_conversation,
load_turns, load_tool_history — and never touch EventType or offsets.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from taui.session_replay import ReplayItem, ReplayTranscript, ToolPair, replay_events
from taui.store.events import Event, EventType
from taui.store.store import Store, StreamNotFoundError

logger = logging.getLogger(__name__)


class StreamClient:
    """High-level async client for reading from and writing to streams.

    Usage::

        client = StreamClient(store)
        await client.ensure_stream("agents/abc-123")
        await client.append("agents/abc-123", EventType.STATE_CHANGE, {"state": "running"})

        async for event in client.tail("agents/abc-123"):
            print(event.type, event.data)
    """

    def __init__(self, store: Store) -> None:
        self._store = store

    # ── Stream lifecycle ──────────────────────────────────────────────────

    async def ensure_stream(
        self, stream_id: str, *, parent_id: str | None = None
    ) -> None:
        """Create a stream if it doesn't exist. Idempotent."""
        await self._store.create_stream(stream_id, parent_id=parent_id)

    async def close_stream(self, stream_id: str) -> None:
        """Close a stream (signal EOF)."""
        try:
            await self._store.close_stream(stream_id)
        except StreamNotFoundError:
            logger.warning("Attempted to close non-existent stream: %s", stream_id)

    # ── Writing ───────────────────────────────────────────────────────────

    async def append(
        self,
        stream_id: str,
        event_type: EventType,
        data: dict[str, Any],
    ) -> int:
        """Append an event at the next available offset. Returns the offset written."""
        return await self._store.append(stream_id, event_type, data)

    # ── Reading ───────────────────────────────────────────────────────────

    async def read(
        self,
        stream_id: str,
        *,
        from_offset: int = 0,
        limit: int = 1000,
    ) -> list[Event]:
        """Read events starting at from_offset."""
        return await self._store.read(stream_id, from_offset=from_offset, limit=limit)

    async def read_all(self, stream_id: str) -> list[Event]:
        """Read all events from a stream."""
        return await self._store.read(stream_id, from_offset=0, limit=2**31)

    # ── Stream queries ────────────────────────────────────────────────────

    async def stream_exists(self, stream_id: str) -> bool:
        """Return True if the stream exists."""
        return await self._store.stream_exists(stream_id)

    async def get_length(self, stream_id: str) -> int:
        """Return the number of events in a stream."""
        return await self._store.get_length(stream_id)

    # ── Semantic read projections ─────────────────────────────────────────

    async def load_conversation(self, stream_id: str) -> ReplayTranscript:
        """Return the full conversation as agent messages and display items.

        Callers don't need to know about EventType, offsets, or the raw
        event model — this is the standard way to reconstruct a session.
        """
        events = await self.read_all(stream_id)
        return replay_events(events)

    async def load_turns(self, stream_id: str) -> list[list[ReplayItem]]:
        """Return conversation items grouped by turn (one list per user message)."""
        transcript = await self.load_conversation(stream_id)
        turns: list[list[ReplayItem]] = []
        current: list[ReplayItem] = []
        for item in transcript.items:
            if item.kind == "user" and current:
                turns.append(current)
                current = []
            current.append(item)
        if current:
            turns.append(current)
        return turns

    async def load_tool_history(self, stream_id: str) -> list[ToolPair]:
        """Return all tool calls paired with their results.

        Result is None for any call that has not yet received a result.
        Order matches the order calls were emitted.
        """
        transcript = await self.load_conversation(stream_id)
        results: dict[str, ReplayItem] = {
            item.call_id: item
            for item in transcript.items
            if item.kind == "tool_result"
        }
        return [
            ToolPair(call=item, result=results.get(item.call_id))
            for item in transcript.items
            if item.kind == "tool_call"
        ]

    async def tail(
        self,
        stream_id: str,
        *,
        from_offset: int = 0,
        poll_timeout: float = 30.0,
    ) -> AsyncIterator[Event]:
        """Async generator that yields events as they arrive.

        Catches up from from_offset, then blocks waiting for new events.
        Exits when the stream is closed or deleted.
        """
        offset = from_offset
        while True:
            events = await self._store.read(stream_id, from_offset=offset, limit=100)
            for event in events:
                yield event
                offset = event.offset + 1

            try:
                if await self._store.is_closed(stream_id):
                    return
            except StreamNotFoundError:
                return

            if not events:
                got_data = await self._store.wait_for_new(
                    stream_id, timeout=poll_timeout
                )
                if not got_data:
                    try:
                        if await self._store.is_closed(stream_id):
                            return
                    except StreamNotFoundError:
                        return
