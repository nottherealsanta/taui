"""
StreamClient — in-process async client for reading from and writing to durable streams.

This is a thin convenience wrapper around ``StreamStore`` used by agent components
(``AgentRunner``, ``AgentManager``, ``PrimeAgent``) to interact with durable streams
without coupling directly to the store's SQL interface.

For agent producers, the client provides:
- ``ensure_stream()`` — create-if-not-exists (idempotent)
- ``append()`` / ``append_auto()`` — write events to a stream
- ``close_stream()`` — signal EOF (agent done)

For consumers (frontend catch-up, ``AgentManager.subscribe``), the client provides:
- ``read()`` — batch read from an offset
- ``tail()`` — async generator that yields chunks as they arrive (live-tail)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

from taui.streams.store import (
    StreamChunk,
    StreamClosedError,
    StreamNotFoundError,
    StreamStore,
)

logger = logging.getLogger(__name__)


class StreamClient:
    """In-process async client for durable streams.

    Usage::

        client = StreamClient(store)
        await client.ensure_stream("agents/abc-123")
        offset = await client.append_auto("agents/abc-123", {"type": "state_change", "state": "running"})
        chunks = await client.read("agents/abc-123", from_offset=0)
        async for chunk in client.tail("agents/abc-123", from_offset=0):
            print(chunk.data)
    """

    def __init__(self, store: StreamStore) -> None:
        self._store = store

    # ── Stream lifecycle ──────────────────────────────────────────────────────

    async def ensure_stream(self, stream_id: str) -> None:
        """Create a stream if it doesn't exist. Idempotent."""
        await self._store.create_stream(stream_id)

    async def close_stream(self, stream_id: str) -> None:
        """Close a stream (signal EOF). No more appends allowed after this."""
        try:
            await self._store.close_stream(stream_id)
        except StreamNotFoundError:
            logger.warning("Attempted to close non-existent stream: %s", stream_id)

    async def stream_exists(self, stream_id: str) -> bool:
        """Check if a stream exists."""
        return await self._store.stream_exists(stream_id)

    async def get_stream_length(self, stream_id: str) -> int:
        """Return the current number of chunks in a stream."""
        return await self._store.get_stream_length(stream_id)

    # ── Producing (writing) ───────────────────────────────────────────────────

    async def append(
        self,
        stream_id: str,
        *,
        offset: int,
        data: bytes,
    ) -> int:
        """Append a chunk at a specific offset. Idempotent for identical data.

        Returns the offset written.
        """
        return await self._store.append(stream_id, offset=offset, data=data)

    async def append_auto(
        self,
        stream_id: str,
        payload: dict[str, Any] | bytes,
    ) -> int:
        """Append a chunk at the next available offset.

        If ``payload`` is a dict, it is serialized to JSON bytes.
        Returns the offset written.
        """
        if isinstance(payload, dict):
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        else:
            data = payload
        return await self._store.append_auto(stream_id, data)

    async def append_event(
        self,
        stream_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> int:
        """Convenience: append an event with a ``type`` field prepended.

        Serializes ``{"type": event_type, **payload}`` as JSON bytes and appends.
        Returns the offset written.
        """
        data = {"type": event_type, **payload}
        return await self.append_auto(stream_id, data)

    # ── Consuming (reading) ───────────────────────────────────────────────────

    async def read(
        self,
        stream_id: str,
        *,
        from_offset: int = 0,
        limit: int = 1000,
    ) -> list[StreamChunk]:
        """Read chunks from a stream starting at ``from_offset``.

        Returns up to ``limit`` chunks.
        """
        return await self._store.read(stream_id, from_offset=from_offset, limit=limit)

    async def read_all(self, stream_id: str) -> list[StreamChunk]:
        """Read all chunks from a stream."""
        return await self._store.read(stream_id, from_offset=0, limit=2**31)

    async def tail(
        self,
        stream_id: str,
        *,
        from_offset: int = 0,
        poll_timeout: float = 30.0,
    ) -> AsyncIterator[StreamChunk]:
        """Async generator that yields chunks as they arrive.

        Starts from ``from_offset`` and yields all existing chunks (catch-up),
        then blocks waiting for new chunks (live-tail). Exits when the stream
        is closed or the caller breaks out of the loop.

        This implements the consumer side of the Durable Streams ``live=long-poll``
        pattern as an async iterator.
        """
        offset = from_offset
        while True:
            # Read any available chunks from current offset
            chunks = await self._store.read(stream_id, from_offset=offset, limit=100)
            if chunks:
                for chunk in chunks:
                    yield chunk
                    offset = chunk.offset + 1

            # Check if stream is closed (EOF)
            try:
                if await self._store.is_closed(stream_id):
                    return
            except StreamNotFoundError:
                return

            # No more data currently — wait for new appends
            if not chunks:
                got_data = await self._store.wait_for_new_data(
                    stream_id, timeout=poll_timeout
                )
                if not got_data:
                    # Timeout — check if stream still exists and loop
                    try:
                        if await self._store.is_closed(stream_id):
                            return
                    except StreamNotFoundError:
                        return
