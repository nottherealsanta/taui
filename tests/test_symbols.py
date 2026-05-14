"""Tests for taui.symbols module."""

from __future__ import annotations

from pathlib import Path

from taui.symbols.indexer import SymbolIndexer
from taui.symbols.models import SymbolEntry

# ── models ─────────────────────────────────────────────────────────────────────


class TestSymbolEntry:
    def test_to_dict(self):
        s = SymbolEntry(
            id="foo.py::module::bar",
            name="bar",
            kind="function",
            file_path="foo.py",
            line_start=1,
            line_end=5,
            scope="module",
        )
        d = s.to_dict()
        assert d["name"] == "bar"
        assert d["kind"] == "function"
        assert d["line_start"] == 1
        assert d["language"] == "python"

    def test_roundtrip(self):
        s = SymbolEntry(
            id="a.py::module::X",
            name="X",
            kind="constant",
            file_path="a.py",
            line_start=3,
            line_end=3,
            scope="module",
            value_preview="42",
        )
        d = s.to_dict()
        s2 = SymbolEntry.from_dict(d)
        assert s2.name == s.name
        assert s2.kind == s.kind
        assert s2.value_preview == "42"

    def test_from_dict_defaults(self):
        d = {
            "id": "x",
            "name": "x",
            "kind": "variable",
            "file_path": "x.py",
            "line_start": 1,
            "line_end": 1,
            "scope": "module",
        }
        s = SymbolEntry.from_dict(d)
        assert s.language == "python"
        assert s.parent_symbol is None
        assert s.content_hash == ""


# ── indexer ────────────────────────────────────────────────────────────────────


class TestSymbolIndexer:
    def _write(self, tmp_path: Path, name: str, content: str) -> Path:
        p = tmp_path / name
        p.write_text(content)
        return p

    def test_empty_project(self, tmp_path):
        idx = SymbolIndexer(tmp_path)
        assert idx.scan_project() == []

    def test_index_function(self, tmp_path):
        self._write(tmp_path, "mod.py", "def hello():\n    pass\n")
        idx = SymbolIndexer(tmp_path)
        syms = idx.scan_project()
        names = [s.name for s in syms]
        assert "hello" in names
        s = next(s for s in syms if s.name == "hello")
        assert s.kind == "function"
        assert s.scope == "module"
        assert s.line_start == 1

    def test_index_class_and_method(self, tmp_path):
        code = "class Foo:\n    def bar(self):\n        pass\n"
        self._write(tmp_path, "c.py", code)
        idx = SymbolIndexer(tmp_path)
        syms = idx.scan_project()
        names = {s.name: s for s in syms}
        assert "Foo" in names
        assert names["Foo"].kind == "class"
        assert "bar" in names
        assert names["bar"].kind == "method"
        assert names["bar"].parent_symbol == "Foo"

    def test_index_constant(self, tmp_path):
        self._write(tmp_path, "const.py", "MAX_SIZE = 1024\n")
        idx = SymbolIndexer(tmp_path)
        syms = idx.scan_project()
        s = next(s for s in syms if s.name == "MAX_SIZE")
        assert s.kind == "constant"
        assert s.value_preview == "1024"

    def test_index_variable(self, tmp_path):
        self._write(tmp_path, "v.py", "x = 10\n")
        idx = SymbolIndexer(tmp_path)
        syms = idx.scan_project()
        s = next(s for s in syms if s.name == "x")
        assert s.kind == "variable"

    def test_index_annotated_assign(self, tmp_path):
        self._write(tmp_path, "ann.py", "name: str = 'hello'\n")
        idx = SymbolIndexer(tmp_path)
        syms = idx.scan_project()
        s = next(s for s in syms if s.name == "name")
        assert s.kind == "variable"
        assert s.value_preview == "'hello'"

    def test_index_async_function(self, tmp_path):
        self._write(tmp_path, "af.py", "async def fetch():\n    pass\n")
        idx = SymbolIndexer(tmp_path)
        syms = idx.scan_project()
        s = next(s for s in syms if s.name == "fetch")
        assert s.kind == "function"

    def test_skips_non_python(self, tmp_path):
        (tmp_path / "data.json").write_text("{}")
        idx = SymbolIndexer(tmp_path)
        assert idx.scan_project() == []

    def test_skips_syntax_errors(self, tmp_path):
        self._write(tmp_path, "bad.py", "def (\n")
        idx = SymbolIndexer(tmp_path)
        assert idx.scan_project() == []

    def test_skips_venv(self, tmp_path):
        venv = tmp_path / ".venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "mod.py").write_text("def hidden(): pass\n")
        self._write(tmp_path, "top.py", "def visible(): pass\n")
        idx = SymbolIndexer(tmp_path)
        syms = idx.scan_project()
        names = [s.name for s in syms]
        assert "visible" in names
        assert "hidden" not in names

    def test_index_file_returns_relative_path(self, tmp_path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        self._write(pkg, "mod.py", "X = 1\n")
        idx = SymbolIndexer(tmp_path)
        syms = idx.index_file(pkg / "mod.py")
        assert syms[0].file_path == "pkg/mod.py"

    def test_content_hash_changes(self, tmp_path):
        p = self._write(tmp_path, "h.py", "x = 1\n")
        idx = SymbolIndexer(tmp_path)
        h1 = idx.index_file(p)[0].content_hash
        p.write_text("x = 2\n")
        h2 = idx.index_file(p)[0].content_hash
        assert h1 != h2

    def test_nested_class(self, tmp_path):
        code = "class Outer:\n    class Inner:\n        pass\n"
        self._write(tmp_path, "nested.py", code)
        idx = SymbolIndexer(tmp_path)
        syms = idx.scan_project()
        inner = next(s for s in syms if s.name == "Inner")
        assert inner.parent_symbol == "Outer"

    def test_preview_truncated(self, tmp_path):
        long_val = "'" + "a" * 200 + "'"
        self._write(tmp_path, "long.py", f"X = {long_val}\n")
        idx = SymbolIndexer(tmp_path)
        syms = idx.scan_project()
        s = next(s for s in syms if s.name == "X")
        assert len(s.value_preview) <= 120

    def test_multiple_files(self, tmp_path):
        self._write(tmp_path, "a.py", "def alpha(): pass\n")
        self._write(tmp_path, "b.py", "def beta(): pass\n")
        idx = SymbolIndexer(tmp_path)
        syms = idx.scan_project()
        names = {s.name for s in syms}
        assert names == {"alpha", "beta"}

    def test_symbol_id_unique(self, tmp_path):
        code = "x = 1\ny = 2\n"
        self._write(tmp_path, "u.py", code)
        idx = SymbolIndexer(tmp_path)
        syms = idx.scan_project()
        ids = [s.id for s in syms]
        assert len(ids) == len(set(ids))
