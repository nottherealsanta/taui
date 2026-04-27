"""Tests for taui.lsp module."""

from __future__ import annotations

import asyncio
import json

import pytest

from taui.lsp.types import (
    Diagnostic,
    HoverResult,
    Location,
    Position,
    Range,
    SymbolInfo,
)
from taui.lsp.client import LspClient, LspError, _HEADER_SEP
from taui.lsp.manager import LspManager, _DEFAULT_SERVERS


# ── types ──────────────────────────────────────────────────────────────────────


class TestPosition:
    def test_basic(self):
        p = Position(line=5, character=10)
        assert p.line == 5
        assert p.character == 10


class TestRange:
    def test_basic(self):
        r = Range(start=Position(0, 0), end=Position(5, 10))
        assert r.start.line == 0
        assert r.end.character == 10


class TestLocation:
    def test_to_dict(self):
        loc = Location(
            uri="file:///src/foo.py",
            range=Range(start=Position(4, 2), end=Position(4, 8)),
        )
        d = loc.to_dict()
        assert d["file"] == "/src/foo.py"
        assert d["line"] == 5  # 1-indexed
        assert d["character"] == 3

    def test_non_file_uri(self):
        loc = Location(
            uri="untitled:Untitled-1",
            range=Range(start=Position(0, 0), end=Position(0, 5)),
        )
        d = loc.to_dict()
        assert d["file"] == "untitled:Untitled-1"


class TestDiagnostic:
    def test_to_dict(self):
        diag = Diagnostic(
            range=Range(start=Position(9, 0), end=Position(9, 5)),
            message="Undefined variable 'x'",
            severity=1,
            source="pyflakes",
        )
        d = diag.to_dict()
        assert d["severity"] == "error"
        assert d["line"] == 10
        assert d["source"] == "pyflakes"

    def test_pretty(self):
        diag = Diagnostic(
            range=Range(start=Position(0, 3), end=Position(0, 8)),
            message="unused import",
            severity=2,
        )
        s = diag.pretty()
        assert "WARN" in s
        assert "unused import" in s

    def test_severity_levels(self):
        for sev, label in [(1, "error"), (2, "warning"), (3, "info"), (4, "hint")]:
            d = Diagnostic(
                range=Range(start=Position(0, 0), end=Position(0, 0)),
                message="x",
                severity=sev,
            )
            assert d.to_dict()["severity"] == label


class TestSymbolInfo:
    def test_to_dict(self):
        sym = SymbolInfo(
            name="MyClass",
            kind=5,  # Class
            location=Location(
                uri="file:///a.py",
                range=Range(start=Position(1, 0), end=Position(10, 0)),
            ),
            container_name="module",
        )
        d = sym.to_dict()
        assert d["name"] == "MyClass"
        assert d["container"] == "module"

    def test_no_container(self):
        sym = SymbolInfo(
            name="func",
            kind=12,
            location=Location(
                uri="file:///b.py",
                range=Range(start=Position(0, 0), end=Position(2, 0)),
            ),
        )
        d = sym.to_dict()
        assert "container" not in d


class TestHoverResult:
    def test_to_dict(self):
        h = HoverResult(contents="def foo(x: int) -> str: ...")
        d = h.to_dict()
        assert d["contents"].startswith("def foo")
        assert "line" not in d

    def test_with_range(self):
        h = HoverResult(
            contents="help",
            range=Range(start=Position(3, 0), end=Position(3, 5)),
        )
        d = h.to_dict()
        assert d["line"] == 4


# ── client ─────────────────────────────────────────────────────────────────────


class TestLspClient:
    def test_init(self):
        c = LspClient(["pylsp"])
        assert c._cmd == ["pylsp"]
        assert not c._initialized
        assert not c.alive

    def test_send_format(self):
        """_send writes Content-Length header + JSON body."""
        c = LspClient(["pylsp"])

        # Mock subprocess
        class FakeStdin:
            def __init__(self):
                self.data = b""
            def write(self, b: bytes):
                self.data += b

        class FakeProc:
            stdin = FakeStdin()
            returncode = None

        c._proc = FakeProc()
        msg = {"jsonrpc": "2.0", "method": "test", "params": {}}
        c._send(msg)

        raw = c._proc.stdin.data
        assert raw.startswith(b"Content-Length:")
        header, body = raw.split(_HEADER_SEP, 1)
        parsed = json.loads(body)
        assert parsed["method"] == "test"

    def test_handle_message_response(self):
        c = LspClient(["pylsp"])
        loop = asyncio.new_event_loop()
        fut = loop.create_future()
        c._pending[1] = fut
        c._handle_message({"id": 1, "result": {"ok": True}})
        assert fut.result() == {"ok": True}
        loop.close()

    def test_handle_message_error(self):
        c = LspClient(["pylsp"])
        loop = asyncio.new_event_loop()
        fut = loop.create_future()
        c._pending[2] = fut
        c._handle_message({"id": 2, "error": {"message": "boom"}})
        with pytest.raises(LspError, match="boom"):
            fut.result()
        loop.close()

    def test_handle_message_unknown_id_ignored(self):
        c = LspClient(["pylsp"])
        # Should not raise
        c._handle_message({"id": 999, "result": None})


# ── manager ────────────────────────────────────────────────────────────────────


class TestLspManager:
    def test_init(self, tmp_path):
        m = LspManager(tmp_path)
        assert m._root == tmp_path
        assert m._root_uri == tmp_path.as_uri()
        assert m._clients == {}

    def test_configure_server(self, tmp_path):
        m = LspManager(tmp_path)
        m.configure_server("rust", ["custom-ra", "--stdio"])
        assert m._custom_servers["rust"] == ["custom-ra", "--stdio"]

    async def test_get_client_unknown_language(self, tmp_path):
        m = LspManager(tmp_path)
        with pytest.raises(ValueError, match="No LSP server configured"):
            await m._get_client("brainfuck")

    async def test_stop_all_empty(self, tmp_path):
        m = LspManager(tmp_path)
        await m.stop_all()  # no-op, no error

    def test_default_servers(self):
        assert "python" in _DEFAULT_SERVERS
        assert "typescript" in _DEFAULT_SERVERS
        assert "go" in _DEFAULT_SERVERS
