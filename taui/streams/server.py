"""
Durable Streams HTTP router — FastAPI implementation of the Durable Streams Protocol.

Implements the five core operations:

| Operation       | HTTP Method | Path                      |
|-----------------|-------------|---------------------------|
| Create stream   | PUT         | /streams/{stream_id:path} |
| Append chunk    | POST        | /streams/{stream_id:path} |
| Read catch-up   | GET         | /streams/{stream_id:path} |
| Read live (SSE) | GET         | /streams/{stream_id:path}?live=sse |
| Read live (poll)| GET         | /streams/{stream_id:path}?live=long-poll |
| Close stream    | DELETE      | /streams/{stream_id:path} |
| Stream info     | HEAD        | /streams/{stream_id:path} |

The ``stream_id`` is a path-style identifier (e.g. ``agents/abc-123`` or
``prime/tokens``), supporting nested stream namespaces.

Protocol reference:
  https://github.com/durable-streams/durable-streams/blob/main/PROTOCOL.md
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from taui.streams.store import (
    OffsetConflictError,
    StreamClosedError,
    StreamNotFoundError,
    StreamStore,
)

logger = logging.getLogger(__name__)


def create_streams_router(store: StreamStore) -> APIRouter:
    """Create the FastAPI router for durable streams.

    Args:
        store: The StreamStore instance (must already be connected).

    Returns:
        A FastAPI APIRouter to be mounted at ``/streams``.
    """
    router = APIRouter()

    # ── PUT /streams/{stream_id} — Create stream ──────────────────────────

    @router.put("/{stream_id:path}")
    async def create_stream(stream_id: str) -> Response:
        """Create a new stream. Idempotent — returns 200 if already exists."""
        created = await store.create_stream(stream_id)
        if created:
            return Response(status_code=201, content="", media_type="text/plain")
        return Response(status_code=200, content="", media_type="text/plain")

    # ── POST /streams/{stream_id} — Append chunk ─────────────────────────

    @router.post("/{stream_id:path}")
    async def append_chunk(stream_id: str, request: Request) -> Response:
        """Append a chunk to a stream.

        The ``Offset`` header specifies the expected offset. If omitted,
        auto-appends at the next available offset.

        Returns the offset written in the ``Offset`` response header.
        """
        data = await request.body()
        offset_header = request.headers.get("Offset")

        try:
            if offset_header is not None:
                offset = int(offset_header)
                written = await store.append(stream_id, offset=offset, data=data)
            else:
                written = await store.append_auto(stream_id, data)
        except StreamNotFoundError:
            return Response(status_code=404, content="Stream not found")
        except StreamClosedError:
            return Response(status_code=410, content="Stream is closed")
        except OffsetConflictError:
            return Response(
                status_code=409,
                content="Offset conflict — data at this offset differs",
            )

        return Response(
            status_code=200,
            content="",
            media_type="text/plain",
            headers={"Offset": str(written)},
        )

    # ── GET /streams/{stream_id} — Read (catch-up or live) ───────────────

    @router.get("/{stream_id:path}")
    async def read_stream(
        stream_id: str,
        request: Request,
        offset: int = 0,
        limit: int = 1000,
        live: str | None = None,
    ) -> Response:
        """Read chunks from a stream.

        Query params:
            offset: Starting offset (default 0).
            limit: Max chunks to return in catch-up mode (default 1000).
            live: ``"sse"`` for Server-Sent Events, ``"long-poll"`` for long-poll.
                  Omit for a one-shot catch-up read.

        Catch-up mode returns NDJSON (newline-delimited JSON), one line per chunk.
        SSE mode returns ``text/event-stream`` with ``data:`` frames.
        Long-poll mode blocks until new data is available, then returns NDJSON.
        """
        try:
            exists = await store.stream_exists(stream_id)
            if not exists:
                return Response(status_code=404, content="Stream not found")
        except Exception:
            return Response(status_code=404, content="Stream not found")

        if live == "sse":
            return StreamingResponse(
                _sse_generator(store, stream_id, offset, request),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        if live == "long-poll":
            return await _long_poll_read(store, stream_id, offset, limit)

        # Catch-up read
        return await _catchup_read(store, stream_id, offset, limit)

    # ── HEAD /streams/{stream_id} — Stream info ──────────────────────────

    @router.head("/{stream_id:path}")
    async def stream_info(stream_id: str) -> Response:
        """Return stream metadata in headers."""
        info = await store.get_stream_info(stream_id)
        if info is None:
            return Response(status_code=404)
        return Response(
            status_code=200,
            headers={
                "Stream-Length": str(info["length"]),
                "Stream-Closed": "true" if info["closed"] else "false",
            },
        )

    # ── DELETE /streams/{stream_id} — Close stream ───────────────────────

    @router.delete("/{stream_id:path}")
    async def close_stream_endpoint(stream_id: str) -> Response:
        """Close a stream (signal EOF). No more appends allowed."""
        try:
            await store.close_stream(stream_id)
        except StreamNotFoundError:
            return Response(status_code=404, content="Stream not found")
        return Response(status_code=200, content="", media_type="text/plain")

    return router


# ── Read helpers ──────────────────────────────────────────────────────────────


async def _catchup_read(
    store: StreamStore,
    stream_id: str,
    from_offset: int,
    limit: int,
) -> Response:
    """One-shot catch-up read returning NDJSON."""
    chunks = await store.read(stream_id, from_offset=from_offset, limit=limit)
    is_closed = await store.is_closed(stream_id)
    stream_length = await store.get_stream_length(stream_id)

    lines: list[str] = []
    for chunk in chunks:
        # Each line: JSON object with offset and data
        try:
            payload = json.loads(chunk.data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = chunk.data.decode("utf-8", errors="replace")
        lines.append(
            json.dumps({"offset": chunk.offset, "data": payload}, separators=(",", ":"))
        )

    body = "\n".join(lines) + ("\n" if lines else "")
    headers: dict[str, str] = {
        "Stream-Length": str(stream_length),
    }
    if is_closed:
        headers["Stream-Closed"] = "true"

    return Response(
        status_code=200,
        content=body,
        media_type="application/x-ndjson",
        headers=headers,
    )


async def _long_poll_read(
    store: StreamStore,
    stream_id: str,
    from_offset: int,
    limit: int,
    timeout: float = 30.0,
) -> Response:
    """Long-poll: return immediately if data is available, otherwise block until new data."""
    # First, check if there's already data at the requested offset
    chunks = await store.read(stream_id, from_offset=from_offset, limit=limit)
    if chunks:
        return await _catchup_read(store, stream_id, from_offset, limit)

    # Check if stream is closed (no more data will come)
    if await store.is_closed(stream_id):
        return await _catchup_read(store, stream_id, from_offset, limit)

    # Wait for new data
    got_data = await store.wait_for_new_data(stream_id, timeout=timeout)
    if got_data:
        return await _catchup_read(store, stream_id, from_offset, limit)

    # Timeout — return empty response with 304 Not Modified
    return Response(
        status_code=304,
        headers={"Stream-Length": str(await store.get_stream_length(stream_id))},
    )


async def _sse_generator(
    store: StreamStore,
    stream_id: str,
    from_offset: int,
    request: Request,
) -> Any:
    """Async generator for SSE (Server-Sent Events) live-tail.

    Yields ``data:`` frames as new chunks arrive. Sends periodic ``:keepalive``
    comments to prevent connection timeout.
    """
    offset = from_offset
    while True:
        # Check if client disconnected
        if await request.is_disconnected():
            return

        # Read available chunks
        chunks = await store.read(stream_id, from_offset=offset, limit=100)
        for chunk in chunks:
            try:
                payload = json.loads(chunk.data)
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload = chunk.data.decode("utf-8", errors="replace")
            event_data = json.dumps(
                {"offset": chunk.offset, "data": payload},
                separators=(",", ":"),
            )
            yield f"data: {event_data}\n\n"
            offset = chunk.offset + 1

        # Check if stream is closed
        try:
            if await store.is_closed(stream_id):
                yield "event: eof\ndata: {}\n\n"
                return
        except StreamNotFoundError:
            yield 'event: error\ndata: {"error":"stream_not_found"}\n\n'
            return

        # Wait for new data (with keepalive)
        if not chunks:
            got_data = await store.wait_for_new_data(stream_id, timeout=15.0)
            if not got_data:
                # Send keepalive comment
                yield ": keepalive\n\n"
