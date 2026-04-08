"""
AgentHistoryDB — on-disk, WAL-mode SQLite database for agent sessions and messages.

Stores all agent-related state (sessions, messages, tool calls, questions, events,
branch locks, task queue) in a project-local on-disk SQLite file with WAL journaling.
Every write is immediately durable — no in-memory snapshot required.

Default path: <workspace>/.taui/agents.db
"""

from __future__ import annotations

import asyncio
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


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """\
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agent_sessions (
    agent_id        TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    parent_agent_id TEXT REFERENCES agent_sessions(agent_id) ON DELETE SET NULL,
    spec_ref        TEXT NOT NULL,
    task            TEXT NOT NULL,
    state           TEXT NOT NULL DEFAULT 'idle',
    tier            TEXT NOT NULL DEFAULT 'medium',
    agent_type      TEXT NOT NULL DEFAULT 'root',
    display_name    TEXT,
    model           TEXT,
    provider        TEXT,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_state    ON agent_sessions(state);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_spec_ref ON agent_sessions(spec_ref);

CREATE TABLE IF NOT EXISTS agent_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL REFERENCES agent_sessions(agent_id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    content         TEXT,
    tool_call_id    TEXT,
    name            TEXT,
    metadata        TEXT,
    seq             INTEGER NOT NULL,
    created_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_messages_agent ON agent_messages(agent_id, seq);

CREATE TABLE IF NOT EXISTS agent_tool_calls (
    call_id         TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES agent_sessions(agent_id) ON DELETE CASCADE,
    message_id      INTEGER REFERENCES agent_messages(id) ON DELETE SET NULL,
    tool_name       TEXT NOT NULL,
    arguments       TEXT NOT NULL,
    created_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_agent ON agent_tool_calls(agent_id);

CREATE TABLE IF NOT EXISTS agent_tool_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id         TEXT NOT NULL REFERENCES agent_tool_calls(call_id) ON DELETE CASCADE,
    output          TEXT,
    error           TEXT,
    duration_ms     INTEGER,
    created_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_tool_results_call ON agent_tool_results(call_id);

CREATE TABLE IF NOT EXISTS agent_questions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id            TEXT NOT NULL REFERENCES agent_sessions(agent_id) ON DELETE CASCADE,
    question_node_ref   TEXT NOT NULL,
    question            TEXT NOT NULL,
    options             TEXT,
    answer              TEXT,
    status              TEXT NOT NULL DEFAULT 'pending',
    created_at          REAL NOT NULL,
    answered_at         REAL
);

CREATE INDEX IF NOT EXISTS idx_agent_questions_agent  ON agent_questions(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_questions_status ON agent_questions(status);

CREATE TABLE IF NOT EXISTS agent_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT NOT NULL REFERENCES agent_sessions(agent_id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,
    payload     TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    created_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_events_agent ON agent_events(agent_id, seq);

CREATE TABLE IF NOT EXISTS branch_locks (
    spec_ref    TEXT NOT NULL,
    agent_id    TEXT NOT NULL REFERENCES agent_sessions(agent_id) ON DELETE CASCADE,
    locked_at   REAL NOT NULL,
    PRIMARY KEY (spec_ref, agent_id)
);

CREATE TABLE IF NOT EXISTS agent_task_queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT NOT NULL REFERENCES agent_sessions(agent_id) ON DELETE CASCADE,
    message     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  REAL NOT NULL,
    started_at  REAL
);

CREATE INDEX IF NOT EXISTS idx_agent_task_queue_agent ON agent_task_queue(agent_id, status);
"""


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


class AgentHistoryDB:
    """On-disk, WAL-mode SQLite store for all agent state.

    Each write commits immediately — no snapshot needed.  Messages survive
    server restarts and crashes (WAL checkpoint on close).

    Usage::

        db = AgentHistoryDB(workspace)
        await db.connect()
        # ... use ...
        await db.close()
    """

    def __init__(self, workspace: Path, *, db_path: Path | None = None) -> None:
        self.workspace = workspace
        self.db_path = db_path or (workspace / ".taui" / "agents.db")
        self._conn: Any | None = None
        self._conn_lock = asyncio.Lock()

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
            await self._migrate()

    async def close(self) -> None:
        async with self._conn_lock:
            if self._conn is None:
                return
            if _aiosqlite is not None:
                await self._conn.commit()
            else:
                await self._conn.commit()
            await self._conn.close()
            self._conn = None

    # ── Migration ─────────────────────────────────────────────────────────────

    async def _migrate(self) -> None:
        assert self._conn is not None
        await self._conn.executescript(_SCHEMA)
        await self._backfill_columns()
        await self._conn.commit()

    async def _backfill_columns(self) -> None:
        """Apply any column additions needed for databases created before a schema update."""
        agent_session_cols = {
            str(row["name"])
            for row in await self._all("PRAGMA table_info(agent_sessions)")
        }
        if agent_session_cols:
            if "agent_type" not in agent_session_cols:
                await self._execute(
                    "ALTER TABLE agent_sessions ADD COLUMN agent_type TEXT NOT NULL DEFAULT 'root'"
                )
            if "display_name" not in agent_session_cols:
                await self._execute(
                    "ALTER TABLE agent_sessions ADD COLUMN display_name TEXT"
                )

        agent_message_cols = {
            str(row["name"])
            for row in await self._all("PRAGMA table_info(agent_messages)")
        }
        if agent_message_cols and "metadata" not in agent_message_cols:
            await self._execute("ALTER TABLE agent_messages ADD COLUMN metadata TEXT")

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        assert self._conn is not None
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

    # ── Agent sessions ────────────────────────────────────────────────────────

    async def create_agent_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        spec_ref: str,
        task: str,
        tier: str = "medium",
        agent_type: str = "root",
        display_name: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        parent_agent_id: str | None = None,
    ) -> None:
        now_ts = time.time()
        await self._execute(
            """
INSERT INTO agent_sessions(
    agent_id, session_id, parent_agent_id, spec_ref, task, state, tier,
    agent_type, display_name, model, provider,
    created_at, updated_at
) VALUES (?, ?, ?, ?, ?, 'idle', ?, ?, ?, ?, ?, ?, ?)
""",
            (
                agent_id,
                session_id,
                parent_agent_id,
                spec_ref,
                task,
                tier,
                agent_type,
                display_name,
                model,
                provider,
                now_ts,
                now_ts,
            ),
        )
        await self._conn.commit()

    async def get_agent_session(self, agent_id: str) -> dict[str, Any] | None:
        return await self._one(
            "SELECT * FROM agent_sessions WHERE agent_id = ?", (agent_id,)
        )

    async def list_agent_sessions(
        self, *, state: str | None = None
    ) -> list[dict[str, Any]]:
        if state is not None:
            return await self._all(
                "SELECT * FROM agent_sessions WHERE state = ? ORDER BY created_at DESC",
                (state,),
            )
        return await self._all("SELECT * FROM agent_sessions ORDER BY created_at DESC")

    async def list_agent_sessions_by_states(
        self, states: set[str]
    ) -> list[dict[str, Any]]:
        """Return all agent sessions whose state is in *states*."""
        if not states:
            return []
        placeholders = ", ".join("?" * len(states))
        return await self._all(
            f"SELECT * FROM agent_sessions WHERE state IN ({placeholders}) ORDER BY created_at",
            tuple(states),
        )

    async def update_agent_state(self, agent_id: str, state: str) -> None:
        await self._execute(
            "UPDATE agent_sessions SET state = ?, updated_at = ? WHERE agent_id = ?",
            (state, time.time(), agent_id),
        )
        await self._conn.commit()

    # ── Agent messages ────────────────────────────────────────────────────────

    async def record_agent_message(
        self,
        *,
        agent_id: str,
        role: str,
        content: str | None,
        tool_call_id: str | None = None,
        name: str | None = None,
        metadata: str | None = None,
    ) -> int:
        row = await self._one(
            "SELECT COALESCE(MAX(seq), 0) AS seq FROM agent_messages WHERE agent_id = ?",
            (agent_id,),
        )
        next_seq = int(row["seq"]) + 1 if row is not None else 1
        cur = await self._execute(
            """
INSERT INTO agent_messages(agent_id, role, content, tool_call_id, name, metadata, seq, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
""",
            (
                agent_id,
                role,
                content,
                tool_call_id,
                name,
                metadata,
                next_seq,
                time.time(),
            ),
        )
        await self._conn.commit()
        return int(cur.lastrowid or 0)

    # ── Agent tool calls / results ────────────────────────────────────────────

    async def record_agent_tool_call(
        self,
        *,
        call_id: str,
        agent_id: str,
        message_id: int | None,
        tool_name: str,
        arguments: str,
    ) -> None:
        await self._execute(
            """
INSERT INTO agent_tool_calls(call_id, agent_id, message_id, tool_name, arguments, created_at)
VALUES (?, ?, ?, ?, ?, ?)
""",
            (call_id, agent_id, message_id, tool_name, arguments, time.time()),
        )
        await self._conn.commit()

    async def record_agent_tool_result(
        self,
        *,
        call_id: str,
        output: str | None,
        error: str | None,
        duration_ms: int | None,
    ) -> None:
        await self._execute(
            """
INSERT INTO agent_tool_results(call_id, output, error, duration_ms, created_at)
VALUES (?, ?, ?, ?, ?)
""",
            (call_id, output, error, duration_ms, time.time()),
        )
        await self._conn.commit()

    # ── Agent events ──────────────────────────────────────────────────────────

    async def add_agent_event(
        self,
        *,
        agent_id: str,
        event_type: str,
        payload: str,
    ) -> int:
        row = await self._one(
            "SELECT COALESCE(MAX(seq), 0) AS seq FROM agent_events WHERE agent_id = ?",
            (agent_id,),
        )
        next_seq = int(row["seq"]) + 1 if row is not None else 1
        cur = await self._execute(
            """
INSERT INTO agent_events(agent_id, event_type, payload, seq, created_at)
VALUES (?, ?, ?, ?, ?)
""",
            (agent_id, event_type, payload, next_seq, time.time()),
        )
        await self._conn.commit()
        return int(cur.lastrowid or 0)

    async def get_agent_events(
        self, agent_id: str, *, after_seq: int = 0
    ) -> list[dict[str, Any]]:
        return await self._all(
            "SELECT * FROM agent_events WHERE agent_id = ? AND seq > ? ORDER BY seq",
            (agent_id, after_seq),
        )

    # ── Agent task queue ──────────────────────────────────────────────────────

    async def enqueue_agent_task(self, *, agent_id: str, message: str) -> int:
        cur = await self._execute(
            """
INSERT INTO agent_task_queue(agent_id, message, status, created_at)
VALUES (?, ?, 'pending', ?)
""",
            (agent_id, message, time.time()),
        )
        await self._conn.commit()
        return int(cur.lastrowid or 0)

    async def pop_agent_task(self, agent_id: str) -> dict[str, Any] | None:
        row = await self._one(
            "SELECT * FROM agent_task_queue WHERE agent_id = ? AND status = 'pending' ORDER BY id LIMIT 1",
            (agent_id,),
        )
        if row is None:
            return None
        await self._execute(
            "UPDATE agent_task_queue SET status = 'started', started_at = ? WHERE id = ?",
            (time.time(), row["id"]),
        )
        await self._conn.commit()
        return row

    async def complete_agent_task(self, task_id: int) -> None:
        await self._execute(
            "UPDATE agent_task_queue SET status = 'done' WHERE id = ?",
            (task_id,),
        )
        await self._conn.commit()

    # ── Agent questions ────────────────────────────────────────────────────────

    async def add_agent_question(
        self,
        *,
        agent_id: str,
        question_node_ref: str,
        question: str,
        options: list[str] | None = None,
    ) -> str:
        """Insert a pending question; returns question_node_ref."""
        await self._execute(
            """
INSERT INTO agent_questions(agent_id, question_node_ref, question, options, status, created_at)
VALUES (?, ?, ?, ?, 'pending', ?)
""",
            (
                agent_id,
                question_node_ref,
                question,
                json.dumps(options) if options is not None else None,
                time.time(),
            ),
        )
        await self._conn.commit()
        return question_node_ref

    async def answer_agent_question(self, question_node_ref: str, answer: str) -> bool:
        """Mark question as answered. Returns True if a row was updated."""
        cur = await self._execute(
            """
UPDATE agent_questions
SET answer = ?, status = 'answered', answered_at = ?
WHERE question_node_ref = ? AND status = 'pending'
""",
            (answer, time.time(), question_node_ref),
        )
        await self._conn.commit()
        # rowcount not available on all async cursors — use lastrowid proxy
        return bool(cur.lastrowid)

    async def dismiss_agent_question(self, question_node_ref: str) -> None:
        await self._execute(
            "UPDATE agent_questions SET status = 'dismissed', answered_at = ? WHERE question_node_ref = ? AND status = 'pending'",
            (time.time(), question_node_ref),
        )
        await self._conn.commit()

    async def get_pending_questions(self, agent_id: str) -> list[dict[str, Any]]:
        return await self._all(
            "SELECT * FROM agent_questions WHERE agent_id = ? AND status = 'pending' ORDER BY id",
            (agent_id,),
        )

    async def get_question_by_ref(
        self, question_node_ref: str
    ) -> dict[str, Any] | None:
        return await self._one(
            "SELECT * FROM agent_questions WHERE question_node_ref = ?",
            (question_node_ref,),
        )

    async def dismiss_all_agent_questions(self, agent_id: str) -> None:
        """Dismiss all pending questions for an agent (called on stop)."""
        await self._execute(
            "UPDATE agent_questions SET status = 'dismissed', answered_at = ? WHERE agent_id = ? AND status = 'pending'",
            (time.time(), agent_id),
        )
        await self._conn.commit()

    # ── Branch locks ──────────────────────────────────────────────────────────

    async def acquire_branch_lock(self, spec_ref: str, agent_id: str) -> None:
        await self._execute(
            "INSERT OR IGNORE INTO branch_locks(spec_ref, agent_id, locked_at) VALUES (?, ?, ?)",
            (spec_ref, agent_id, time.time()),
        )
        await self._conn.commit()

    async def release_branch_lock(self, spec_ref: str, agent_id: str) -> None:
        await self._execute(
            "DELETE FROM branch_locks WHERE spec_ref = ? AND agent_id = ?",
            (spec_ref, agent_id),
        )
        await self._conn.commit()

    async def get_branch_lock(self, spec_ref: str) -> dict[str, Any] | None:
        return await self._one(
            "SELECT * FROM branch_locks WHERE spec_ref = ?",
            (spec_ref,),
        )

    async def list_branch_locks(self) -> list[dict[str, Any]]:
        return await self._all("SELECT * FROM branch_locks ORDER BY locked_at")

    async def list_branch_locks_for_agent(self, agent_id: str) -> list[dict[str, Any]]:
        return await self._all(
            "SELECT * FROM branch_locks WHERE agent_id = ?", (agent_id,)
        )
