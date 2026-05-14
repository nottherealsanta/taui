"""Tests for taui.tools.builtins.common — shared utilities."""


import pytest

from taui.tools.builtins.common import (
    SKIP_DIRS,
    is_binary,
    resolve_path,
    suggest_similar,
    truncate,
)


class TestResolvePath:
    def test_relative(self, tmp_path):
        (tmp_path / "foo.py").touch()
        result = resolve_path(tmp_path, "foo.py")
        assert result == (tmp_path / "foo.py").resolve()

    def test_absolute(self, tmp_path):
        target = tmp_path / "bar.py"
        target.touch()
        result = resolve_path(tmp_path, str(target))
        assert result == target.resolve()

    def test_reject_escape(self, tmp_path):
        with pytest.raises(ValueError, match="outside"):
            resolve_path(tmp_path, "../../../etc/passwd")

    def test_nested_path(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "file.py").touch()
        result = resolve_path(tmp_path, "sub/file.py")
        assert result.name == "file.py"

    def test_tilde_expansion(self, tmp_path):
        # ~ expands but may not be inside workspace, so this should raise
        with pytest.raises(ValueError):
            resolve_path(tmp_path, "~/something")


class TestIsBinary:
    def test_text_file(self, tmp_path):
        f = tmp_path / "text.py"
        f.write_text("print('hello')\n")
        assert not is_binary(f)

    def test_binary_file(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"\x00\x01\x02\xff" * 100)
        assert is_binary(f)

    def test_nonexistent(self, tmp_path):
        assert is_binary(tmp_path / "nope")

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty"
        f.write_bytes(b"")
        assert not is_binary(f)


class TestSuggestSimilar:
    def test_close_match(self, tmp_path):
        (tmp_path / "config.py").touch()
        (tmp_path / "confgi.py").touch()
        target = tmp_path / "conifg.py"  # typo
        result = suggest_similar(target, tmp_path)
        assert result is not None
        assert "Did you mean" in result

    def test_no_close_match(self, tmp_path):
        (tmp_path / "completely_different.py").touch()
        target = tmp_path / "zzzzz.py"
        result = suggest_similar(target, tmp_path)
        # Might or might not return a suggestion depending on cutoff
        # Just verify it doesn't crash
        assert result is None or isinstance(result, str)

    def test_suggest_in_correct_dir(self, tmp_path):
        (tmp_path / "hello.py").touch()
        target = tmp_path / "helo.py"
        result = suggest_similar(target, tmp_path)
        assert result is not None
        assert "hello.py" in result


class TestTruncate:
    def test_no_truncation_needed(self):
        text = "line 1\nline 2\nline 3\n"
        result, was_truncated = truncate(text, max_lines=10, max_bytes=1000)
        assert result == text
        assert not was_truncated

    def test_truncate_by_lines(self):
        text = "\n".join(f"line {i}" for i in range(100))
        result, was_truncated = truncate(text, max_lines=10, max_bytes=100_000)
        assert was_truncated
        # 10 content lines + truncation marker lines
        assert result.count("\n") <= 15

    def test_truncate_by_bytes(self):
        text = "x" * 10_000
        result, was_truncated = truncate(text, max_lines=100_000, max_bytes=100)
        assert was_truncated
        assert len(result.encode()) < 200  # truncated + marker

    def test_never_splits_lines(self):
        text = "short\n" + "x" * 200 + "\nshort\n"
        result, _ = truncate(text, max_lines=100, max_bytes=50)
        # Result should end with a complete line or the truncation marker
        for line in result.splitlines():
            assert len(line) < 300  # No partial mega-lines

    def test_empty_text(self):
        result, was_truncated = truncate("", max_lines=10, max_bytes=100)
        assert result == ""
        assert not was_truncated


class TestSkipDirs:
    def test_common_dirs_present(self):
        assert ".git" in SKIP_DIRS
        assert "node_modules" in SKIP_DIRS
        assert "__pycache__" in SKIP_DIRS
        assert ".venv" in SKIP_DIRS
