from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import time
from typing import Any
from uuid import uuid4

from .models import SpecFile, SpecNode, SpecNodeDetail

try:
    import aiosqlite as _aiosqlite
except ModuleNotFoundError:  # pragma: no cover - fallback for local dev envs
    _aiosqlite = None


class _SQLiteRow(dict[str, Any]):
    def __getattr__(self, key: str) -> Any:
        return self[key]


class _FallbackCursor:
    def __init__(
        self, rows: list[sqlite3.Row] | None = None, lastrowid: int | None = None
    ) -> None:
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
            if (
                first.startswith("SELECT")
                or first.startswith("WITH")
                or first.startswith("PRAGMA")
            ):
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
    depth: int
    heading_level: int | None
    line_start: int | None
    line_end: int | None
    markdown: str
    sort_order: int
    status: str | None = None
    code_refs: str | None = None
    verification: str | None = None
    collapsed: int = 0


class SpecDB:
    def __init__(
        self,
        workspace: Path,
        *,
        db_path: Path | None = None,
        snapshot_interval_sec: float = 30.0,
        persist_snapshot: bool = True,
    ) -> None:
        self.workspace = workspace
        self.db_path = db_path or self._default_db_path(workspace)
        self._persist_snapshot = persist_snapshot
        self._conn: Any | None = None
        self._conn_lock = asyncio.Lock()
        self._persist_lock = asyncio.Lock()
        self._snapshot_interval_sec = snapshot_interval_sec
        self._snapshot_task: asyncio.Task[None] | None = None

    @staticmethod
    def _default_db_path(workspace: Path) -> Path:
        return workspace / "tangles" / ".taui.db"

    async def connect(self) -> None:
        async with self._conn_lock:
            if self._conn is not None:
                return
            if self._persist_snapshot:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
            if _aiosqlite is not None:
                conn = await _aiosqlite.connect(":memory:")
                conn.row_factory = _aiosqlite.Row
                self._conn = conn
            else:
                self._conn = _FallbackConnection(":memory:")
            if self._persist_snapshot:
                await self._load_snapshot_from_disk()
            await self._migrate()
            if self._persist_snapshot:
                self._start_snapshot_loop()

    async def close(self) -> None:
        if self._snapshot_task is not None:
            self._snapshot_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._snapshot_task
            self._snapshot_task = None
        if self._conn is None:
            return
        if self._persist_snapshot:
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
        if self._conn is None or not self._persist_snapshot:
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
    mtime_ns INTEGER NOT NULL,
    format TEXT NOT NULL DEFAULT 'legacy'
);

CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    spec_ref TEXT NOT NULL UNIQUE,
    anchor TEXT NOT NULL,
    depth INTEGER NOT NULL,
    heading_level INTEGER,
    line_start INTEGER,
    line_end INTEGER,
    markdown TEXT NOT NULL DEFAULT '',
    status TEXT,
    code_refs TEXT,
    verification TEXT,
    collapsed INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_nodes_file_id ON nodes(file_id);
CREATE INDEX IF NOT EXISTS idx_nodes_depth ON nodes(depth);

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
    to_node TEXT REFERENCES nodes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'depends_on',
    UNIQUE(from_node, to_node, kind)
);

CREATE INDEX IF NOT EXISTS idx_node_refs_to ON node_refs(to_node);

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

-- ── Agent infrastructure (Phase 2) ──────────────────────────────────────────
-- Agent tables have been moved to AgentHistoryDB (taui/tangle/agent_db.py)
-- for on-disk WAL-mode persistence.  This comment block is kept so that
-- existing on-disk snapshots (which may still contain these tables) continue
-- to load without errors -- the CREATE TABLE IF NOT EXISTS statements are
-- idempotent and harmless.

-- ── Tangle v2 tables ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tangle_files (
    id INTEGER PRIMARY KEY,
    rel_path TEXT UNIQUE NOT NULL,
    content_hash TEXT NOT NULL,
    mtime_ns INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    last_updated TEXT NOT NULL DEFAULT '',
    last_seen REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tangle_nodes (
    id TEXT PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES tangle_files(id) ON DELETE CASCADE,
    heading TEXT NOT NULL,
    depth INTEGER NOT NULL,
    anchor TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    line_start INTEGER,
    line_end INTEGER
);

CREATE INDEX IF NOT EXISTS idx_tangle_nodes_file ON tangle_nodes(file_id);

CREATE TABLE IF NOT EXISTS tangle_refs (
    id INTEGER PRIMARY KEY,
    node_id TEXT NOT NULL REFERENCES tangle_nodes(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    target TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT '',
    line_in_tangle INTEGER
);

CREATE INDEX IF NOT EXISTS idx_tangle_refs_node ON tangle_refs(node_id);

CREATE TABLE IF NOT EXISTS tangle_links (
    id INTEGER PRIMARY KEY,
    source_path TEXT NOT NULL,
    target_path TEXT NOT NULL,
    link_type TEXT NOT NULL DEFAULT 'markdown_link'
);

CREATE INDEX IF NOT EXISTS idx_tangle_links_source ON tangle_links(source_path);

CREATE INDEX IF NOT EXISTS idx_tangle_links_target ON tangle_links(target_path);
"""
        )
        node_columns = {
            str(row["name"]) for row in await self._all("PRAGMA table_info(nodes)")
        }
        if "markdown" not in node_columns:
            await self._execute(
                "ALTER TABLE nodes ADD COLUMN markdown TEXT NOT NULL DEFAULT ''"
            )
            await self._execute(
                """
UPDATE nodes
SET markdown = CASE
    WHEN TRIM(COALESCE(title, '')) = '' THEN COALESCE(content, '')
    WHEN TRIM(COALESCE(content, '')) = '' THEN COALESCE(title, '')
    ELSE title || char(10) || content
END
"""
            )
        if "status" not in node_columns:
            await self._execute("ALTER TABLE nodes ADD COLUMN status TEXT")
        if "code_refs" not in node_columns:
            await self._execute("ALTER TABLE nodes ADD COLUMN code_refs TEXT")
        if "verification" not in node_columns:
            await self._execute("ALTER TABLE nodes ADD COLUMN verification TEXT")
        if "collapsed" not in node_columns:
            await self._execute(
                "ALTER TABLE nodes ADD COLUMN collapsed INTEGER NOT NULL DEFAULT 0"
            )
        if "agent_id" not in node_columns:
            await self._execute("ALTER TABLE nodes ADD COLUMN agent_id TEXT")

        file_columns = {
            str(row["name"]) for row in await self._all("PRAGMA table_info(files)")
        }
        if "format" not in file_columns:
            await self._execute(
                "ALTER TABLE files ADD COLUMN format TEXT NOT NULL DEFAULT 'legacy'"
            )

        ref_columns = {
            str(row["name"]) for row in await self._all("PRAGMA table_info(node_refs)")
        }
        if "kind" not in ref_columns:
            await self._execute(
                "ALTER TABLE node_refs ADD COLUMN kind TEXT NOT NULL DEFAULT 'depends_on'"
            )

        metadata_exists = await self._one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='node_metadata'"
        )
        if metadata_exists is not None:
            await self._execute("DROP TABLE IF EXISTS node_metadata")

        # ── Symbol index tables (Phase 1 literate programming) ───────────
        from taui.symbols.db import SymbolDB

        symbol_db = SymbolDB(self._conn)
        await symbol_db.migrate()

        await self._conn.commit()

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

    async def upsert_file(
        self,
        rel_path: str,
        content_hash: str,
        mtime_ns: int,
        now_ts: float,
        format: str = "legacy",
    ) -> SpecFile:
        await self._execute(
            """
INSERT INTO files(rel_path, content_hash, last_seen, mtime_ns, format)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(rel_path) DO UPDATE SET
    content_hash=excluded.content_hash,
    last_seen=excluded.last_seen,
    mtime_ns=excluded.mtime_ns,
    format=excluded.format
""",
            (rel_path, content_hash, now_ts, mtime_ns, format),
        )
        await self._conn.commit()
        row = await self._one(
            "SELECT id, rel_path, content_hash, last_seen, mtime_ns, format FROM files WHERE rel_path = ?",
            (rel_path,),
        )
        assert row is not None
        return SpecFile(**row)

    async def update_file_tracking(
        self, file_id: int, *, content_hash: str, mtime_ns: int, last_seen: float
    ) -> None:
        await self._execute(
            "UPDATE files SET content_hash = ?, mtime_ns = ?, last_seen = ? WHERE id = ?",
            (content_hash, mtime_ns, last_seen, file_id),
        )
        await self._conn.commit()

    async def get_file(self, rel_path: str) -> SpecFile | None:
        row = await self._one(
            "SELECT id, rel_path, content_hash, last_seen, mtime_ns, format FROM files WHERE rel_path = ?",
            (rel_path,),
        )
        return SpecFile(**row) if row is not None else None

    async def get_file_by_id(self, file_id: int) -> SpecFile | None:
        row = await self._one(
            "SELECT id, rel_path, content_hash, last_seen, mtime_ns, format FROM files WHERE id = ?",
            (file_id,),
        )
        return SpecFile(**row) if row is not None else None

    async def list_files(self) -> list[SpecFile]:
        rows = await self._all(
            "SELECT id, rel_path, content_hash, last_seen, mtime_ns, format FROM files ORDER BY rel_path"
        )
        return [SpecFile(**row) for row in rows]

    async def upsert_tangle_file(
        self,
        rel_path: str,
        content_hash: str,
        mtime_ns: int,
        title: str,
        last_updated: str,
        now_ts: float,
    ) -> int:
        await self._execute(
            """
INSERT INTO tangle_files(rel_path, content_hash, mtime_ns, title, last_updated, last_seen)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(rel_path) DO UPDATE SET
    content_hash=excluded.content_hash,
    mtime_ns=excluded.mtime_ns,
    title=excluded.title,
    last_updated=excluded.last_updated,
    last_seen=excluded.last_seen
""",
            (rel_path, content_hash, mtime_ns, title, last_updated, now_ts),
        )
        row = await self._one(
            "SELECT id FROM tangle_files WHERE rel_path = ?",
            (rel_path,),
        )
        assert row is not None
        return int(row["id"])

    async def replace_tangle_nodes(
        self,
        *,
        file_id: int,
        nodes: list[dict[str, Any]],
        refs: list[dict[str, Any]],
        links: list[dict[str, Any]],
    ) -> None:
        await self._execute("DELETE FROM tangle_nodes WHERE file_id = ?", (file_id,))
        for node in nodes:
            await self._execute(
                """
INSERT INTO tangle_nodes(id, file_id, heading, depth, anchor, body, line_start, line_end)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
""",
                (
                    node["id"],
                    file_id,
                    node["heading"],
                    node["depth"],
                    node["anchor"],
                    node["body"],
                    node["line_start"],
                    node["line_end"],
                ),
            )

        await self._execute(
            "DELETE FROM tangle_refs WHERE node_id NOT IN (SELECT id FROM tangle_nodes)"
        )
        for ref in refs:
            await self._execute(
                """
INSERT INTO tangle_refs(node_id, file_path, target, context, line_in_tangle)
VALUES (?, ?, ?, ?, ?)
""",
                (
                    ref["node_id"],
                    ref["file_path"],
                    ref["target"],
                    ref["context"],
                    ref["line_in_tangle"],
                ),
            )

        await self._execute(
            "DELETE FROM tangle_links WHERE source_path = (SELECT rel_path FROM tangle_files WHERE id = ?)",
            (file_id,),
        )
        for link in links:
            await self._execute(
                "INSERT INTO tangle_links(source_path, target_path, link_type) VALUES (?, ?, ?)",
                (link["source_path"], link["target_path"], link["link_type"]),
            )
        await self._conn.commit()

    async def delete_missing_tangle_files(self, rel_paths: set[str]) -> None:
        if rel_paths:
            placeholders = ",".join("?" for _ in rel_paths)
            await self._execute(
                f"DELETE FROM tangle_files WHERE rel_path NOT IN ({placeholders})",
                tuple(sorted(rel_paths)),
            )
        else:
            await self._execute("DELETE FROM tangle_files")
        await self._conn.commit()

    async def get_tangle_tree(self) -> list[dict[str, Any]]:
        return await self._all(
            """
SELECT n.id, f.rel_path AS file_path, n.depth, n.anchor, n.heading, n.body,
       n.line_start, n.line_end,
       (f.rel_path || '#' || n.anchor) AS spec_ref
FROM tangle_nodes n
JOIN tangle_files f ON f.id = n.file_id
ORDER BY f.rel_path, n.line_start
"""
        )

    async def delete_missing_files(self, rel_paths: set[str]) -> None:
        if rel_paths:
            placeholders = ",".join("?" for _ in rel_paths)
            await self._execute(
                f"DELETE FROM files WHERE rel_path NOT IN ({placeholders})",
                tuple(sorted(rel_paths)),
            )
        else:
            await self._execute("DELETE FROM files")
        await self._conn.commit()

    async def list_node_ids_by_file(self, file_id: int) -> dict[str, str]:
        rows = await self._all(
            "SELECT id, anchor FROM nodes WHERE file_id = ?", (file_id,)
        )
        return {row["anchor"]: row["id"] for row in rows}

    async def replace_nodes_for_file(
        self, file_id: int, nodes: list[NodeUpsert]
    ) -> None:
        now_ts = time.time()
        await self._execute("DELETE FROM nodes WHERE file_id = ?", (file_id,))
        for node in nodes:
            await self._execute(
                """
INSERT INTO nodes(
    id, file_id, spec_ref, anchor, depth, heading_level,
    line_start, line_end, markdown, status, code_refs, verification, collapsed,
    sort_order, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                (
                    node.id,
                    file_id,
                    node.spec_ref,
                    node.anchor,
                    node.depth,
                    node.heading_level,
                    node.line_start,
                    node.line_end,
                    node.markdown,
                    node.status,
                    node.code_refs,
                    node.verification,
                    node.collapsed,
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

    async def replace_node_refs(self, refs: list[tuple[str, str, str]]) -> None:
        await self._execute("DELETE FROM node_refs")
        for from_node, to_node, kind in refs:
            await self._execute(
                "INSERT OR IGNORE INTO node_refs(from_node, to_node, kind) VALUES (?, ?, ?)",
                (from_node, to_node, kind),
            )
        await self._conn.commit()

    def _load_json_list(self, raw: Any) -> list[str]:
        if raw in (None, ""):
            return []
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return []
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        return []

    def _row_to_node(self, row: dict[str, Any]) -> SpecNode:
        return SpecNode(
            id=row["id"],
            spec_ref=row["spec_ref"],
            depth=row["depth"],
            file_path=row["rel_path"],
            anchor=row["anchor"],
            markdown=row.get("markdown") or "",
            status=row.get("status"),
            code_refs=self._load_json_list(row.get("code_refs")),
            verification=row.get("verification"),
            collapsed=bool(row.get("collapsed") or 0),
        )

    def _row_to_detail(self, row: dict[str, Any]) -> SpecNodeDetail:
        return SpecNodeDetail(
            id=row["id"],
            spec_ref=row["spec_ref"],
            depth=row["depth"],
            file_path=row["rel_path"],
            anchor=row["anchor"],
            markdown=row.get("markdown") or "",
            status=row.get("status"),
            code_refs=self._load_json_list(row.get("code_refs")),
            verification=row.get("verification"),
            collapsed=bool(row.get("collapsed") or 0),
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

    async def get_depends_on(self, node_id: str) -> list[SpecNode]:
        rows = await self._all(
            """
SELECT n.*, f.rel_path
FROM node_refs r
JOIN nodes n ON n.id = r.to_node
JOIN files f ON f.id = n.file_id
WHERE r.from_node = ? AND r.kind = 'depends_on'
ORDER BY n.sort_order
""",
            (node_id,),
        )
        return [self._row_to_node(row) for row in rows]

    async def get_related_to(self, node_id: str) -> list[SpecNode]:
        rows = await self._all(
            """
SELECT n.*, f.rel_path
FROM node_refs r
JOIN nodes n ON n.id = CASE WHEN r.from_node = ? THEN r.to_node ELSE r.from_node END
JOIN files f ON f.id = n.file_id
WHERE (r.from_node = ? OR r.to_node = ?) AND r.kind = 'related_to'
ORDER BY n.sort_order
""",
            (node_id, node_id, node_id),
        )
        return [self._row_to_node(row) for row in rows]

    async def get_cross_file_children(self, node_id: str) -> list[SpecNode]:
        """Return direct children of node_id that live in a different file."""
        rows = await self._all(
            """
SELECT n.*, f.rel_path
FROM edges e
JOIN nodes n ON n.id = e.child_id
JOIN files f ON f.id = n.file_id
WHERE e.parent_id = ?
  AND n.file_id != (SELECT file_id FROM nodes WHERE id = ?)
ORDER BY e.sort_order
""",
            (node_id, node_id),
        )
        return [self._row_to_node(row) for row in rows]

    async def update_node(
        self,
        node_id: str,
        *,
        spec_ref: str,
        anchor: str,
        markdown: str,
    ) -> None:
        await self._execute(
            """
UPDATE nodes
SET spec_ref = ?, anchor = ?, markdown = ?, updated_at = ?
WHERE id = ?
""",
            (spec_ref, anchor, markdown, time.time(), node_id),
        )
        await self._conn.commit()

    async def set_node_collapsed(self, node_id: str, collapsed: bool) -> None:
        await self._execute(
            "UPDATE nodes SET collapsed = ?, updated_at = ? WHERE id = ?",
            (1 if collapsed else 0, time.time(), node_id),
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
            (
                sid,
                spec_ref,
                node_id,
                parent_session_id,
                status,
                model,
                provider,
                now_ts,
                now_ts,
            ),
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
        row = await self._one(
            "SELECT COALESCE(MAX(seq), 0) AS seq FROM messages WHERE session_id = ?",
            (session_id,),
        )
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
        return await self._all(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY seq", (session_id,)
        )

    async def record_tool_call(
        self, *, call_id: str, message_id: str, tool_name: str, arguments: str
    ) -> None:
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

    async def record_subagent_spawn(
        self, *, parent_session_id: str, child_session_id: str, purpose: str | None
    ) -> None:
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


# Backward-compat alias for incremental migration
TangleDB = SpecDB
