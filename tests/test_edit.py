"""Tests for the edit tool — fuzzy matching, multi-edit, edge cases."""

import pytest
from pathlib import Path

from taui.tools.builtins.edit import EditTool, find_match


# ── find_match unit tests ─────────────────────────────────────────────────────


class TestFindMatch:
    def test_exact_match(self):
        content = "hello world\nfoo bar\nbaz"
        result = find_match(content, "foo bar")
        assert result is not None
        pos, strategy = result
        assert strategy == "exact"
        assert content[pos : pos + 7] == "foo bar"

    def test_no_match(self):
        assert find_match("hello world", "not here") is None

    def test_multiple_exact_returns_none(self):
        content = "foo\nfoo\nfoo"
        assert find_match(content, "foo") is None

    def test_unicode_normalization(self):
        # Smart quotes → straight quotes
        content = "print('hello')\n"
        search = "print(\u2018hello\u2019)"
        result = find_match(content, search)
        assert result is not None
        _, strategy = result
        assert strategy == "unicode_normalized"

    def test_whitespace_normalization(self):
        content = "def foo():  \n    pass\n"
        search = "def foo():\n    pass\n"
        result = find_match(content, search)
        assert result is not None

    def test_smart_double_quotes(self):
        content = 'x = "hello"\n'
        search = "x = \u201chello\u201d"
        result = find_match(content, search)
        assert result is not None


# ── EditTool integration tests ────────────────────────────────────────────────


@pytest.fixture
def working_dir(tmp_path):
    return tmp_path


@pytest.fixture
def edit_tool(working_dir):
    return EditTool(working_dir=working_dir)


@pytest.fixture
def sample_file(working_dir):
    f = working_dir / "sample.py"
    f.write_text(
        "def greet(name):\n"
        '    return f"Hello, {name}!"\n'
        "\n"
        "def add(a, b):\n"
        "    return a + b\n"
    )
    return f


class TestEditTool:
    async def test_basic_edit(self, edit_tool, sample_file):
        result = await edit_tool.execute(
            {
                "path": "sample.py",
                "edits": [
                    {
                        "old_text": '    return f"Hello, {name}!"',
                        "new_text": '    return f"Hi, {name}!"',
                    }
                ],
            }
        )
        assert not result.error
        assert 'Hi, {name}!' in sample_file.read_text()

    async def test_multi_edit(self, edit_tool, sample_file):
        result = await edit_tool.execute(
            {
                "path": "sample.py",
                "edits": [
                    {
                        "old_text": "def greet(name):",
                        "new_text": "def greet(name: str) -> str:",
                    },
                    {
                        "old_text": "def add(a, b):",
                        "new_text": "def add(a: int, b: int) -> int:",
                    },
                ],
            }
        )
        assert not result.error
        content = sample_file.read_text()
        assert "def greet(name: str) -> str:" in content
        assert "def add(a: int, b: int) -> int:" in content

    async def test_not_found(self, edit_tool, sample_file):
        result = await edit_tool.execute(
            {
                "path": "sample.py",
                "edits": [
                    {"old_text": "this text does not exist", "new_text": "x"},
                ],
            }
        )
        assert result.error
        assert "not found" in result.content.lower()

    async def test_ambiguous_match(self, edit_tool, working_dir):
        f = working_dir / "dup.py"
        f.write_text("x = 1\nx = 1\n")
        result = await edit_tool.execute(
            {
                "path": "dup.py",
                "edits": [{"old_text": "x = 1", "new_text": "x = 2"}],
            }
        )
        assert result.error
        assert "2 locations" in result.content

    async def test_empty_old_text(self, edit_tool, sample_file):
        result = await edit_tool.execute(
            {
                "path": "sample.py",
                "edits": [{"old_text": "", "new_text": "x"}],
            }
        )
        assert result.error
        assert "empty" in result.content.lower()

    async def test_missing_file(self, edit_tool):
        result = await edit_tool.execute(
            {
                "path": "nonexistent.py",
                "edits": [{"old_text": "x", "new_text": "y"}],
            }
        )
        assert result.error
        assert "Not a file" in result.content

    async def test_path_outside_workspace(self, edit_tool):
        result = await edit_tool.execute(
            {
                "path": "../../../etc/passwd",
                "edits": [{"old_text": "x", "new_text": "y"}],
            }
        )
        assert result.error
        assert "outside" in result.content.lower()

    async def test_delete_text(self, edit_tool, sample_file):
        """new_text can be empty to delete."""
        result = await edit_tool.execute(
            {
                "path": "sample.py",
                "edits": [
                    {
                        "old_text": "\ndef add(a, b):\n    return a + b\n",
                        "new_text": "\n",
                    }
                ],
            }
        )
        assert not result.error
        assert "add" not in sample_file.read_text()

    async def test_diff_in_output(self, edit_tool, sample_file):
        result = await edit_tool.execute(
            {
                "path": "sample.py",
                "edits": [
                    {"old_text": "def greet(name):", "new_text": "def greet(n):"},
                ],
            }
        )
        assert not result.error
        assert "---" in result.content  # Unified diff header
        assert "+++" in result.content

    async def test_metadata(self, edit_tool, sample_file):
        result = await edit_tool.execute(
            {
                "path": "sample.py",
                "edits": [
                    {"old_text": "def greet(name):", "new_text": "def greet(n):"},
                ],
            }
        )
        assert result.metadata["edits_applied"] == 1
        assert "exact" in result.metadata["strategies"]

    async def test_overlapping_edits_rejected(self, edit_tool, working_dir):
        f = working_dir / "overlap.py"
        f.write_text("abcdefgh\n")
        result = await edit_tool.execute(
            {
                "path": "overlap.py",
                "edits": [
                    {"old_text": "abcdef", "new_text": "ABCDEF"},
                    {"old_text": "cdefgh", "new_text": "CDEFGH"},
                ],
            }
        )
        assert result.error
        assert "overlap" in result.content.lower()

    async def test_unicode_fuzzy_edit(self, edit_tool, working_dir):
        f = working_dir / "quotes.py"
        f.write_text("x = 'hello'\n")
        result = await edit_tool.execute(
            {
                "path": "quotes.py",
                "edits": [
                    {"old_text": "x = \u2018hello\u2019", "new_text": "x = 'world'"},
                ],
            }
        )
        assert not result.error
        assert "world" in f.read_text()

    async def test_edits_as_json_string(self, edit_tool, sample_file):
        """LLMs sometimes send edits as a JSON string instead of array."""
        import json

        edits_json = json.dumps(
            [{"old_text": "def greet(name):", "new_text": "def greet(n):"}]
        )
        result = await edit_tool.execute(
            {"path": "sample.py", "edits": edits_json}
        )
        assert not result.error
        assert "def greet(n):" in sample_file.read_text()

    async def test_register_builtins_includes_edit(self):
        from taui.tools.builtins import register_builtins
        from taui.tools.registry import ToolRegistry

        reg = ToolRegistry()
        register_builtins(reg)
        assert "edit" in reg
