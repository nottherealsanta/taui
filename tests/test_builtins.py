"""Tests for taui.tools.builtins — file ops, bash, and registration."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from taui.tools.builtins import register_builtins
from taui.tools.builtins.bash import BashTool
from taui.tools.builtins.files import GlobTool, GrepTool, ReadTool, WriteTool
from taui.tools.builtins.session_name import SessionNameTool
from taui.tools.registry import ToolRegistry

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a workspace with some test files."""
    (tmp_path / "hello.py").write_text("print('hello')\nprint('world')\n")
    (tmp_path / "data.txt").write_text("line one\nline two\nline three\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.py").write_text("# nested\nimport os\n")
    (tmp_path / "empty").mkdir()
    return tmp_path


# ═══ ReadTool ═════════════════════════════════════════════════════════════════


class TestReadTool:
    async def test_read_file(self, workspace: Path):
        tool = ReadTool(working_dir=workspace)
        result = await tool.execute({"path": "hello.py"})
        assert result.error is False
        assert "print('hello')" in result.content
        assert "1|" in result.content

    async def test_read_file_with_offset(self, workspace: Path):
        tool = ReadTool(working_dir=workspace)
        result = await tool.execute({"path": "data.txt", "offset": 2})
        assert "line two" in result.content
        assert "line one" not in result.content

    async def test_read_file_with_limit(self, workspace: Path):
        tool = ReadTool(working_dir=workspace)
        result = await tool.execute({"path": "data.txt", "limit": 1})
        assert "line one" in result.content
        assert "line two" not in result.content
        assert "more lines" in result.content

    async def test_read_directory(self, workspace: Path):
        tool = ReadTool(working_dir=workspace)
        result = await tool.execute({"path": "."})
        assert result.error is False
        assert "hello.py" in result.content
        assert "sub/" in result.content  # Dirs have trailing /

    async def test_read_empty_dir(self, workspace: Path):
        tool = ReadTool(working_dir=workspace)
        result = await tool.execute({"path": "empty"})
        assert "empty directory" in result.content

    async def test_read_missing_file(self, workspace: Path):
        tool = ReadTool(working_dir=workspace)
        result = await tool.execute({"path": "nope.txt"})
        assert result.error is True
        assert "not found" in result.content.lower()

    async def test_read_binary_file(self, workspace: Path):
        (workspace / "image.bin").write_bytes(b"\x00\x01\x02\x03")
        tool = ReadTool(working_dir=workspace)
        result = await tool.execute({"path": "image.bin"})
        assert result.error is True
        assert "binary" in result.content.lower()

    async def test_read_rejects_escape(self, workspace: Path):
        tool = ReadTool(working_dir=workspace)
        result = await tool.execute({"path": "../../../etc/passwd"})
        assert result.error is True
        assert "outside" in result.content.lower()


# ═══ WriteTool ════════════════════════════════════════════════════════════════


class TestWriteTool:
    async def test_write_new_file(self, workspace: Path):
        tool = WriteTool(working_dir=workspace)
        result = await tool.execute({"path": "new.txt", "content": "hello\nworld\n"})
        assert result.error is False
        assert (workspace / "new.txt").read_text() == "hello\nworld\n"

    async def test_write_creates_parent_dirs(self, workspace: Path):
        tool = WriteTool(working_dir=workspace)
        result = await tool.execute({
            "path": "deep/nested/dir/file.txt",
            "content": "deep content",
        })
        assert result.error is False
        assert (workspace / "deep/nested/dir/file.txt").read_text() == "deep content"

    async def test_write_overwrites_existing(self, workspace: Path):
        tool = WriteTool(working_dir=workspace)
        result = await tool.execute({"path": "hello.py", "content": "new content\n"})
        assert result.error is False
        assert (workspace / "hello.py").read_text() == "new content\n"

    async def test_write_rejects_escape(self, workspace: Path):
        tool = WriteTool(working_dir=workspace)
        result = await tool.execute({
            "path": "../../escape.txt",
            "content": "bad",
        })
        assert result.error is True
        assert "outside" in result.content.lower()

    async def test_write_reports_line_count(self, workspace: Path):
        tool = WriteTool(working_dir=workspace)
        result = await tool.execute({"path": "count.txt", "content": "a\nb\nc\n"})
        assert result.error is False
        assert "3 lines" in result.content


# ═══ GlobTool ═════════════════════════════════════════════════════════════════


class TestGlobTool:
    async def test_glob_py_files(self, workspace: Path):
        tool = GlobTool(working_dir=workspace)
        result = await tool.execute({"pattern": "**/*.py"})
        assert result.error is False
        assert "hello.py" in result.content
        assert "nested.py" in result.content

    async def test_glob_no_matches(self, workspace: Path):
        tool = GlobTool(working_dir=workspace)
        result = await tool.execute({"pattern": "*.rs"})
        assert result.error is False
        assert "No matches" in result.content

    async def test_glob_specific_dir(self, workspace: Path):
        tool = GlobTool(working_dir=workspace)
        result = await tool.execute({"pattern": "*.py", "path": "sub"})
        assert "nested.py" in result.content

    async def test_glob_rejects_escape(self, workspace: Path):
        tool = GlobTool(working_dir=workspace)
        result = await tool.execute({"pattern": "*", "path": "../../"})
        assert result.error is True


# ═══ GrepTool ═════════════════════════════════════════════════════════════════


class TestGrepTool:
    async def test_grep_simple(self, workspace: Path):
        tool = GrepTool(working_dir=workspace)
        result = await tool.execute({"pattern": "hello"})
        assert result.error is False
        assert "hello.py" in result.content
        assert result.metadata["match_count"] >= 1

    async def test_grep_regex(self, workspace: Path):
        tool = GrepTool(working_dir=workspace)
        result = await tool.execute({"pattern": "line (one|two)"})
        assert "line one" in result.content
        assert "line two" in result.content

    async def test_grep_include_filter(self, workspace: Path):
        tool = GrepTool(working_dir=workspace)
        result = await tool.execute({"pattern": "print", "include": "*.py"})
        assert "hello.py" in result.content

    async def test_grep_no_matches(self, workspace: Path):
        tool = GrepTool(working_dir=workspace)
        result = await tool.execute({"pattern": "zzzznotfound"})
        assert result.error is False
        assert "No matches" in result.content

    async def test_grep_invalid_regex(self, workspace: Path):
        tool = GrepTool(working_dir=workspace)
        result = await tool.execute({"pattern": "[invalid"})
        assert result.error is True
        assert "regex" in result.content.lower()

    async def test_grep_rejects_escape(self, workspace: Path):
        tool = GrepTool(working_dir=workspace)
        result = await tool.execute({"pattern": ".", "path": "../../"})
        assert result.error is True


# ═══ BashTool ═════════════════════════════════════════════════════════════════


class TestBashTool:
    async def test_simple_command(self, workspace: Path):
        tool = BashTool(working_dir=workspace)
        result = await tool.execute({"command": "echo hello"})
        assert result.error is False
        assert "hello" in result.content

    async def test_exit_code_nonzero(self, workspace: Path):
        tool = BashTool(working_dir=workspace)
        result = await tool.execute({"command": "exit 1"})
        assert result.error is True
        assert "Exit code: 1" in result.content

    async def test_working_directory(self, workspace: Path):
        tool = BashTool(working_dir=workspace)
        result = await tool.execute({"command": "pwd"})
        assert str(workspace) in result.content

    async def test_timeout(self, workspace: Path):
        tool = BashTool(working_dir=workspace)
        result = await tool.execute({"command": "sleep 100", "timeout": 1})
        assert result.error is True
        assert "timed out" in result.content.lower()

    async def test_empty_command(self, workspace: Path):
        tool = BashTool(working_dir=workspace)
        result = await tool.execute({"command": ""})
        assert result.error is True
        assert "empty" in result.content.lower()

    async def test_multiline_output(self, workspace: Path):
        tool = BashTool(working_dir=workspace)
        result = await tool.execute({"command": "ls"})
        assert result.error is False
        assert "hello.py" in result.content

    async def test_env_filtering(self, workspace: Path):
        """Sensitive env vars should not leak through."""
        tool = BashTool(working_dir=workspace)
        # Set a fake secret, run bash, check it's not visible
        os.environ["TAUI_SECRET_TEST"] = "supersecret"
        try:
            result = await tool.execute({"command": "env"})
            assert "TAUI_SECRET_TEST" not in result.content
        finally:
            del os.environ["TAUI_SECRET_TEST"]


# ═══ register_builtins ═══════════════════════════════════════════════════════


class TestRegisterBuiltins:
    def test_registers_all(self):
        reg = ToolRegistry()
        register_builtins(reg)
        assert "read" in reg
        assert "write" in reg
        assert "glob" in reg
        assert "grep" in reg
        assert "bash" in reg
        assert "git" in reg
        assert "question" in reg
        assert "memory" in reg
        assert "sub_agent" in reg
        assert "skills" in reg
        assert "mcp" in reg
        assert "session_name" in reg
        assert "peek" in reg
        assert "lsp" in reg
        assert "task_create" in reg
        assert "task_stop" in reg
        assert len(reg) == 26

    def test_schemas_exported(self):
        reg = ToolRegistry()
        register_builtins(reg)
        schemas = reg.schemas()
        assert len(schemas) == 26
        names = {s["function"]["name"] for s in schemas}
        assert names == {
            "read", "write", "edit", "glob", "grep", "bash", "git",
            "question", "memory", "skills", "sub_agent", "mcp",
            "session_name", "peek", "task", "webfetch", "apply_patch",
            "lsp", "repo_overview", "notebook_edit",
            "task_create", "task_get", "task_list",
            "task_output", "task_stop", "task_update",
        }


class TestSessionNameTool:
    async def test_rejects_when_unwired(self):
        tool = SessionNameTool()
        r = await tool.execute({"name": "foo"})
        assert r.error
        assert "not wired" in r.content

    async def test_saves_name_via_callback(self):
        tool = SessionNameTool()
        saved: list[str] = []

        async def set_name(name: str) -> None:
            saved.append(name)

        tool._set_name = set_name
        r = await tool.execute({"name": "fix /sessions crash"})
        assert not r.error
        assert saved == ["fix /sessions crash"]
        assert r.metadata["name"] == "fix /sessions crash"

    async def test_rejects_empty(self):
        tool = SessionNameTool()
        tool._set_name = lambda n: None  # type: ignore[assignment]
        r = await tool.execute({"name": "  "})
        assert r.error

    async def test_truncates_long_name(self):
        tool = SessionNameTool()
        saved: list[str] = []

        async def set_name(name: str) -> None:
            saved.append(name)

        tool._set_name = set_name
        r = await tool.execute({"name": "x" * 200})
        assert not r.error
        assert len(saved[0]) == 80
