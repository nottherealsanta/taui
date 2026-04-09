"""
StreamStore — SQLite-backed append-only stream event store.

Implements the storage layer for the Durable Streams protocol.
Each stream is an ordered, append-only log of byte chunks addressed by offset.

Storage uses the existing aiosqlite dependency with WAL journaling, matching
the pattern established by ``AgentHistoryDB``.

Default path: <workspace>/.taui/streams.db
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

try:
    import aiosqlite as _aiosqlite
except ModuleNotFoundError:  # pragma: no cover
    _aiosqlite = None

logger = logging.getLogger(__name__)


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """\
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS streams (
    stream_id   TEXT PRIMARY KEY,
    created_at  REAL NOT NULL,
    closed      INTEGER NOT NULL DEFAULT 0,
    closed_at   REAL
);

CREATE TABLE IF NOT EXISTS stream_chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_id   TEXT NOT NULL REFERENCES streams(stream_id) ON DELETE CASCADE,
    offset      INTEGER NOT NULL,
    data        BLOB NOT NULL,
    created_at  REAL NOT NULL,
    UNIQUE(stream_id, offset)
);

CREATE INDEX IF NOT EXISTS idx_stream_chunks_stream
    ON stream_chunks(stream_id, offset);
"""


# ── Data types ────────────────────────────────────────────────────────────────


class StreamNotFoundError(Exception):
    """Raised when a stream does not exist."""

    def __init__(self, stream_id: str) -> None:
        super().__init__(f"Stream not found: {stream_id!r}")
        self.stream_id = stream_id


class StreamClosedError(Exception):
    """Raised when attempting to append to a closed stream."""

    def __init__(self, stream_id: str) -> None:
        super().__init__(f"Stream is closed: {stream_id!r}")
        self.stream_id = stream_id


class OffsetConflictError(Exception):
    """Raised when an append offset conflicts with an existing chunk."""

    def __init__(self, stream_id: str, offset: int) -> None:
        super().__init__(
            f"Offset conflict in stream {stream_id!r}: offset {offset} already exists"
        )
        self.stream_id = stream_id
        self.offset = offset


class StreamChunk:
    """A single chunk read from a stream."""

    __slots__ = ("stream_id", "offset", "data", "created_at")

    def __init__(
        self,
        stream_id: str,
        offset: int,
        data: bytes,
        created_at: float,
    ) -> None:
        self.stream_id = stream_id
        self.offset = offset
        self.data = data
        self.created_at = created_at


# ── Fallback sync wrappers (mirrors AgentHistoryDB pattern) ───────────────────


class _FallbackCursor:
    """Sync cursor wrapped to look async."""

    def __init__(
        self, rows: list[sqlite3.Row] | None = None, lastrowid: int | None = None
    ) -> None:
        self._rows = rows or []
        self.lastrowid = lastrowid

    async def fetchone(self) -> dict[str, Any] | None:
        if not self._rows:
            return None
        row = self._rows[0]
        return {k: row[k] for k in row.keys()}

    async def fetchall(self) -> list[dict[str, Any]]:
        return [{k: row[k] for k in row.keys()} for row in self._rows]


class _FallbackConnection:
    """Synchronous sqlite3 wrapped to look async (for environments without aiosqlite)."""

    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._lock = asyncio.Lock()

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _FallbackCursor:
        async with self._lock:
            cur = self._conn.execute(sql, params)
            first = sql.lstrip().upper()
            if first.startswith(("SELECT", "WITH", "PRAGMA")):
                rows = cur.fetchall()
            else:
                rows = None
            return _FallbackCursor(rows=rows, lastrowid=cur.lastrowid)

    async def executescript(self, script: str) -> None:
        async with self._lock:
            self._conn.executescript(script)

    async def commit(self) -> None:
        async with self._lock:
            self._conn.commit()

    async def close(self) -> None:
        async with self._lock:
            self._conn.close()


# ── StreamStore ───────────────────────────────────────────────────────────────


class StreamStore:
    """SQLite-backed append-only stream store.

    Each stream is an ordered sequence of byte chunks. Chunks are addressed
    by a monotonically increasing integer offset (0-indexed). Offsets are
    gap-free within a stream.

    Usage::

        store = StreamStore(workspace)
        await store.connect()
        await store.create_stream("agents/abc-123")
        await store.append("agents/abc-123", offset=0, data=b'{"type":"state_change",...}')
        chunks = await store.read("agents/abc-123", from_offset=0, limit=100)
        await store.close()
    """

    def __init__(self, workspace: Path, *, db_path: Path | None = None) -> None:
        self.workspace = workspace
        self.db_path = db_path or (workspace / ".taui" / "streams.db")
        self._conn: Any | None = None
        self._conn_lock = asyncio.Lock()
        # Waiters for live-tail: stream_id → list of asyncio.Event
        self._waiters: dict[str, list[asyncio.Event]] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        async with self._conn_lock:
            if self._conn is not None:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            if _aiosqlite is not None:
                conn = await _aiosqlite.connect(self.db_path.as_posix())
                conn.row_factory = _aiosqlite.Row
                self._conn = conn
            else:
                self._conn = _FallbackConnection(self.db_path.as_posix())
            await self._conn.executescript(_SCHEMA)
            await self._conn.commit()

    async def close(self) -> None:
        async with self._conn_lock:
            if self._conn is None:
                return
            await self._conn.commit()
            await self._conn.close()
            self._conn = None
            # Wake all waiters so they can exit
            for waiters in self._waiters.values():
                for w in waiters:
                    w.set()
            self._waiters.clear()

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        assert self._conn is not None, "StreamStore not connected"
        return await self._conn.execute(sql, params)

    async def _one(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> dict[str, Any] | None:
        cur = await self._execute(sql, params)
        row = await cur.fetchone()
        if row is None:
            return None
        return dict(row)

    async def _all(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        cur = await self._execute(sql, params)
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    # ── Stream CRUD ───────────────────────────────────────────────────────────

    async def create_stream(self, stream_id: str) -> bool:
        """Create a new stream. Returns True if created, False if it already exists.

        This is idempotent — calling create on an existing stream is a no-op.
        """
        existing = await self._one(
            "SELECT stream_id FROM streams WHERE stream_id = ?", (stream_id,)
        )
        if existing is not None:
            return False
        await self._execute(
            "INSERT INTO streams(stream_id, created_at) VALUES (?, ?)",
            (stream_id, time.time()),
        )
        await self._conn.commit()
        return True

    async def stream_exists(self, stream_id: str) -> bool:
        """Check if a stream exists."""
        row = await self._one(
            "SELECT stream_id FROM streams WHERE stream_id = ?", (stream_id,)
        )
        return row is not None

    async def get_stream_info(self, stream_id: str) -> dict[str, Any] | None:
        """Get stream metadata including current length."""
        stream = await self._one(
            "SELECT * FROM streams WHERE stream_id = ?", (stream_id,)
        )
        if stream is None:
            return None
        length_row = await self._one(
            "SELECT COALESCE(MAX(offset) + 1, 0) AS length FROM stream_chunks WHERE stream_id = ?",
            (stream_id,),
        )
        stream["length"] = int(length_row["length"]) if length_row else 0
        return stream

    async def close_stream(self, stream_id: str) -> None:
        """Close a stream (no more appends allowed). Signals EOF."""
        row = await self._one(
            "SELECT stream_id FROM streams WHERE stream_id = ?", (stream_id,)
        )
        if row is None:
            raise StreamNotFoundError(stream_id)
        await self._execute(
            "UPDATE streams SET closed = 1, closed_at = ? WHERE stream_id = ?",
            (time.time(), stream_id),
        )
        await self._conn.commit()
        # Wake all live-tail waiters so they see the close
        self._notify_waiters(stream_id)

    async def delete_stream(self, stream_id: str) -> bool:
        """Delete a stream and all its chunks. Returns True if deleted."""
        row = await self._one(
            "SELECT stream_id FROM streams WHERE stream_id = ?", (stream_id,)
        )
        if row is None:
            return False
        await self._execute(
            "DELETE FROM stream_chunks WHERE stream_id = ?", (stream_id,)
        )
        await self._execute("DELETE FROM streams WHERE stream_id = ?", (stream_id,))
        await self._conn.commit()
        self._notify_waiters(stream_id)
        return True

    # ── Append ────────────────────────────────────────────────────────────────

    async def append(
        self,
        stream_id: str,
        *,
        offset: int,
        data: bytes,
    ) -> int:
        """Append a chunk to a stream at the given offset.

        The offset must equal the current stream length (next expected offset).
        If the offset matches an existing chunk with identical data, the append
        is treated as idempotent (no error). If the data differs, raises
        ``OffsetConflictError``.

        Returns the offset that was written.
        """
        # Verify stream exists and is open
        stream = await self._one(
            "SELECT stream_id, closed FROM streams WHERE stream_id = ?", (stream_id,)
        )
        if stream is None:
            raise StreamNotFoundError(stream_id)
        if stream["closed"]:
            raise StreamClosedError(stream_id)

        # Check for idempotent retry
        existing = await self._one(
            "SELECT data FROM stream_chunks WHERE stream_id = ? AND offset = ?",
            (stream_id, offset),
        )
        if existing is not None:
            if existing["data"] == data:
                return offset  # Idempotent — same data
            raise OffsetConflictError(stream_id, offset)

        await self._execute(
            "INSERT INTO stream_chunks(stream_id, offset, data, created_at) VALUES (?, ?, ?, ?)",
            (stream_id, offset, data, time.time()),
        )
        await self._conn.commit()

        # Wake live-tail waiters
        self._notify_waiters(stream_id)

        return offset

    async def append_auto(
        self,
        stream_id: str,
        data: bytes,
    ) -> int:
        """Append a chunk at the next available offset. Returns the offset written.

        Convenience method that auto-computes the next offset. Useful when the
        producer doesn't need explicit offset control (most agent event writes).
        """
        stream = await self._one(
            "SELECT stream_id, closed FROM streams WHERE stream_id = ?", (stream_id,)
        )
        if stream is None:
            raise StreamNotFoundError(stream_id)
        if stream["closed"]:
            raise StreamClosedError(stream_id)

        length_row = await self._one(
            "SELECT COALESCE(MAX(offset) + 1, 0) AS next_offset FROM stream_chunks WHERE stream_id = ?",
            (stream_id,),
        )
        next_offset = int(length_row["next_offset"]) if length_row else 0

        await self._execute(
            "INSERT INTO stream_chunks(stream_id, offset, data, created_at) VALUES (?, ?, ?, ?)",
            (stream_id, next_offset, data, time.time()),
        )
        await self._conn.commit()

        self._notify_waiters(stream_id)
        return next_offset

    # ── Read ──────────────────────────────────────────────────────────────────

    async def read(
        self,
        stream_id: str,
        *,
        from_offset: int = 0,
        limit: int = 1000,
    ) -> list[StreamChunk]:
        """Read chunks from a stream starting at ``from_offset``.

        Returns up to ``limit`` chunks ordered by offset.
        """
        if not await self.stream_exists(stream_id):
            raise StreamNotFoundError(stream_id)

        rows = await self._all(
            "SELECT * FROM stream_chunks WHERE stream_id = ? AND offset >= ? ORDER BY offset LIMIT ?",
            (stream_id, from_offset, limit),
        )
        return [
            StreamChunk(
                stream_id=row["stream_id"],
                offset=row["offset"],
                data=row["data"]
                if isinstance(row["data"], bytes)
                else row["data"].encode(),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def get_stream_length(self, stream_id: str) -> int:
        """Return the number of chunks in a stream (i.e. next expected offset)."""
        row = await self._one(
            "SELECT COALESCE(MAX(offset) + 1, 0) AS length FROM stream_chunks WHERE stream_id = ?",
            (stream_id,),
        )
        return int(row["length"]) if row else 0

    # ── Live-tail support ─────────────────────────────────────────────────────

    def _notify_waiters(self, stream_id: str) -> None:
        """Wake all waiters for a stream (called after append or close)."""
        waiters = self._waiters.get(stream_id)
        if waiters:
            for w in waiters:
                w.set()

    async def wait_for_new_data(
        self,
        stream_id: str,
        *,
        timeout: float = 30.0,
    ) -> bool:
        """Block until new data is appended to the stream or timeout expires.

        Returns True if new data is available, False if timeout.
        Used by long-poll and SSE live-tail modes.
        """
        event = asyncio.Event()
        if stream_id not in self._waiters:
            self._waiters[stream_id] = []
        self._waiters[stream_id].append(event)
        try:
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout)
                return True
            except asyncio.TimeoutError:
                return False
        finally:
            waiters = self._waiters.get(stream_id)
            if waiters is not None:
                try:
                    waiters.remove(event)
                except ValueError:
                    pass
                if not waiters:
                    del self._waiters[stream_id]

    async def is_closed(self, stream_id: str) -> bool:
        """Check if a stream is closed (EOF)."""
        row = await self._one(
            "SELECT closed FROM streams WHERE stream_id = ?", (stream_id,)
        )
        if row is None:
            raise StreamNotFoundError(stream_id)
        return bool(row["closed"])
