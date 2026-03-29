"""SQLite storage for symbol index and semantic reference index."""

from __future__ import annotations

import json
from typing import Any

from .models import SymbolEntry


class SymbolDB:
    """Manages symbols and ref_index tables.

    Operates on an existing database connection (the SpecDB connection).
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def migrate(self) -> None:
        """Create symbols and ref_index tables if they don't exist."""
        await self._conn.executescript(
            """
CREATE TABLE IF NOT EXISTS symbols (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    line_start      INTEGER NOT NULL,
    line_end        INTEGER NOT NULL,
    scope           TEXT NOT NULL,
    parent_symbol   TEXT,
    language        TEXT NOT NULL,
    value_preview   TEXT,
    content_hash    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_path);
CREATE INDEX IF NOT EXISTS idx_symbols_kind ON symbols(kind);

CREATE TABLE IF NOT EXISTS ref_index (
    id              TEXT PRIMARY KEY,
    ref_kind        TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    symbol_path     TEXT,
    spec_node_id    TEXT NOT NULL,
    diagnostic      TEXT NOT NULL DEFAULT 'resolved'
);
CREATE INDEX IF NOT EXISTS idx_ref_by_file ON ref_index(file_path);
CREATE INDEX IF NOT EXISTS idx_ref_by_symbol ON ref_index(symbol_path);
CREATE INDEX IF NOT EXISTS idx_ref_by_node ON ref_index(spec_node_id);
"""
        )
        await self._conn.commit()

    # ── Symbol CRUD ──────────────────────────────────────────────────────

    async def upsert_symbols(self, symbols: list[SymbolEntry]) -> None:
        """Bulk upsert symbols (replace on conflict)."""
        for sym in symbols:
            await self._conn.execute(
                """
INSERT INTO symbols (id, name, kind, file_path, line_start, line_end,
                     scope, parent_symbol, language, value_preview, content_hash)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(id) DO UPDATE SET
    name=excluded.name, kind=excluded.kind, file_path=excluded.file_path,
    line_start=excluded.line_start, line_end=excluded.line_end,
    scope=excluded.scope, parent_symbol=excluded.parent_symbol,
    language=excluded.language, value_preview=excluded.value_preview,
    content_hash=excluded.content_hash
""",
                (
                    sym.id,
                    sym.name,
                    sym.kind,
                    sym.file_path,
                    sym.line_start,
                    sym.line_end,
                    sym.scope,
                    sym.parent_symbol,
                    sym.language,
                    sym.value_preview,
                    sym.content_hash,
                ),
            )
        await self._conn.commit()

    async def delete_symbols_for_file(self, file_path: str) -> None:
        """Remove all symbols from a specific file."""
        await self._conn.execute(
            "DELETE FROM symbols WHERE file_path = ?", (file_path,)
        )
        await self._conn.commit()

    async def search_symbols(
        self,
        query: str,
        *,
        kind: str | None = None,
        scope: str | None = None,
        limit: int = 50,
    ) -> list[SymbolEntry]:
        """Search symbols by name (case-insensitive prefix/substring match)."""
        conditions = ["name LIKE ?"]
        params: list[Any] = [f"%{query}%"]
        if kind:
            conditions.append("kind = ?")
            params.append(kind)
        if scope:
            conditions.append("scope LIKE ?")
            params.append(f"%{scope}%")
        params.append(limit)

        where = " AND ".join(conditions)
        cur = await self._conn.execute(
            f"SELECT * FROM symbols WHERE {where} ORDER BY name LIMIT ?",
            tuple(params),
        )
        rows = await cur.fetchall()
        return [self._row_to_symbol(dict(row)) for row in rows]

    async def get_symbol(
        self, file_path: str, symbol_name: str
    ) -> SymbolEntry | None:
        """Get a specific symbol by file path and name."""
        cur = await self._conn.execute(
            "SELECT * FROM symbols WHERE file_path = ? AND name = ? LIMIT 1",
            (file_path, symbol_name),
        )
        row = await cur.fetchone()
        return self._row_to_symbol(dict(row)) if row else None

    async def get_symbols_in_file(self, file_path: str) -> list[SymbolEntry]:
        """Get all symbols in a file."""
        cur = await self._conn.execute(
            "SELECT * FROM symbols WHERE file_path = ? ORDER BY line_start",
            (file_path,),
        )
        rows = await cur.fetchall()
        return [self._row_to_symbol(dict(row)) for row in rows]

    async def get_symbol_by_id(self, symbol_id: str) -> SymbolEntry | None:
        """Get a symbol by its ID."""
        cur = await self._conn.execute(
            "SELECT * FROM symbols WHERE id = ?", (symbol_id,)
        )
        row = await cur.fetchone()
        return self._row_to_symbol(dict(row)) if row else None

    async def get_symbols_by_name(self, name: str) -> list[SymbolEntry]:
        """Find all symbols with an exact name match (across all files)."""
        cur = await self._conn.execute(
            "SELECT * FROM symbols WHERE name = ? ORDER BY file_path, line_start",
            (name,),
        )
        rows = await cur.fetchall()
        return [self._row_to_symbol(dict(row)) for row in rows]

    # ── Ref Index ────────────────────────────────────────────────────────

    async def upsert_ref(
        self,
        ref_id: str,
        ref_kind: str,
        file_path: str,
        symbol_path: str | None,
        spec_node_id: str,
        diagnostic: str = "resolved",
    ) -> None:
        """Insert or update a reference index entry."""
        await self._conn.execute(
            """
INSERT INTO ref_index (id, ref_kind, file_path, symbol_path, spec_node_id, diagnostic)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(id) DO UPDATE SET
    ref_kind=excluded.ref_kind, file_path=excluded.file_path,
    symbol_path=excluded.symbol_path, spec_node_id=excluded.spec_node_id,
    diagnostic=excluded.diagnostic
""",
            (ref_id, ref_kind, file_path, symbol_path, spec_node_id, diagnostic),
        )
        await self._conn.commit()

    async def delete_refs_for_node(self, spec_node_id: str) -> None:
        """Remove all reference entries for a spec node."""
        await self._conn.execute(
            "DELETE FROM ref_index WHERE spec_node_id = ?", (spec_node_id,)
        )
        await self._conn.commit()

    async def get_refs_for_node(self, spec_node_id: str) -> list[dict[str, Any]]:
        """Get all refs attached to a spec node."""
        cur = await self._conn.execute(
            "SELECT * FROM ref_index WHERE spec_node_id = ? ORDER BY file_path",
            (spec_node_id,),
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def get_backlinks_for_file(
        self, file_path: str, *, symbol_name: str | None = None
    ) -> list[dict[str, Any]]:
        """Find all spec nodes referencing a given file (and optionally symbol)."""
        if symbol_name:
            cur = await self._conn.execute(
                "SELECT * FROM ref_index WHERE file_path = ? AND symbol_path LIKE ?",
                (file_path, f"%{symbol_name}%"),
            )
        else:
            cur = await self._conn.execute(
                "SELECT * FROM ref_index WHERE file_path = ?", (file_path,)
            )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def validate_all_refs(self) -> list[dict[str, Any]]:
        """Return all ref_index entries for validation."""
        cur = await self._conn.execute(
            "SELECT * FROM ref_index ORDER BY spec_node_id, file_path"
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def update_ref_diagnostic(self, ref_id: str, diagnostic: str) -> None:
        """Update the diagnostic status of a ref."""
        await self._conn.execute(
            "UPDATE ref_index SET diagnostic = ? WHERE id = ?",
            (diagnostic, ref_id),
        )
        await self._conn.commit()

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_symbol(row: dict[str, Any]) -> SymbolEntry:
        return SymbolEntry(
            id=row["id"],
            name=row["name"],
            kind=row["kind"],
            file_path=row["file_path"],
            line_start=row["line_start"],
            line_end=row["line_end"],
            scope=row["scope"],
            parent_symbol=row.get("parent_symbol"),
            language=row.get("language", "python"),
            value_preview=row.get("value_preview"),
            content_hash=row.get("content_hash", ""),
        )
