"""Tests for ApplyPatchTool."""

from __future__ import annotations

from taui.tools.builtins.apply_patch import ApplyPatchTool, _apply_hunks, _parse_patch


class TestParsePatch:
    def test_simple_patch(self):
        patch = (
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-old line\n"
            "+new line\n"
            " line3\n"
        )
        result = _parse_patch(patch)
        assert "file.py" in result
        assert len(result["file.py"]) == 1

    def test_multi_hunk(self):
        patch = (
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-old1\n"
            "+new1\n"
            " ctx\n"
            "@@ -10,2 +10,2 @@\n"
            "-old2\n"
            "+new2\n"
            " ctx\n"
        )
        result = _parse_patch(patch)
        assert len(result["file.py"]) == 2

    def test_multi_file(self):
        patch = (
            "--- a/a.py\n"
            "+++ b/a.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
            "--- a/b.py\n"
            "+++ b/b.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        )
        result = _parse_patch(patch)
        assert "a.py" in result
        assert "b.py" in result

    def test_new_file_devnull(self):
        patch = (
            "--- /dev/null\n"
            "+++ b/new_file.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+line1\n"
            "+line2\n"
        )
        result = _parse_patch(patch)
        assert "new_file.py" in result


class TestApplyHunks:
    def test_simple_replacement(self):
        lines = ["line1\n", "old line\n", "line3\n"]
        hunks = [
            {
                "old_start": 2,
                "old_count": 1,
                "new_start": 2,
                "new_count": 1,
                "lines": ["-old line", "+new line"],
            }
        ]
        result = _apply_hunks(lines, hunks)
        assert "new line\n" in result
        assert "old line\n" not in result

    def test_multi_hunk_offsets(self):
        lines = ["a\n", "b\n", "c\n", "d\n", "e\n"]
        hunks = [
            {
                "old_start": 1,
                "old_count": 1,
                "new_start": 1,
                "new_count": 2,
                "lines": ["-a", "+a1", "+a2"],
            },
            {
                "old_start": 5,
                "old_count": 1,
                "new_start": 6,
                "new_count": 1,
                "lines": ["-e", "+E"],
            },
        ]
        result = _apply_hunks(lines, hunks)
        assert result[0] == "a1\n"
        assert result[1] == "a2\n"
        assert result[-1] == "E\n"

    def test_context_mismatch_raises(self):
        lines = ["line1\n", "actual\n", "line3\n"]
        hunks = [
            {
                "old_start": 2,
                "old_count": 1,
                "new_start": 2,
                "new_count": 1,
                "lines": ["-expected", "+new"],
            }
        ]
        import pytest

        with pytest.raises(ValueError, match="Context mismatch"):
            _apply_hunks(lines, hunks)

    def test_hunk_beyond_file_end_raises(self):
        lines = ["line1\n"]
        hunks = [
            {
                "old_start": 10,
                "old_count": 1,
                "new_start": 10,
                "new_count": 1,
                "lines": ["-x", "+y"],
            }
        ]
        import pytest

        with pytest.raises(ValueError, match="extends beyond file end"):
            _apply_hunks(lines, hunks)


class TestApplyPatchTool:
    async def test_apply_simple_patch(self, tmp_path):
        (tmp_path / "file.py").write_text("line1\nold line\nline3\n")
        tool = ApplyPatchTool()
        tool.working_dir = tmp_path

        patch = (
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-old line\n"
            "+new line\n"
            " line3\n"
        )
        result = await tool.execute({"patch": patch})
        assert not result.error
        assert (tmp_path / "file.py").read_text().strip() == "line1\nnew line\nline3"

    async def test_empty_patch(self, tmp_path):
        tool = ApplyPatchTool()
        tool.working_dir = tmp_path
        result = await tool.execute({"patch": ""})
        assert result.error

    async def test_new_file_from_patch(self, tmp_path):
        tool = ApplyPatchTool()
        tool.working_dir = tmp_path

        patch = (
            "--- /dev/null\n"
            "+++ b/new_file.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+line1\n"
            "+line2\n"
        )
        result = await tool.execute({"patch": patch})
        assert not result.error
        assert (tmp_path / "new_file.py").exists()

    async def test_rejects_path_escape(self, tmp_path):
        # A patch header like `+++ b/../escape.txt` must not write outside the
        # workspace.
        work = tmp_path / "work"
        work.mkdir()
        tool = ApplyPatchTool()
        tool.working_dir = work

        patch = (
            "--- /dev/null\n"
            "+++ b/../escape.txt\n"
            "@@ -0,0 +1,1 @@\n"
            "+pwned\n"
        )
        result = await tool.execute({"patch": patch})
        assert result.error
        assert "outside the workspace" in result.content
        assert not (tmp_path / "escape.txt").exists()

    async def test_multi_file_patch(self, tmp_path):
        (tmp_path / "a.py").write_text("old\n")
        (tmp_path / "b.py").write_text("old\n")
        tool = ApplyPatchTool()
        tool.working_dir = tmp_path

        patch = (
            "--- a/a.py\n"
            "+++ b/a.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new_a\n"
            "--- a/b.py\n"
            "+++ b/b.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new_b\n"
        )
        result = await tool.execute({"patch": patch})
        assert not result.error
        assert "new_a" in (tmp_path / "a.py").read_text()
        assert "new_b" in (tmp_path / "b.py").read_text()

    async def test_bad_patch_context_returns_fail(self, tmp_path):
        (tmp_path / "file.py").write_text("actual content\n")
        tool = ApplyPatchTool()
        tool.working_dir = tmp_path

        patch = (
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-wrong content\n"
            "+new\n"
        )
        result = await tool.execute({"patch": patch})
        assert result.error
        assert "Failed to apply patch" in result.content

    async def test_result_lists_patched_file(self, tmp_path):
        (tmp_path / "x.py").write_text("a\nb\n")
        tool = ApplyPatchTool()
        tool.working_dir = tmp_path

        patch = (
            "--- a/x.py\n"
            "+++ b/x.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-a\n"
            "+A\n"
            " b\n"
        )
        result = await tool.execute({"patch": patch})
        assert not result.error
        assert "Patched x.py" in result.content
