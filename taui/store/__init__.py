"""
taui.store — append-only event store backed by SQLite.

The Store is the persistence and communication backbone for Taui.
Every event — agent state changes, tool calls, messages, questions,
approvals — is an append-only row in a SQLite database. Streams are
ordered sequences of events that agents and frontends produce and consume.
"""

from taui.store.events import Event, EventType
from taui.store.store import (
    OffsetConflictError,
    Store,
    StreamClosedError,
    StreamNotFoundError,
)
from taui.store.stream import StreamClient

__all__ = [
    "Event",
    "EventType",
    "OffsetConflictError",
    "Store",
    "StreamClient",
    "StreamClosedError",
    "StreamNotFoundError",
]
