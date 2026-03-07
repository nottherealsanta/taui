from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sqlite3
import time
from typing import Any
from uuid import uuid4

from platformdirs import user_cache_dir

from .models import SpecFile, SpecNode, SpecNodeDetail

try:
    import aiosqlite as _aiosqlite
except ModuleNotFoundError:  # pragma: no cover - fallback for local dev envs
    _aiosqlite = None


class _SQLiteRow(dict[str, Any]):
    def __getattr__(self, key: str) -> Any:
        return self[key]


class _FallbackCursor:
    def __init__(self, rows: list[sqlite3.Row] | None = None, lastrowid: int | None = None) -> None:
        self._rows = rows or []
        self.lastrowid = lastrowid

    async def fetchone(self) -> _SQLiteRow | None:
        if not self._rows:
            return None
        row = self._rows[0]
        return _SQLiteRow({k: row[k] for k in row.keys()})

    async def fetchall(self) -> list[_SQLiteRow]:
        out: list[_SQLiteRow] = []
        for row in self._rows:
            out.append(_SQLiteRow({k: row[k] for k in row.keys()}))
        return out


class _FallbackConnection:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._lock = asyncio.Lock()

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _FallbackCursor:
        async with self._lock:
            cur = self._conn.execute(sql, params)
            rows = None
            first = sql.lstrip().upper()
            if first.startswith("SELECT") or first.startswith("WITH") or first.startswith("PRAGMA"):
                rows = cur.fetchall()
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

    @property
    def raw(self) -> sqlite3.Connection:
        return self._conn


@dataclass(slots=True)
class NodeUpsert:
    id: str
    file_id: int
    spec_ref: str
    anchor: str
    title: str
    depth: int
    heading_level: int | None
    line_start: int | None
    line_end: int | None
    intent: str | None
    status: str | None
    content: str
    sort_order: int


class SpecDB:
    def __init__(
        self,
        workspace: Path,
        *,
        db_path: Path | None = None,
        snapshot_interval_sec: float = 3.0,
    ) -> None:
        self.workspace = workspace
        self.db_path = db_path or self._default_db_path(workspace)
        self._conn: Any | None = None
        self._conn_lock = asyncio.Lock()
        self._persist_lock = asyncio.Lock()
        self._snapshot_interval_sec = snapshot_interval_sec
        self._snapshot_task: asyncio.Task[None] | None = None

    @staticmethod
    def _default_db_path(workspace: Path) -> Path:
        digest = sha256(str(workspace).encode("utf-8")).hexdigest()[:12]
        return Path(user_cache_dir("taui")) / digest / "spec.db"

    async def connect(self) -> None:
        async with self._conn_lock:
            if self._conn is not None:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            if _aiosqlite is not None:
                conn = await _aiosqlite.connect(":memory:")
                conn.row_factory = _aiosqlite.Row
                self._conn = conn
            else:
                self._conn = _FallbackConnection(":memory:")
            await self._load_snapshot_from_disk()
            await self._migrate()
            self._start_snapshot_loop()

    async def close(self) -> None:
        if self._snapshot_task is not None:
            self._snapshot_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._snapshot_task
            self._snapshot_task = None
        if self._conn is None:
            return
        await self.flush_snapshot_to_disk()
        await self._conn.close()
        self._conn = None

    def _start_snapshot_loop(self) -> None:
        if self._snapshot_task is not None and not self._snapshot_task.done():
            return
        self._snapshot_task = asyncio.create_task(self._snapshot_loop())

    async def _snapshot_loop(self) -> None:
        while True:
            await asyncio.sleep(self._snapshot_interval_sec)
            await self.flush_snapshot_to_disk()

    async def _load_snapshot_from_disk(self) -> None:
        if self._conn is None or not self.db_path.exists():
            return
        if _aiosqlite is not None and isinstance(self._conn, _aiosqlite.Connection):
            disk = await _aiosqlite.connect(self.db_path.as_posix())
            try:
                await disk.backup(self._conn)
            finally:
                await disk.close()
            return

        if isinstance(self._conn, _FallbackConnection):
            disk = sqlite3.connect(self.db_path.as_posix())
            try:
                disk.backup(self._conn.raw)
            finally:
                disk.close()

    async def flush_snapshot_to_disk(self) -> None:
        if self._conn is None:
            return
        async with self._persist_lock:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            if _aiosqlite is not None and isinstance(self._conn, _aiosqlite.Connection):
                await self._conn.commit()
                disk = await _aiosqlite.connect(self.db_path.as_posix())
                try:
                    await self._conn.backup(disk)
                    await disk.commit()
                finally:
                    await disk.close()
                return

            if isinstance(self._conn, _FallbackConnection):
                await self._conn.commit()
                disk = sqlite3.connect(self.db_path.as_posix())
                try:
                    self._conn.raw.backup(disk)
                    disk.commit()
                finally:
                    disk.close()

    async def _migrate(self) -> None:
        assert self._conn is not None
        await self._conn.executescript(
            """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rel_path TEXT NOT NULL UNIQUE,
    content_hash TEXT NOT NULL,
    last_seen REAL NOT NULL,
    mtime_ns INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    spec_ref TEXT NOT NULL UNIQUE,
    anchor TEXT NOT NULL,
    title TEXT NOT NULL,
    depth INTEGER NOT NULL,
    heading_level INTEGER,
    line_start INTEGER,
    line_end INTEGER,
    intent TEXT,
    status TEXT,
    content TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_nodes_file_id ON nodes(file_id);
CREATE INDEX IF NOT EXISTS idx_nodes_depth ON nodes(depth);
CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status);

CREATE TABLE IF NOT EXISTS edges (
    parent_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    child_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (parent_id, child_id)
);

CREATE INDEX IF NOT EXISTS idx_edges_child ON edges(child_id);

CREATE TABLE IF NOT EXISTS node_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_node TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    to_node TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    UNIQUE(from_node, to_node)
);

CREATE INDEX IF NOT EXISTS idx_node_refs_to ON node_refs(to_node);

CREATE TABLE IF NOT EXISTS node_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_node_metadata_node ON node_metadata(node_id);
CREATE INDEX IF NOT EXISTS idx_node_metadata_key ON node_metadata(node_id, key);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    spec_ref TEXT,
    node_id TEXT REFERENCES nodes(id) ON DELETE SET NULL,
    parent_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'active',
    model TEXT,
    provider TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_node ON sessions(node_id);
CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT,
    name TEXT,
    tool_call_id TEXT,
    seq INTEGER NOT NULL,
    created_at REAL NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, seq);

CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    arguments TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_message ON tool_calls(message_id);

CREATE TABLE IF NOT EXISTS tool_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_call_id TEXT NOT NULL REFERENCES tool_calls(id) ON DELETE CASCADE,
    output TEXT,
    error TEXT,
    duration_ms INTEGER,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_results_call ON tool_results(tool_call_id);

CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
    node_id TEXT REFERENCES nodes(id) ON DELETE SET NULL,
    question TEXT NOT NULL,
    options TEXT,
    answer TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL,
    answered_at REAL
);

CREATE INDEX IF NOT EXISTS idx_questions_session ON questions(session_id);
CREATE INDEX IF NOT EXISTS idx_questions_node ON questions(node_id);
CREATE INDEX IF NOT EXISTS idx_questions_status ON questions(status);

CREATE TABLE IF NOT EXISTS subagent_spawns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    child_session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    purpose TEXT,
    created_at REAL NOT NULL,
    UNIQUE(parent_session_id, child_session_id)
);

CREATE INDEX IF NOT EXISTS idx_spawns_parent ON subagent_spawns(parent_session_id);
CREATE INDEX IF NOT EXISTS idx_spawns_child ON subagent_spawns(child_session_id);
"""
        )
        await self._conn.commit()

    async def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        assert self._conn is not None
        return await self._conn.execute(sql, params)

    async def _one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        cur = await self._execute(sql, params)
        row = await cur.fetchone()
        if row is None:
            return None
        return dict(row)

    async def _all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        cur = await self._execute(sql, params)
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def upsert_file(self, rel_path: str, content_hash: str, mtime_ns: int, now_ts: float) -> SpecFile:
        await self._execute(
            """
INSERT INTO files(rel_path, content_hash, last_seen, mtime_ns)
VALUES (?, ?, ?, ?)
ON CONFLICT(rel_path) DO UPDATE SET
    content_hash=excluded.content_hash,
    last_seen=excluded.last_seen,
    mtime_ns=excluded.mtime_ns
""",
            (rel_path, content_hash, now_ts, mtime_ns),
        )
        await self._conn.commit()
        row = await self._one(
            "SELECT id, rel_path, content_hash, last_seen, mtime_ns FROM files WHERE rel_path = ?",
            (rel_path,),
        )
        assert row is not None
        return SpecFile(**row)

    async def update_file_tracking(self, file_id: int, *, content_hash: str, mtime_ns: int, last_seen: float) -> None:
        await self._execute(
            "UPDATE files SET content_hash = ?, mtime_ns = ?, last_seen = ? WHERE id = ?",
            (content_hash, mtime_ns, last_seen, file_id),
        )
        await self._conn.commit()

    async def get_file(self, rel_path: str) -> SpecFile | None:
        row = await self._one(
            "SELECT id, rel_path, content_hash, last_seen, mtime_ns FROM files WHERE rel_path = ?",
            (rel_path,),
        )
        return SpecFile(**row) if row is not None else None

    async def get_file_by_id(self, file_id: int) -> SpecFile | None:
        row = await self._one(
            "SELECT id, rel_path, content_hash, last_seen, mtime_ns FROM files WHERE id = ?",
            (file_id,),
        )
        return SpecFile(**row) if row is not None else None

    async def list_files(self) -> list[SpecFile]:
        rows = await self._all(
            "SELECT id, rel_path, content_hash, last_seen, mtime_ns FROM files ORDER BY rel_path"
        )
        return [SpecFile(**row) for row in rows]

    async def delete_missing_files(self, rel_paths: set[str]) -> None:
        if rel_paths:
            placeholders = ",".join("?" for _ in rel_paths)
            await self._execute(f"DELETE FROM files WHERE rel_path NOT IN ({placeholders})", tuple(sorted(rel_paths)))
        else:
            await self._execute("DELETE FROM files")
        await self._conn.commit()

    async def list_node_ids_by_file(self, file_id: int) -> dict[str, str]:
        rows = await self._all("SELECT id, anchor FROM nodes WHERE file_id = ?", (file_id,))
        return {row["anchor"]: row["id"] for row in rows}

    async def replace_nodes_for_file(self, file_id: int, nodes: list[NodeUpsert]) -> None:
        now_ts = time.time()
        await self._execute("DELETE FROM nodes WHERE file_id = ?", (file_id,))
        for node in nodes:
            await self._execute(
                """
INSERT INTO nodes(
    id, file_id, spec_ref, anchor, title, depth, heading_level,
    line_start, line_end, intent, status, content, sort_order, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                (
                    node.id,
                    file_id,
                    node.spec_ref,
                    node.anchor,
                    node.title,
                    node.depth,
                    node.heading_level,
                    node.line_start,
                    node.line_end,
                    node.intent,
                    node.status,
                    node.content,
                    node.sort_order,
                    now_ts,
                    now_ts,
                ),
            )
        await self._conn.commit()

    async def replace_edges(self, edges: list[tuple[str, str, int]]) -> None:
        await self._execute("DELETE FROM edges")
        for parent_id, child_id, sort_order in edges:
            await self._execute(
                "INSERT OR IGNORE INTO edges(parent_id, child_id, sort_order) VALUES (?, ?, ?)",
                (parent_id, child_id, sort_order),
            )
        await self._conn.commit()

    async def replace_node_refs(self, refs: list[tuple[str, str]]) -> None:
        await self._execute("DELETE FROM node_refs")
        for from_node, to_node in refs:
            await self._execute(
                "INSERT OR IGNORE INTO node_refs(from_node, to_node) VALUES (?, ?)",
                (from_node, to_node),
            )
        await self._conn.commit()

    async def replace_node_metadata(self, metadata: list[tuple[str, str, str]]) -> None:
        await self._execute("DELETE FROM node_metadata")
        for node_id, key, value in metadata:
            await self._execute(
                "INSERT INTO node_metadata(node_id, key, value) VALUES (?, ?, ?)",
                (node_id, key, value),
            )
        await self._conn.commit()

    def _row_to_node(self, row: dict[str, Any]) -> SpecNode:
        return SpecNode(
            id=row["id"],
            spec_ref=row["spec_ref"],
            title=row["title"],
            depth=row["depth"],
            file_path=row["rel_path"],
            anchor=row["anchor"],
            intent=row["intent"],
            status=row["status"],
        )

    def _row_to_detail(self, row: dict[str, Any]) -> SpecNodeDetail:
        return SpecNodeDetail(
            id=row["id"],
            spec_ref=row["spec_ref"],
            title=row["title"],
            depth=row["depth"],
            file_path=row["rel_path"],
            anchor=row["anchor"],
            intent=row["intent"],
            status=row["status"],
            content=row.get("content") or "",
            line_start=row.get("line_start"),
            line_end=row.get("line_end"),
        )

    async def get_tree(self) -> list[SpecNode]:
        rows = await self._all(
            """
SELECT n.*, f.rel_path
FROM nodes n
JOIN files f ON f.id = n.file_id
ORDER BY n.sort_order, n.file_id, n.line_start
"""
        )
        return [self._row_to_node(row) for row in rows]

    async def get_nodes_for_file(self, file_id: int) -> list[SpecNodeDetail]:
        rows = await self._all(
            """
SELECT n.*, f.rel_path
FROM nodes n
JOIN files f ON f.id = n.file_id
WHERE n.file_id = ?
ORDER BY n.line_start, n.sort_order
""",
            (file_id,),
        )
        return [self._row_to_detail(row) for row in rows]

    async def get_node_metadata(self, node_id: str) -> list[tuple[str, str]]:
        rows = await self._all(
            "SELECT key, value FROM node_metadata WHERE node_id = ? ORDER BY id",
            (node_id,),
        )
        return [(row["key"], row["value"]) for row in rows]

    async def get_node(self, node_id: str) -> SpecNodeDetail | None:
        row = await self._one(
            """
SELECT n.*, f.rel_path
FROM nodes n
JOIN files f ON f.id = n.file_id
WHERE n.id = ?
""",
            (node_id,),
        )
        return self._row_to_detail(row) if row is not None else None

    async def get_node_by_ref(self, spec_ref: str) -> SpecNodeDetail | None:
        row = await self._one(
            """
SELECT n.*, f.rel_path
FROM nodes n
JOIN files f ON f.id = n.file_id
WHERE n.spec_ref = ?
""",
            (spec_ref,),
        )
        return self._row_to_detail(row) if row is not None else None

    async def get_children(self, node_id: str) -> list[SpecNode]:
        rows = await self._all(
            """
SELECT n.*, f.rel_path
FROM edges e
JOIN nodes n ON n.id = e.child_id
JOIN files f ON f.id = n.file_id
WHERE e.parent_id = ?
ORDER BY e.sort_order
""",
            (node_id,),
        )
        return [self._row_to_node(row) for row in rows]

    async def get_ancestors(self, node_id: str) -> list[SpecNode]:
        rows = await self._all(
            """
WITH RECURSIVE ancestors(node_id, depth) AS (
    SELECT parent_id, 1 FROM edges WHERE child_id = ?
    UNION ALL
    SELECT e.parent_id, a.depth + 1
    FROM edges e JOIN ancestors a ON e.child_id = a.node_id
)
SELECT n.*, f.rel_path, a.depth AS ad
FROM ancestors a
JOIN nodes n ON n.id = a.node_id
JOIN files f ON f.id = n.file_id
ORDER BY a.depth DESC
""",
            (node_id,),
        )
        return [self._row_to_node(row) for row in rows]

    async def get_siblings(self, node_id: str) -> list[SpecNode]:
        rows = await self._all(
            """
SELECT n.*, f.rel_path
FROM nodes n
JOIN files f ON f.id = n.file_id
WHERE n.id IN (
    SELECT child_id FROM edges WHERE parent_id = (
        SELECT parent_id FROM edges WHERE child_id = ? LIMIT 1
    )
)
ORDER BY n.sort_order
""",
            (node_id,),
        )
        return [self._row_to_node(row) for row in rows]

    async def get_subtree(self, node_id: str) -> list[SpecNode]:
        rows = await self._all(
            """
WITH RECURSIVE tree(id, depth) AS (
    SELECT ?, 0
    UNION ALL
    SELECT e.child_id, tree.depth + 1
    FROM edges e JOIN tree ON e.parent_id = tree.id
)
SELECT n.*, f.rel_path, tree.depth as td
FROM tree
JOIN nodes n ON n.id = tree.id
JOIN files f ON f.id = n.file_id
WHERE tree.depth > 0
ORDER BY tree.depth, n.sort_order
""",
            (node_id,),
        )
        return [self._row_to_node(row) for row in rows]

    async def get_referencing_nodes(self, node_id: str) -> list[SpecNode]:
        rows = await self._all(
            """
SELECT n.*, f.rel_path
FROM node_refs r
JOIN nodes n ON n.id = r.from_node
JOIN files f ON f.id = n.file_id
WHERE r.to_node = ?
ORDER BY n.sort_order
""",
            (node_id,),
        )
        return [self._row_to_node(row) for row in rows]

    async def get_referenced_nodes(self, node_id: str) -> list[SpecNode]:
        rows = await self._all(
            """
SELECT n.*, f.rel_path
FROM node_refs r
JOIN nodes n ON n.id = r.to_node
JOIN files f ON f.id = n.file_id
WHERE r.from_node = ?
ORDER BY n.sort_order
""",
            (node_id,),
        )
        return [self._row_to_node(row) for row in rows]

    async def update_node(
        self,
        node_id: str,
        *,
        spec_ref: str,
        anchor: str,
        title: str,
        intent: str | None,
        status: str | None,
        content: str,
    ) -> None:
        await self._execute(
            """
UPDATE nodes
SET spec_ref = ?, anchor = ?, title = ?, intent = ?, status = ?, content = ?, updated_at = ?
WHERE id = ?
""",
            (spec_ref, anchor, title, intent, status, content, time.time(), node_id),
        )
        await self._conn.commit()

    async def set_tree_coordinates(self, updates: list[tuple[str, int, int]]) -> None:
        for node_id, depth, sort_order in updates:
            await self._execute(
                "UPDATE nodes SET depth = ?, sort_order = ?, updated_at = ? WHERE id = ?",
                (depth, sort_order, time.time(), node_id),
            )
        await self._conn.commit()

    async def create_session(
        self,
        *,
        session_id: str | None = None,
        spec_ref: str | None = None,
        node_id: str | None = None,
        parent_session_id: str | None = None,
        status: str = "active",
        model: str | None = None,
        provider: str | None = None,
    ) -> str:
        now_ts = time.time()
        sid = session_id or str(uuid4())
        await self._execute(
            """
INSERT INTO sessions(id, spec_ref, node_id, parent_session_id, status, model, provider, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
            (sid, spec_ref, node_id, parent_session_id, status, model, provider, now_ts, now_ts),
        )
        await self._conn.commit()
        return sid

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        return await self._one("SELECT * FROM sessions WHERE id = ?", (session_id,))

    async def update_session_status(self, session_id: str, status: str) -> None:
        await self._execute(
            "UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?",
            (status, time.time(), session_id),
        )
        await self._conn.commit()

    async def append_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str | None,
        name: str | None = None,
        tool_call_id: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: float | None = None,
        message_id: str | None = None,
    ) -> str:
        row = await self._one("SELECT COALESCE(MAX(seq), 0) AS seq FROM messages WHERE session_id = ?", (session_id,))
        next_seq = int(row["seq"]) + 1 if row is not None else 1
        mid = message_id or str(uuid4())
        await self._execute(
            """
INSERT INTO messages(id, session_id, role, content, name, tool_call_id, seq, created_at, input_tokens, output_tokens, cost_usd)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
            (
                mid,
                session_id,
                role,
                content,
                name,
                tool_call_id,
                next_seq,
                time.time(),
                input_tokens,
                output_tokens,
                cost_usd,
            ),
        )
        await self._conn.commit()
        return mid

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        return await self._all("SELECT * FROM messages WHERE session_id = ? ORDER BY seq", (session_id,))

    async def record_tool_call(self, *, call_id: str, message_id: str, tool_name: str, arguments: str) -> None:
        await self._execute(
            "INSERT INTO tool_calls(id, message_id, tool_name, arguments, created_at) VALUES (?, ?, ?, ?, ?)",
            (call_id, message_id, tool_name, arguments, time.time()),
        )
        await self._conn.commit()

    async def record_tool_result(
        self,
        *,
        tool_call_id: str,
        output: str | None,
        error: str | None,
        duration_ms: int | None,
    ) -> None:
        await self._execute(
            "INSERT INTO tool_results(tool_call_id, output, error, duration_ms, created_at) VALUES (?, ?, ?, ?, ?)",
            (tool_call_id, output, error, duration_ms, time.time()),
        )
        await self._conn.commit()

    async def record_question(
        self,
        *,
        question_id: str | None = None,
        session_id: str,
        question: str,
        options: str | None = None,
        message_id: str | None = None,
        node_id: str | None = None,
    ) -> str:
        qid = question_id or str(uuid4())
        await self._execute(
            """
INSERT INTO questions(id, session_id, message_id, node_id, question, options, status, created_at)
VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
""",
            (qid, session_id, message_id, node_id, question, options, time.time()),
        )
        await self._conn.commit()
        return qid

    async def record_answer(self, question_id: str, answer: str) -> None:
        await self._execute(
            "UPDATE questions SET answer = ?, status = 'answered', answered_at = ? WHERE id = ?",
            (answer, time.time(), question_id),
        )
        await self._conn.commit()

    async def record_subagent_spawn(self, *, parent_session_id: str, child_session_id: str, purpose: str | None) -> None:
        await self._execute(
            """
INSERT OR IGNORE INTO subagent_spawns(parent_session_id, child_session_id, purpose, created_at)
VALUES (?, ?, ?, ?)
""",
            (parent_session_id, child_session_id, purpose, time.time()),
        )
        await self._conn.commit()

    @staticmethod
    def new_node_id() -> str:
        return str(uuid4())
