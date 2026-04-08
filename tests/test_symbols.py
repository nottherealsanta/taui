"""Tests for the symbol indexer, resolver, and DB (Phase 1 literate programming)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from textwrap import dedent

import pytest

from taui.symbols.indexer import SymbolIndexer
from taui.symbols.models import SemanticRef, ResolvedRef, SymbolEntry
from taui.symbols.db import SymbolDB
from taui.symbols.resolver import SymbolResolver


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a small temporary project with files in various languages."""
    # Python file
    py_file = tmp_path / "config.py"
    py_file.write_text(dedent("""\
        MAX_RETRIES = 3
        DEFAULT_TIMEOUT = 30.0
        APP_NAME = "my_app"
        DEBUG = True

        class Settings:
            def __init__(self):
                self.host = "localhost"

            def get_port(self):
                return 8080

        def compute_value():
            return MAX_RETRIES * 2
    """))

    # TypeScript file
    ts_dir = tmp_path / "src"
    ts_dir.mkdir()
    ts_file = ts_dir / "theme.ts"
    ts_file.write_text(dedent("""\
        export const PRIMARY_COLOR = "#3b82f6";
        export const FONT_SIZE = 16;

        export interface ThemeTokens {
            background: string;
            foreground: string;
        }

        export function applyTheme(tokens: ThemeTokens): void {
            document.body.style.background = tokens.background;
        }

        const helper = (x: number) => x * 2;
    """))

    # CSS file
    css_file = ts_dir / "app.css"
    css_file.write_text(dedent("""\
        :root {
            --color-bg: #1a1a2e;
            --color-fg: #eaeaea;
            --spacing-md: 16px;
        }
    """))

    # Rust file
    rs_file = tmp_path / "main.rs"
    rs_file.write_text(dedent("""\
        const MAX_SIZE: usize = 1024;

        struct AppConfig {
            name: String,
            port: u16,
        }

        impl AppConfig {
            fn new() -> Self {
                Self {
                    name: String::from("test"),
                    port: 8080,
                }
            }
        }

        fn main() {
            println!("Hello, world!");
        }
    """))

    return tmp_path


@pytest.fixture
def indexer(tmp_project: Path) -> SymbolIndexer:
    return SymbolIndexer(tmp_project)


# ── Indexer Tests ─────────────────────────────────────────────────────────────


class TestSymbolIndexer:
    def test_scan_project(self, indexer: SymbolIndexer) -> None:
        symbols = indexer.scan_project()
        assert len(symbols) > 0
        names = {s.name for s in symbols}
        assert "MAX_RETRIES" in names
        assert "Settings" in names
        assert "compute_value" in names

    def test_python_functions(self, indexer: SymbolIndexer) -> None:
        symbols = indexer.scan_project()
        funcs = [s for s in symbols if s.kind == "function" and s.language == "python"]
        func_names = {s.name for s in funcs}
        assert "compute_value" in func_names
        assert "get_port" in func_names
        assert "__init__" in func_names

    def test_python_classes(self, indexer: SymbolIndexer) -> None:
        symbols = indexer.scan_project()
        classes = [s for s in symbols if s.kind == "class" and s.language == "python"]
        assert any(s.name == "Settings" for s in classes)

    def test_python_variables(self, indexer: SymbolIndexer) -> None:
        symbols = indexer.scan_project()
        constants = [
            s for s in symbols if s.kind == "constant" and s.language == "python"
        ]
        const_names = {s.name for s in constants}
        assert "MAX_RETRIES" in const_names
        assert "DEFAULT_TIMEOUT" in const_names
        assert "APP_NAME" in const_names
        assert "DEBUG" in const_names

    def test_python_value_preview(self, indexer: SymbolIndexer) -> None:
        symbols = indexer.scan_project()
        retries = next(s for s in symbols if s.name == "MAX_RETRIES")
        assert retries.value_preview == "3"

    def test_typescript_functions(self, indexer: SymbolIndexer) -> None:
        symbols = indexer.scan_project()
        ts_funcs = [
            s for s in symbols if s.kind == "function" and s.language == "typescript"
        ]
        func_names = {s.name for s in ts_funcs}
        assert "applyTheme" in func_names

    def test_typescript_types(self, indexer: SymbolIndexer) -> None:
        symbols = indexer.scan_project()
        types = [s for s in symbols if s.kind == "type" and s.language == "typescript"]
        type_names = {s.name for s in types}
        assert "ThemeTokens" in type_names

    def test_typescript_variables(self, indexer: SymbolIndexer) -> None:
        symbols = indexer.scan_project()
        ts_vars = [
            s for s in symbols
            if s.language == "typescript" and s.kind in ("variable", "constant")
        ]
        names = {s.name for s in ts_vars}
        assert "PRIMARY_COLOR" in names or "FONT_SIZE" in names

    def test_css_custom_properties(self, indexer: SymbolIndexer) -> None:
        symbols = indexer.scan_project()
        css = [s for s in symbols if s.kind == "css_property"]
        css_names = {s.name for s in css}
        assert "--color-bg" in css_names
        assert "--color-fg" in css_names
        assert "--spacing-md" in css_names

    def test_css_value_preview(self, indexer: SymbolIndexer) -> None:
        symbols = indexer.scan_project()
        bg = next(s for s in symbols if s.name == "--color-bg")
        assert bg.value_preview is not None
        assert "#1a1a2e" in bg.value_preview

    def test_rust_functions(self, indexer: SymbolIndexer) -> None:
        symbols = indexer.scan_project()
        rs_funcs = [
            s for s in symbols if s.kind == "function" and s.language == "rust"
        ]
        func_names = {s.name for s in rs_funcs}
        assert "main" in func_names
        assert "new" in func_names

    def test_rust_structs(self, indexer: SymbolIndexer) -> None:
        symbols = indexer.scan_project()
        rs_structs = [s for s in symbols if s.kind == "class" and s.language == "rust"]
        assert any(s.name == "AppConfig" for s in rs_structs)

    def test_rust_constants(self, indexer: SymbolIndexer) -> None:
        symbols = indexer.scan_project()
        rs_consts = [
            s for s in symbols if s.kind == "constant" and s.language == "rust"
        ]
        assert any(s.name == "MAX_SIZE" for s in rs_consts)

    def test_index_single_file(self, indexer: SymbolIndexer) -> None:
        config_path = indexer.project_root / "config.py"
        symbols = indexer.index_file(config_path)
        assert len(symbols) > 0
        names = {s.name for s in symbols}
        assert "MAX_RETRIES" in names

    def test_symbol_scopes(self, indexer: SymbolIndexer) -> None:
        symbols = indexer.scan_project()
        init = next(s for s in symbols if s.name == "__init__" and s.language == "python")
        assert init.scope == "class:Settings"
        assert init.parent_symbol == "Settings"


# ── Symbol DB Tests ──────────────────────────────────────────────────────────


class TestSymbolDB:
    @pytest.fixture
    def event_loop(self):
        loop = asyncio.new_event_loop()
        yield loop
        loop.close()

    @pytest.fixture
    def db(self, event_loop):
        """Create an in-memory SQLite DB with symbol tables."""
        import sqlite3

        class FakeCursor:
            def __init__(self, rows=None, lastrowid=None):
                self._rows = rows or []
                self.lastrowid = lastrowid

            async def fetchone(self):
                return self._rows[0] if self._rows else None

            async def fetchall(self):
                return self._rows

        class FakeConn:
            def __init__(self):
                self._conn = sqlite3.connect(":memory:")
                self._conn.row_factory = sqlite3.Row

            async def execute(self, sql, params=()):
                cur = self._conn.execute(sql, params)
                rows = None
                first = sql.lstrip().upper()
                if first.startswith("SELECT") or first.startswith("WITH") or first.startswith("PRAGMA"):
                    rows = cur.fetchall()
                return FakeCursor(rows=rows, lastrowid=cur.lastrowid)

            async def executescript(self, script):
                self._conn.executescript(script)

            async def commit(self):
                self._conn.commit()

        conn = FakeConn()
        sdb = SymbolDB(conn)
        event_loop.run_until_complete(sdb.migrate())
        return sdb

    def test_upsert_and_search(self, db, event_loop):
        sym = SymbolEntry(
            id="test1",
            name="MAX_RETRIES",
            kind="constant",
            file_path="config.py",
            line_start=1,
            line_end=1,
            scope="module",
            language="python",
            value_preview="3",
            content_hash="abc123",
        )
        event_loop.run_until_complete(db.upsert_symbols([sym]))
        results = event_loop.run_until_complete(db.search_symbols("MAX"))
        assert len(results) == 1
        assert results[0].name == "MAX_RETRIES"
        assert results[0].value_preview == "3"

    def test_get_symbol(self, db, event_loop):
        sym = SymbolEntry(
            id="test2",
            name="Settings",
            kind="class",
            file_path="config.py",
            line_start=5,
            line_end=10,
            scope="module",
            language="python",
            content_hash="abc123",
        )
        event_loop.run_until_complete(db.upsert_symbols([sym]))
        result = event_loop.run_until_complete(db.get_symbol("config.py", "Settings"))
        assert result is not None
        assert result.kind == "class"

    def test_delete_symbols_for_file(self, db, event_loop):
        syms = [
            SymbolEntry(
                id="del1", name="a", kind="variable", file_path="a.py",
                line_start=1, line_end=1, scope="module", language="python",
                content_hash="x",
            ),
            SymbolEntry(
                id="del2", name="b", kind="variable", file_path="a.py",
                line_start=2, line_end=2, scope="module", language="python",
                content_hash="x",
            ),
        ]
        event_loop.run_until_complete(db.upsert_symbols(syms))
        event_loop.run_until_complete(db.delete_symbols_for_file("a.py"))
        results = event_loop.run_until_complete(db.get_symbols_in_file("a.py"))
        assert len(results) == 0

    def test_ref_index_crud(self, db, event_loop):
        event_loop.run_until_complete(
            db.upsert_ref("r1", "variable_ref", "config.py", "MAX_RETRIES", "node-1")
        )
        refs = event_loop.run_until_complete(db.get_refs_for_node("node-1"))
        assert len(refs) == 1
        assert refs[0]["ref_kind"] == "variable_ref"

        backlinks = event_loop.run_until_complete(
            db.get_backlinks_for_file("config.py")
        )
        assert len(backlinks) == 1

        event_loop.run_until_complete(db.delete_refs_for_node("node-1"))
        refs = event_loop.run_until_complete(db.get_refs_for_node("node-1"))
        assert len(refs) == 0


# ── Resolver Tests ───────────────────────────────────────────────────────────


class TestSymbolResolver:
    @pytest.fixture
    def populated_db_and_resolver(self, tmp_project):
        """Create a populated symbol DB with resolver."""
        import sqlite3

        class FakeCursor:
            def __init__(self, rows=None, lastrowid=None):
                self._rows = rows or []
                self.lastrowid = lastrowid

            async def fetchone(self):
                return self._rows[0] if self._rows else None

            async def fetchall(self):
                return self._rows

        class FakeConn:
            def __init__(self):
                self._conn = sqlite3.connect(":memory:")
                self._conn.row_factory = sqlite3.Row

            async def execute(self, sql, params=()):
                cur = self._conn.execute(sql, params)
                rows = None
                first = sql.lstrip().upper()
                if first.startswith("SELECT") or first.startswith("WITH") or first.startswith("PRAGMA"):
                    rows = cur.fetchall()
                return FakeCursor(rows=rows, lastrowid=cur.lastrowid)

            async def executescript(self, script):
                self._conn.executescript(script)

            async def commit(self):
                self._conn.commit()

        loop = asyncio.new_event_loop()
        conn = FakeConn()
        sdb = SymbolDB(conn)
        loop.run_until_complete(sdb.migrate())

        # Index the project
        indexer = SymbolIndexer(tmp_project)
        symbols = indexer.scan_project()
        loop.run_until_complete(sdb.upsert_symbols(symbols))

        resolver = SymbolResolver(tmp_project, sdb)
        yield loop, sdb, resolver
        loop.close()

    def test_resolve_file_ref(self, populated_db_and_resolver):
        loop, sdb, resolver = populated_db_and_resolver
        ref = SemanticRef(file_path="config.py", ref_kind="file_ref")
        resolved = loop.run_until_complete(resolver.resolve(ref))
        assert resolved.diagnostic == "resolved"
        assert resolved.line_start == 1
        assert "MAX_RETRIES" in resolved.preview_snippet

    def test_resolve_file_ref_missing(self, populated_db_and_resolver):
        loop, sdb, resolver = populated_db_and_resolver
        ref = SemanticRef(file_path="nonexistent.py", ref_kind="file_ref")
        resolved = loop.run_until_complete(resolver.resolve(ref))
        assert resolved.diagnostic == "unresolved"

    def test_resolve_line_ref(self, populated_db_and_resolver):
        loop, sdb, resolver = populated_db_and_resolver
        ref = SemanticRef(
            file_path="config.py", ref_kind="line_ref",
            line_start=1, line_end=3,
        )
        resolved = loop.run_until_complete(resolver.resolve(ref))
        assert resolved.diagnostic == "resolved"
        assert "MAX_RETRIES" in resolved.preview_snippet

    def test_resolve_symbol_ref(self, populated_db_and_resolver):
        loop, sdb, resolver = populated_db_and_resolver
        ref = SemanticRef(
            file_path="config.py",
            symbol_path="compute_value",
            ref_kind="symbol_ref",
        )
        resolved = loop.run_until_complete(resolver.resolve(ref))
        assert resolved.diagnostic in ("resolved", "stale")
        assert resolved.symbol_kind == "function"

    def test_resolve_variable_ref_writable(self, populated_db_and_resolver):
        loop, sdb, resolver = populated_db_and_resolver
        ref = SemanticRef(
            file_path="config.py",
            symbol_path="MAX_RETRIES",
            ref_kind="variable_ref",
        )
        resolved = loop.run_until_complete(resolver.resolve(ref))
        assert resolved.diagnostic in ("resolved", "stale")
        assert resolved.writable is True
        assert resolved.edit_strategy == "replace_literal"

    def test_resolve_symbol_not_found(self, populated_db_and_resolver):
        loop, sdb, resolver = populated_db_and_resolver
        ref = SemanticRef(
            file_path="config.py",
            symbol_path="nonexistent_func",
            ref_kind="symbol_ref",
        )
        resolved = loop.run_until_complete(resolver.resolve(ref))
        assert resolved.diagnostic == "unresolved"

    def test_resolve_css_property(self, populated_db_and_resolver):
        loop, sdb, resolver = populated_db_and_resolver
        ref = SemanticRef(
            file_path="src/app.css",
            symbol_path="--color-bg",
            ref_kind="variable_ref",
        )
        resolved = loop.run_until_complete(resolver.resolve(ref))
        assert resolved.diagnostic in ("resolved", "stale")
        assert resolved.writable is True
        assert resolved.edit_strategy == "replace_property"

    def test_update_value(self, populated_db_and_resolver, tmp_project):
        loop, sdb, resolver = populated_db_and_resolver
        result = loop.run_until_complete(
            resolver.update_value("config.py", "MAX_RETRIES", "5")
        )
        assert result["success"] is True
        assert result["old_value"] == "3"
        assert result["new_value"] == "5"

        # Verify file was actually modified
        content = (tmp_project / "config.py").read_text()
        assert "MAX_RETRIES = 5" in content

    def test_update_value_read_only(self, populated_db_and_resolver):
        loop, sdb, resolver = populated_db_and_resolver
        result = loop.run_until_complete(
            resolver.update_value("config.py", "compute_value", "99")
        )
        assert result["success"] is False


# ── SemanticRef Model Tests ──────────────────────────────────────────────────


class TestSemanticRefModel:
    def test_roundtrip(self):
        ref = SemanticRef(
            file_path="config.py",
            symbol_path="MAX_RETRIES",
            ref_kind="variable_ref",
            language="python",
            edit_policy="replace_literal",
        )
        d = ref.to_dict()
        ref2 = SemanticRef.from_dict(d)
        assert ref2.file_path == ref.file_path
        assert ref2.symbol_path == ref.symbol_path
        assert ref2.ref_kind == ref.ref_kind
        assert ref2.language == ref.language
        assert ref2.edit_policy == ref.edit_policy

    def test_symbol_entry_roundtrip(self):
        entry = SymbolEntry(
            id="abc123",
            name="Settings",
            kind="class",
            file_path="config.py",
            line_start=5,
            line_end=10,
            scope="module",
            language="python",
            content_hash="xyz",
        )
        d = entry.to_dict()
        entry2 = SymbolEntry.from_dict(d)
        assert entry2.name == entry.name
        assert entry2.kind == entry.kind


# ── Integration: RPC handler tests ──────────────────────────────────────────


class TestRefsRPC:
    """Integration tests for the refs/* RPC methods through MethodHandlers."""

    @pytest.fixture
    def handlers_with_project(self, tmp_project):
        """Set up MethodHandlers pointing at the tmp project."""
        from taui.server.handlers import MethodHandlers

        specs_dir = tmp_project / "specs"
        specs_dir.mkdir(exist_ok=True)
        main_md = specs_dir / "_main.md"
        main_md.write_text(dedent("""\
            - Project root
                - Config module
                    {{code_ref: `config.py`}}
        """))

        handlers = MethodHandlers(workspace=tmp_project, specs_path=specs_dir)
        return handlers

    @pytest.fixture
    def loop(self):
        loop = asyncio.new_event_loop()
        yield loop
        loop.close()

    def test_refs_reindex(self, handlers_with_project, loop):
        handlers = handlers_with_project
        loop.run_until_complete(handlers.specs.ensure_initialized())
        result = loop.run_until_complete(
            handlers._handle_refs_reindex({})
        )
        assert result["symbols"] > 0
        assert result["indexed_files"] > 0

    def test_refs_search(self, handlers_with_project, loop):
        handlers = handlers_with_project
        loop.run_until_complete(handlers.specs.ensure_initialized())
        loop.run_until_complete(handlers._handle_refs_reindex({}))

        result = loop.run_until_complete(
            handlers._handle_refs_search({"query": "MAX_RETRIES"})
        )
        assert len(result["symbols"]) >= 1
        assert result["symbols"][0]["name"] == "MAX_RETRIES"

    def test_refs_resolve(self, handlers_with_project, loop):
        handlers = handlers_with_project
        loop.run_until_complete(handlers.specs.ensure_initialized())
        loop.run_until_complete(handlers._handle_refs_reindex({}))

        result = loop.run_until_complete(
            handlers._handle_refs_resolve({
                "ref": {
                    "file_path": "config.py",
                    "symbol_path": "MAX_RETRIES",
                    "ref_kind": "variable_ref",
                }
            })
        )
        assert result["diagnostic"] in ("resolved", "stale")
        assert result["writable"] is True

    def test_refs_get_definition(self, handlers_with_project, loop):
        handlers = handlers_with_project
        loop.run_until_complete(handlers.specs.ensure_initialized())
        loop.run_until_complete(handlers._handle_refs_reindex({}))

        result = loop.run_until_complete(
            handlers._handle_refs_get_definition({
                "file_path": "config.py",
                "symbol_name": "Settings",
            })
        )
        assert result["symbol"] is not None
        assert result["symbol"]["kind"] == "class"
        assert "class Settings" in result["source_text"]

    def test_refs_update_value(self, handlers_with_project, loop, tmp_project):
        handlers = handlers_with_project
        loop.run_until_complete(handlers.specs.ensure_initialized())
        loop.run_until_complete(handlers._handle_refs_reindex({}))

        result = loop.run_until_complete(
            handlers._handle_refs_update_value({
                "file_path": "config.py",
                "symbol_name": "MAX_RETRIES",
                "new_value": "10",
            })
        )
        assert result["success"] is True
        content = (tmp_project / "config.py").read_text()
        assert "MAX_RETRIES = 10" in content

    def test_refs_reindex_single_file(self, handlers_with_project, loop):
        handlers = handlers_with_project
        loop.run_until_complete(handlers.specs.ensure_initialized())

        result = loop.run_until_complete(
            handlers._handle_refs_reindex({"file_path": "config.py"})
        )
        assert result["indexed_files"] == 1
        assert result["symbols"] > 0
