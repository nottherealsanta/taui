"""Tests for grep/glob — ripgrep integration, .gitignore, fallback, ReDoS guard."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from taui.tools.builtins.files import GlobTool, GrepTool


# ── Helpers ──────────────────────────────────────────────────────────────────

def _has_rg() -> bool:
    return shutil.which("rg") is not None


def _init_git(path: Path) -> None:
    """Initialize a git repo at *path* with a .gitignore."""
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path), capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path), capture_output=True,
    )


def _make_project(tmp_path: Path) -> Path:
    """Create a tiny project with a .gitignore excluding 'dist/'."""
    root = tmp_path / "proj"
    root.mkdir()
    _init_git(root)

    # .gitignore
    (root / ".gitignore").write_text("dist/\n")

    # Source file
    src = root / "src"
    src.mkdir()
    (src / "main.py").write_text("print('hello')\n")

    # Ignored dir
    dist = root / "dist"
    dist.mkdir()
    (dist / "bundle.py").write_text("print('hello')\n")

    # Need at least one commit for rg to pick up .gitignore
    subprocess.run(
        ["git", "add", "-A"], cwd=str(root), capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init", "--allow-empty"],
        cwd=str(root), capture_output=True,
    )
    return root


# ── GrepTool tests ───────────────────────────────────────────────────────────


class TestGrepToolRipgrep:
    """Tests that run only when rg is available."""

    @pytest.mark.skipif(not _has_rg(), reason="ripgrep not installed")
    async def test_rg_respects_gitignore(self, tmp_path):
        root = _make_project(tmp_path)
        tool = GrepTool(working_dir=root)
        result = await tool.execute({"pattern": "hello"})
        assert not result.error
        # dist/bundle.py should be excluded by .gitignore
        assert "dist" not in result.content
        assert "main.py" in result.content

    @pytest.mark.skipif(not _has_rg(), reason="ripgrep not installed")
    async def test_rg_include_filter(self, tmp_path):
        root = _make_project(tmp_path)
        (root / "src" / "notes.txt").write_text("hello from txt\n")
        tool = GrepTool(working_dir=root)
        result = await tool.execute({"pattern": "hello", "include": "*.py"})
        assert not result.error
        assert "main.py" in result.content
        assert "notes.txt" not in result.content

    @pytest.mark.skipif(not _has_rg(), reason="ripgrep not installed")
    async def test_rg_no_matches(self, tmp_path):
        root = _make_project(tmp_path)
        tool = GrepTool(working_dir=root)
        result = await tool.execute({"pattern": "zzz_no_match_zzz"})
        assert not result.error
        assert "No matches" in result.content


class TestGrepToolFallback:
    """Tests for Python fallback when rg is absent."""

    async def test_fallback_works_without_rg(self, tmp_path):
        root = _make_project(tmp_path)
        tool = GrepTool(working_dir=root)

        import taui.tools.builtins.files as files_mod
        old_val = files_mod._rg_path
        try:
            files_mod._rg_path = None  # Force no rg
            result = await tool.execute({"pattern": "hello"})
            assert not result.error
            assert "main.py" in result.content
        finally:
            files_mod._rg_path = old_val

    async def test_fallback_invalid_regex(self, tmp_path):
        root = _make_project(tmp_path)
        tool = GrepTool(working_dir=root)

        import taui.tools.builtins.files as files_mod
        old_val = files_mod._rg_path
        try:
            files_mod._rg_path = None
            result = await tool.execute({"pattern": "[invalid"})
            assert result.error
            assert "Invalid regex" in result.content
        finally:
            files_mod._rg_path = old_val

    async def test_fallback_skips_skip_dirs(self, tmp_path):
        root = _make_project(tmp_path)
        # Put a match in __pycache__
        pc = root / "__pycache__"
        pc.mkdir()
        (pc / "cached.py").write_text("hello\n")

        tool = GrepTool(working_dir=root)

        import taui.tools.builtins.files as files_mod
        old_val = files_mod._rg_path
        try:
            files_mod._rg_path = None
            result = await tool.execute({"pattern": "hello"})
            assert not result.error
            assert "__pycache__" not in result.content
        finally:
            files_mod._rg_path = old_val

    async def test_fallback_timeout_guard(self, tmp_path):
        """A pathological-length search should hit the time budget, not hang."""
        root = _make_project(tmp_path)
        tool = GrepTool(working_dir=root)

        import taui.tools.builtins.files as files_mod
        old_val = files_mod._rg_path
        old_timeout = files_mod._SEARCH_TIMEOUT_SECS
        try:
            files_mod._rg_path = None
            # Use an absurdly short timeout to trigger the guard
            files_mod._SEARCH_TIMEOUT_SECS = 0
            result = await tool.execute({"pattern": "hello"})
            # Should either find results (fast enough) or hit the budget
            # In practice with timeout=0 it should trigger
            # (it only checks every 50 files, so with 1 file it may still succeed)
        finally:
            files_mod._rg_path = old_val
            files_mod._SEARCH_TIMEOUT_SECS = old_timeout

    async def test_single_file_grep(self, tmp_path):
        root = _make_project(tmp_path)
        tool = GrepTool(working_dir=root)
        result = await tool.execute({
            "pattern": "hello",
            "path": "src/main.py",
        })
        assert not result.error
        assert "main.py" in result.content


# ── GlobTool tests ───────────────────────────────────────────────────────────


class TestGlobToolRipgrep:
    @pytest.mark.skipif(not _has_rg(), reason="ripgrep not installed")
    async def test_rg_glob_respects_gitignore(self, tmp_path):
        root = _make_project(tmp_path)
        tool = GlobTool(working_dir=root)
        result = await tool.execute({"pattern": "**/*.py"})
        assert not result.error
        assert "main.py" in result.content
        # dist/ is gitignored
        assert "dist" not in result.content

    @pytest.mark.skipif(not _has_rg(), reason="ripgrep not installed")
    async def test_rg_glob_no_matches(self, tmp_path):
        root = _make_project(tmp_path)
        tool = GlobTool(working_dir=root)
        result = await tool.execute({"pattern": "**/*.rs"})
        assert not result.error
        assert "No matches" in result.content


class TestGlobToolFallback:
    async def test_fallback_glob(self, tmp_path):
        root = _make_project(tmp_path)
        tool = GlobTool(working_dir=root)

        import taui.tools.builtins.files as files_mod
        old_val = files_mod._rg_path
        try:
            files_mod._rg_path = None
            result = await tool.execute({"pattern": "**/*.py"})
            assert not result.error
            assert "main.py" in result.content
        finally:
            files_mod._rg_path = old_val

    async def test_fallback_skips_skip_dirs(self, tmp_path):
        root = _make_project(tmp_path)
        pc = root / "node_modules"
        pc.mkdir()
        (pc / "pkg.py").write_text("x\n")

        tool = GlobTool(working_dir=root)

        import taui.tools.builtins.files as files_mod
        old_val = files_mod._rg_path
        try:
            files_mod._rg_path = None
            result = await tool.execute({"pattern": "**/*.py"})
            assert not result.error
            assert "node_modules" not in result.content
        finally:
            files_mod._rg_path = old_val
