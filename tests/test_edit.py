"""Tests for the edit tool — fuzzy matching, multi-edit, edge cases."""


import pytest

from taui.tools.builtins.edit import EditTool, find_match

# ── find_match unit tests ─────────────────────────────────────────────────────


class TestFindMatch:
    def test_exact_match(self):
        content = "hello world\nfoo bar\nbaz"
        result = find_match(content, "foo bar")
        assert result is not None
        span, strategy = result
        assert strategy == "exact"
        start, end = span
        assert content[start:end] == "foo bar"

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
        span, strategy = result
        assert strategy == "unicode_normalized"
        # The span must reference the *original* content
        start, end = span
        # search has no trailing newline, so span is trimmed
        assert content[start:end] == "print('hello')"

    def test_whitespace_normalization(self):
        content = "def foo():  \n    pass\n"
        search = "def foo():\n    pass\n"
        result = find_match(content, search)
        assert result is not None
        span, strategy = result
        # Span must cover the original lines including trailing whitespace
        start, end = span
        assert content[start:end] == "def foo():  \n    pass\n"

    def test_smart_double_quotes(self):
        content = 'x = "hello"\n'
        search = "x = \u201chello\u201d"
        result = find_match(content, search)
        assert result is not None
        span, _ = result
        start, end = span
        # search has no trailing newline, so span is trimmed
        assert content[start:end] == 'x = "hello"'

    def test_indentation_flexible_returns_correct_span(self):
        content = "        def foo():\n            pass\n"
        search = "    def foo():\n        pass\n"  # Different indentation level
        result = find_match(content, search)
        assert result is not None
        span, strategy = result
        assert strategy == "indentation_flexible"
        start, end = span
        # Must return the original indented text
        assert content[start:end] == "        def foo():\n            pass\n"


# ── Span-based corruption regression tests ────────────────────────────────────
# These test cases previously corrupted the file because fuzzy strategies
# returned positions into normalized strings which were then spliced
# against original content.


class TestSpanBasedCorrectnessRegression:
    """Tests that previously-corrupting fuzzy edits now produce byte-correct files."""

    async def test_smart_quotes_edit_byte_correct(self, tmp_path):
        """File with ASCII quotes, old_text has smart quotes → must be byte-correct."""
        f = tmp_path / "quotes.py"
        original = "msg = 'hello world'\nprint(msg)\n"
        f.write_text(original)

        tool = EditTool(working_dir=tmp_path)
        result = await tool.execute({
            "path": "quotes.py",
            "edits": [{
                "old_text": "msg = \u2018hello world\u2019",  # smart quotes
                "new_text": "msg = 'goodbye world'",
            }],
        })
        assert not result.error, result.content
        final = f.read_text()
        assert final == "msg = 'goodbye world'\nprint(msg)\n"

    async def test_trailing_whitespace_edit_byte_correct(self, tmp_path):
        """File with trailing whitespace, search without it → byte-correct."""
        f = tmp_path / "ws.py"
        # Lines have trailing spaces
        original = "def foo():  \n    return 42  \n"
        f.write_text(original)

        tool = EditTool(working_dir=tmp_path)
        result = await tool.execute({
            "path": "ws.py",
            "edits": [{
                "old_text": "def foo():\n    return 42\n",
                "new_text": "def bar():\n    return 99\n",
            }],
        })
        assert not result.error, result.content
        final = f.read_text()
        assert final == "def bar():\n    return 99\n"

    async def test_indentation_mismatch_edit_byte_correct(self, tmp_path):
        """Search with different indentation level than file → byte-correct."""
        f = tmp_path / "indent.py"
        original = "class Foo:\n    def bar(self):\n        return 1\n"
        f.write_text(original)

        tool = EditTool(working_dir=tmp_path)
        # LLM sends old_text with 2-space indent (file has 4-space)
        result = await tool.execute({
            "path": "indent.py",
            "edits": [{
                "old_text": "  def bar(self):\n      return 1\n",
                "new_text": "  def bar(self):\n      return 2\n",
            }],
        })
        assert not result.error, result.content
        final = f.read_text()
        # The original indentation must be preserved in the surrounding context,
        # and the replacement uses the original indentation level.
        assert "class Foo:\n" in final
        assert "return 2" in final

    async def test_ellipsis_unicode_byte_correct(self, tmp_path):
        """File has '...' (3 dots), search has '…' (ellipsis) → byte-correct."""
        f = tmp_path / "ellip.py"
        original = "# TODO: implement...\ndef func():\n    pass\n"
        f.write_text(original)

        tool = EditTool(working_dir=tmp_path)
        result = await tool.execute({
            "path": "ellip.py",
            "edits": [{
                "old_text": "# TODO: implement\u2026",  # Unicode ellipsis
                "new_text": "# DONE: implemented",
            }],
        })
        assert not result.error, result.content
        final = f.read_text()
        assert final == "# DONE: implemented\ndef func():\n    pass\n"

    async def test_multi_edit_with_fuzzy_byte_correct(self, tmp_path):
        """Multiple fuzzy edits in one call → all byte-correct, no corruption."""
        f = tmp_path / "multi.py"
        original = (
            "msg1 = 'first'  \n"   # trailing space
            "msg2 = 'second'  \n"  # trailing space
            "print(msg1, msg2)\n"
        )
        f.write_text(original)

        tool = EditTool(working_dir=tmp_path)
        result = await tool.execute({
            "path": "multi.py",
            "edits": [
                {
                    "old_text": "msg1 = 'first'\n",   # no trailing space
                    "new_text": "msg1 = 'ONE'\n",
                },
                {
                    "old_text": "msg2 = 'second'\n",  # no trailing space
                    "new_text": "msg2 = 'TWO'\n",
                },
            ],
        })
        assert not result.error, result.content
        final = f.read_text()
        assert "msg1 = 'ONE'" in final
        assert "msg2 = 'TWO'" in final
        assert "print(msg1, msg2)" in final


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

    async def test_preserves_executable_mode(self, edit_tool, working_dir):
        """Editing an executable script must keep its +x bit.

        The atomic write used to mkstemp (0600) then rename over the target,
        which dropped the original mode to 0600 — silently making scripts and
        git hooks non-executable. atomic_write_text now copies the mode across.
        """
        import os
        import stat as stat_mod

        script = working_dir / "run.sh"
        script.write_text("#!/bin/sh\necho original\n")
        os.chmod(script, 0o755)

        result = await edit_tool.execute(
            {
                "path": "run.sh",
                "edits": [{"old_text": "echo original", "new_text": "echo edited"}],
            }
        )
        assert not result.error
        assert "echo edited" in script.read_text()
        mode = stat_mod.S_IMODE(script.stat().st_mode)
        assert mode == 0o755, f"expected mode preserved as 0o755, got {oct(mode)}"
        assert mode & 0o111, "executable bit must survive an edit"

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
