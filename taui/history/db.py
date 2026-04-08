"""
HistoryDB — global message history stored at ~/.taui/history.db.

Records all agent sessions and messages across every workspace so users
can review past conversations.
"""

from __future__ import annotations

import json
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

TAUI_HOME = Path.home() / ".taui"
DEFAULT_HISTORY_DB = TAUI_HOME / "history.db"


def _ensure_taui_home() -> Path:
    """Create ~/.taui/ if it doesn't exist and return the path."""
    TAUI_HOME.mkdir(parents=True, exist_ok=True)
    return TAUI_HOME


_SCHEMA = """\
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS sessions (
    agent_id        TEXT PRIMARY KEY,
    workspace       TEXT,
    spec_ref        TEXT NOT NULL,
    task            TEXT NOT NULL,
    display_name    TEXT,
    model           TEXT,
    provider        TEXT,
    agent_type      TEXT NOT NULL DEFAULT 'root',
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_workspace ON sessions(workspace);
CREATE INDEX IF NOT EXISTS idx_sessions_created   ON sessions(created_at);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL REFERENCES sessions(agent_id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    content         TEXT,
    tool_call_id    TEXT,
    name            TEXT,
    metadata        TEXT,
    seq             INTEGER NOT NULL,
    created_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(agent_id, seq);
CREATE INDEX IF NOT EXISTS idx_messages_role  ON messages(role);
"""


class HistoryDB:
    """Async SQLite store for global message history."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DEFAULT_HISTORY_DB
        self._conn: Any | None = None

    async def connect(self) -> None:
        if self._conn is not None:
            return
        _ensure_taui_home()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if _aiosqlite is not None:
            conn = await _aiosqlite.connect(self.db_path.as_posix())
            conn.row_factory = _aiosqlite.Row
            self._conn = conn
        else:
            conn = sqlite3.connect(self.db_path.as_posix())
            conn.row_factory = sqlite3.Row
            self._conn = conn
        await self._migrate()

    async def close(self) -> None:
        if self._conn is None:
            return
        if _aiosqlite is not None:
            await self._conn.close()
        else:
            self._conn.close()
        self._conn = None

    # ── Write ──────────────────────────────────────────────────────────────────

    async def record_session(
        self,
        *,
        agent_id: str,
        workspace: str | None,
        spec_ref: str,
        task: str,
        display_name: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        agent_type: str = "root",
    ) -> None:
        now = time.time()
        await self._execute(
            """
INSERT OR IGNORE INTO sessions(
    agent_id, workspace, spec_ref, task, display_name,
    model, provider, agent_type, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
            (
                agent_id,
                workspace,
                spec_ref,
                task,
                display_name,
                model,
                provider,
                agent_type,
                now,
                now,
            ),
        )

    async def record_message(
        self,
        *,
        agent_id: str,
        role: str,
        content: str | None,
        tool_call_id: str | None = None,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        seq_row = await self._fetchone(
            "SELECT COALESCE(MAX(seq), 0) AS seq FROM messages WHERE agent_id = ?",
            (agent_id,),
        )
        next_seq = (int(seq_row["seq"]) + 1) if seq_row else 1
        metadata_json = json.dumps(metadata) if metadata is not None else None
        cur = await self._execute(
            """
INSERT INTO messages(agent_id, role, content, tool_call_id, name, metadata, seq, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
""",
            (agent_id, role, content, tool_call_id, name, metadata_json, next_seq, time.time()),
        )
        return cur.lastrowid or 0

    # ── Read ───────────────────────────────────────────────────────────────────

    async def list_sessions(
        self,
        *,
        workspace: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if workspace is not None:
            rows = await self._fetchall(
                "SELECT * FROM sessions WHERE workspace = ? ORDER BY created_at DESC LIMIT ?",
                (workspace, limit),
            )
        else:
            rows = await self._fetchall(
                "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in rows]

    async def get_messages(
        self, agent_id: str, *, limit: int = 500
    ) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT * FROM messages WHERE agent_id = ? ORDER BY seq LIMIT ?",
            (agent_id, limit),
        )
        return [dict(r) for r in rows]

    async def get_messages_page(
        self,
        agent_id: str,
        *,
        before_seq: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if before_seq is None:
            rows = await self._fetchall(
                "SELECT * FROM messages WHERE agent_id = ? ORDER BY seq DESC LIMIT ?",
                (agent_id, limit),
            )
        else:
            rows = await self._fetchall(
                "SELECT * FROM messages WHERE agent_id = ? AND seq < ? ORDER BY seq DESC LIMIT ?",
                (agent_id, before_seq, limit),
            )
        # Queries run in DESC order for efficient "latest page" retrieval.
        # Reverse to ascending order for chat rendering.
        return [dict(r) for r in reversed(rows)]

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _migrate(self) -> None:
        assert self._conn is not None
        if _aiosqlite is not None:
            await self._conn.executescript(_SCHEMA)
            await self._migrate_messages_metadata_column()
            await self._conn.commit()
        else:
            self._conn.executescript(_SCHEMA)
            await self._migrate_messages_metadata_column()
            self._conn.commit()

    async def _migrate_messages_metadata_column(self) -> None:
        """Backfill schema change for pre-metadata history databases."""
        columns = await self._fetchall("PRAGMA table_info(messages)")
        column_names = {
            c["name"] if not isinstance(c, dict) else c.get("name")
            for c in columns
        }
        if "metadata" not in column_names:
            await self._execute("ALTER TABLE messages ADD COLUMN metadata TEXT")

    async def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        assert self._conn is not None
        if _aiosqlite is not None:
            cur = await self._conn.execute(sql, params)
            await self._conn.commit()
            return cur
        else:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    async def _fetchone(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> Any | None:
        assert self._conn is not None
        if _aiosqlite is not None:
            cur = await self._conn.execute(sql, params)
            return await cur.fetchone()
        else:
            cur = self._conn.execute(sql, params)
            return cur.fetchone()

    async def _fetchall(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> list[Any]:
        assert self._conn is not None
        if _aiosqlite is not None:
            cur = await self._conn.execute(sql, params)
            return await cur.fetchall()
        else:
            cur = self._conn.execute(sql, params)
            return cur.fetchall()
