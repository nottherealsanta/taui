"""
taui.streams — Durable Streams implementation for resilient event delivery.

Provides an append-only, offset-addressed stream store backed by SQLite,
an in-process async client for producers and consumers, and a FastAPI router
implementing the Durable Streams HTTP protocol.

Packages:
    store   — StreamStore (SQLite persistence layer)
    client  — StreamClient (in-process async wrapper)
    server  — FastAPI router (HTTP protocol)
"""

from taui.streams.store import (
    StreamChunk,
    StreamClosedError,
    StreamNotFoundError,
    StreamStore,
    OffsetConflictError,
)
from taui.streams.client import StreamClient
from taui.streams.server import create_streams_router

__all__ = [
    "StreamChunk",
    "StreamClient",
    "StreamClosedError",
    "StreamNotFoundError",
    "StreamStore",
    "OffsetConflictError",
    "create_streams_router",
]
