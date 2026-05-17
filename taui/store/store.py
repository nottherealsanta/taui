"""
Store — SQLite append-only event log.

Every event in the system — agent state changes, tool calls, token streams,
messages, questions, approvals — is a row in one database. Streams are
ordered sequences of events addressed by (stream_id, offset).

Default path: <workspace>/.taui/store.db
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiosqlite

from taui.store.events import Event, EventType

logger = logging.getLogger(__name__)


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS streams (
    stream_id   TEXT PRIMARY KEY,
    parent_id   TEXT REFERENCES streams(stream_id),
    created_at  REAL NOT NULL,
    closed      INTEGER NOT NULL DEFAULT 0,
    closed_at   REAL
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_id   TEXT NOT NULL REFERENCES streams(stream_id),
    offset      INTEGER NOT NULL,
    type        TEXT NOT NULL,
    data        TEXT NOT NULL,
    created_at  REAL NOT NULL,
    UNIQUE(stream_id, offset)
);

CREATE INDEX IF NOT EXISTS idx_events_stream_offset
    ON events(stream_id, offset);

CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    stream_id    TEXT NOT NULL DEFAULT '',
    description  TEXT NOT NULL DEFAULT '',
    mode         TEXT NOT NULL DEFAULT 'normal',
    created_at   REAL NOT NULL,
    last_active  REAL NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    model        TEXT NOT NULL DEFAULT '',
    first_message TEXT NOT NULL DEFAULT ''
);
"""


# ── Errors ────────────────────────────────────────────────────────────────────


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
    """Raised when an append offset conflicts with different existing data."""

    def __init__(self, stream_id: str, offset: int) -> None:
        super().__init__(f"Offset conflict in {stream_id!r} at offset {offset}")
        self.stream_id = stream_id
        self.offset = offset


# ── Store ─────────────────────────────────────────────────────────────────────


class Store:
    """SQLite append-only event store.

    Each stream is an ordered sequence of events keyed by (stream_id, offset).
    Events carry an explicit type and a JSON data payload.

    Usage::

        store = Store(Path("/path/to/workspace"))
        await store.connect()
        await store.create_stream("agents/abc-123")
        await store.append("agents/abc-123", EventType.STATE_CHANGE, {"state": "running"})
        events = await store.read("agents/abc-123")
        await store.close()
    """

    def __init__(self, workspace: Path, *, db_path: Path | None = None) -> None:
        self.workspace = workspace
        self.db_path = db_path or (workspace / ".taui" / "store.db")
        self._db: aiosqlite.Connection | None = None
        self._waiters: dict[str, list[asyncio.Event]] = {}
        self._write_count: int = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Open the database and ensure the schema exists."""
        if self._db is not None:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode = WAL")
        await self._db.execute("PRAGMA synchronous = NORMAL")
        await self._db.executescript(_SCHEMA)
        await self._migrate_schema()
        await self._db.commit()

    async def close(self) -> None:
        """Close the database and wake all waiters."""
        if self._db is None:
            return
        await self._db.commit()
        await self._db.close()
        self._db = None
        for waiters in self._waiters.values():
            for w in waiters:
                w.set()
        self._waiters.clear()

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "Store not connected"
        return self._db

    async def checkpoint(self) -> None:
        """Run a WAL checkpoint for crash safety."""
        try:
            await self.db.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception:
            logger.debug("WAL checkpoint failed", exc_info=True)

    async def _migrate_schema(self) -> None:
        """Apply small forward-compatible migrations."""
        async with self.db.execute("PRAGMA table_info(sessions)") as cur:
            columns = {row["name"] for row in await cur.fetchall()}
        if "stream_id" not in columns:
            await self.db.execute(
                "ALTER TABLE sessions ADD COLUMN stream_id TEXT NOT NULL DEFAULT ''"
            )
        if "model" not in columns:
            await self.db.execute(
                "ALTER TABLE sessions ADD COLUMN model TEXT NOT NULL DEFAULT ''"
            )
        if "first_message" not in columns:
            await self.db.execute(
                "ALTER TABLE sessions ADD COLUMN first_message TEXT NOT NULL DEFAULT ''"
            )
        # Backfill first_message for sessions that don't have one yet
        await self.db.execute(
            "UPDATE sessions SET first_message = COALESCE(("
            "  SELECT SUBSTR(json_extract(e.data, '$.text'), 1, 60)"
            "  FROM events e"
            "  WHERE e.stream_id = sessions.stream_id"
            "    AND e.type = 'user_message'"
            "  ORDER BY e.offset ASC LIMIT 1"
            "), '') WHERE (first_message = '' OR first_message IS NULL)"
            "  AND stream_id != '' AND description = ''"
        )

    # ── Stream CRUD ───────────────────────────────────────────────────────

    async def create_stream(
        self, stream_id: str, *, parent_id: str | None = None
    ) -> bool:
        """Create a stream. Returns True if created, False if it already exists."""
        cur = await self.db.execute(
            "INSERT OR IGNORE INTO streams(stream_id, parent_id, created_at) "
            "VALUES (?, ?, ?)",
            (stream_id, parent_id, time.time()),
        )
        await self.db.commit()
        return cur.rowcount == 1

    async def stream_exists(self, stream_id: str) -> bool:
        """Check if a stream exists."""
        async with self.db.execute(
            "SELECT 1 FROM streams WHERE stream_id = ?", (stream_id,)
        ) as cur:
            return await cur.fetchone() is not None

    async def get_stream_info(self, stream_id: str) -> dict[str, Any] | None:
        """Get stream metadata including current length."""
        async with self.db.execute(
            "SELECT * FROM streams WHERE stream_id = ?", (stream_id,)
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                return None
            info = dict(row)
        async with self.db.execute(
            "SELECT COALESCE(MAX(offset) + 1, 0) FROM events WHERE stream_id = ?",
            (stream_id,),
        ) as cur:
            length_row = await cur.fetchone()
            info["length"] = length_row[0] if length_row else 0
        return info

    async def close_stream(self, stream_id: str) -> None:
        """Close a stream — no more appends allowed."""
        if not await self.stream_exists(stream_id):
            raise StreamNotFoundError(stream_id)
        await self.db.execute(
            "UPDATE streams SET closed = 1, closed_at = ? WHERE stream_id = ?",
            (time.time(), stream_id),
        )
        await self.db.commit()
        self._notify(stream_id)

    async def is_closed(self, stream_id: str) -> bool:
        """Check if a stream is closed (EOF)."""
        async with self.db.execute(
            "SELECT closed FROM streams WHERE stream_id = ?", (stream_id,)
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                raise StreamNotFoundError(stream_id)
            return bool(row[0])

    # ── Append ────────────────────────────────────────────────────────────

    async def _check_writable(self, stream_id: str) -> None:
        """Raise if the stream doesn't exist or is closed."""
        async with self.db.execute(
            "SELECT closed FROM streams WHERE stream_id = ?", (stream_id,)
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                raise StreamNotFoundError(stream_id)
            if row[0]:
                raise StreamClosedError(stream_id)

    async def append(
        self,
        stream_id: str,
        event_type: EventType,
        data: dict[str, Any],
        *,
        offset: int | None = None,
    ) -> int:
        """Append an event to a stream.

        If offset is None, appends at the next available offset.
        If offset is given and matches existing type+data identically, it's idempotent.
        If offset conflicts with different data, raises OffsetConflictError.

        Returns the offset written.
        """
        now = time.time()
        json_data = json.dumps(data, separators=(",", ":"))

        try:
            await self.db.execute("BEGIN IMMEDIATE")
            await self._check_writable(stream_id)

            if offset is None:
                async with self.db.execute(
                    "SELECT COALESCE(MAX(offset) + 1, 0) FROM events WHERE stream_id = ?",
                    (stream_id,),
                ) as cur:
                    row = await cur.fetchone()
                    write_offset = row[0] if row else 0
            else:
                write_offset = offset
                async with self.db.execute(
                    "SELECT type, data FROM events WHERE stream_id = ? AND offset = ?",
                    (stream_id, write_offset),
                ) as cur:
                    existing = await cur.fetchone()
                    if existing is not None:
                        if existing[0] == event_type.value and existing[1] == json_data:
                            await self.db.commit()
                            return write_offset  # Idempotent
                        raise OffsetConflictError(stream_id, write_offset)

            await self.db.execute(
                "INSERT INTO events(stream_id, offset, type, data, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (stream_id, write_offset, event_type.value, json_data, now),
            )
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        self._write_count += 1
        if self._write_count % 100 == 0:
            await self.checkpoint()

        self._notify(stream_id)
        return write_offset

    # ── Read ──────────────────────────────────────────────────────────────

    async def read(
        self,
        stream_id: str,
        *,
        from_offset: int = 0,
        limit: int = 1000,
    ) -> list[Event]:
        """Read events from a stream starting at from_offset."""
        if not await self.stream_exists(stream_id):
            raise StreamNotFoundError(stream_id)
        async with self.db.execute(
            "SELECT * FROM events "
            "WHERE stream_id = ? AND offset >= ? "
            "ORDER BY offset LIMIT ?",
            (stream_id, from_offset, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [
            Event(
                stream_id=row["stream_id"],
                offset=row["offset"],
                type=EventType(row["type"]),
                data=json.loads(row["data"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def get_length(self, stream_id: str) -> int:
        """Return the number of events in a stream."""
        async with self.db.execute(
            "SELECT COALESCE(MAX(offset) + 1, 0) FROM events WHERE stream_id = ?",
            (stream_id,),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    # ── Live-tail ─────────────────────────────────────────────────────────

    def _notify(self, stream_id: str) -> None:
        """Wake all waiters blocked on this stream."""
        waiters = self._waiters.get(stream_id)
        if waiters:
            for w in waiters:
                w.set()

    async def wait_for_new(self, stream_id: str, *, timeout: float = 30.0) -> bool:
        """Block until new data arrives on the stream or timeout expires.

        Returns True if woken by new data, False on timeout.
        """
        event = asyncio.Event()
        self._waiters.setdefault(stream_id, []).append(event)
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False
        finally:
            waiters = self._waiters.get(stream_id)
            if waiters:
                try:
                    waiters.remove(event)
                except ValueError:
                    pass
                if not waiters:
                    del self._waiters[stream_id]

    # ── Session metadata ──────────────────────────────────────────────────

    async def create_session(
        self,
        session_id: str,
        *,
        mode: str = "normal",
        stream_id: str | None = None,
        model: str | None = None,
    ) -> None:
        """Create a session metadata record."""
        now = time.time()
        await self.db.execute(
            "INSERT OR IGNORE INTO sessions"
            "(session_id, stream_id, description, mode, created_at, last_active, "
            "message_count, model)"
            " VALUES (?, ?, '', ?, ?, ?, 0, ?)",
            (session_id, stream_id or "", mode, now, now, model or ""),
        )
        if stream_id:
            await self.db.execute(
                "UPDATE sessions SET stream_id = ? WHERE session_id = ? AND stream_id = ''",
                (stream_id, session_id),
            )
        await self.db.commit()

    async def update_session(
        self,
        session_id: str,
        *,
        description: str | None = None,
        message_count: int | None = None,
        mode: str | None = None,
        stream_id: str | None = None,
        model: str | None = None,
        first_message: str | None = None,
    ) -> None:
        """Update session metadata fields."""
        sets: list[str] = ["last_active = ?"]
        params: list[Any] = [time.time()]
        if description is not None:
            sets.append("description = ?")
            params.append(description)
        if message_count is not None:
            sets.append("message_count = ?")
            params.append(message_count)
        if mode is not None:
            sets.append("mode = ?")
            params.append(mode)
        if stream_id is not None:
            sets.append("stream_id = ?")
            params.append(stream_id)
        if model is not None:
            sets.append("model = ?")
            params.append(model)
        if first_message is not None:
            sets.append("first_message = ?")
            params.append(first_message)
        params.append(session_id)
        await self.db.execute(
            f"UPDATE sessions SET {', '.join(sets)} WHERE session_id = ?",
            params,
        )
        await self.db.commit()

    async def list_sessions(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """List recent sessions, newest first."""
        async with self.db.execute(
            "SELECT * FROM sessions ORDER BY last_active DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def list_sessions_with_parents(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """List recent sessions with parent session info resolved through streams."""
        async with self.db.execute(
            "SELECT s.*, ps.session_id AS parent_session_id "
            "FROM sessions s "
            "LEFT JOIN streams st ON s.stream_id = st.stream_id "
            "LEFT JOIN sessions ps ON st.parent_id = ps.stream_id "
            "ORDER BY s.last_active DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def subscribe(
        self,
        stream_id: str,
        *,
        from_offset: int = 0,
        poll_interval: float = 0.5,
    ) -> AsyncIterator[Event]:
        """Async iterator that yields events as they arrive.

        Starts from from_offset and yields new events as they are
        appended. Useful for external observers tailing a live stream.

        Usage::

            async for event in store.subscribe("agents/abc"):
                print(event.type, event.data)
        """
        offset = from_offset
        while self._db is not None:
            events = await self.read(
                stream_id, from_offset=offset, limit=100
            )
            for event in events:
                yield event
                offset = event.offset + 1
            if not events:
                # Wait for new data or poll interval
                await self.wait_for_new(
                    stream_id, timeout=poll_interval
                )

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get a single session's metadata."""
        async with self.db.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None
