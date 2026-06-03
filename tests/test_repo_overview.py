"""Tests for the repo_overview tool (also covers its off-thread execution)."""

from __future__ import annotations

from taui.tools.builtins.repo_overview import RepoOverviewTool


def _setup(tmp_path):
    (tmp_path / "main.py").write_text("print('hi')\n")
    (tmp_path / "README.md").write_text("# demo\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n")
    return tmp_path


def _tool(tmp_path):
    tool = RepoOverviewTool()
    tool.working_dir = tmp_path
    return tool


class TestRepoOverviewTool:
    async def test_surveys_project(self, tmp_path):
        _setup(tmp_path)
        result = await _tool(tmp_path).execute({})
        assert not result.error
        out = result.content
        assert "# Project:" in out
        assert "Languages" in out
        assert "Directory structure" in out
        assert "Python" in out  # main.py / src/app.py

    async def test_lists_entry_points(self, tmp_path):
        _setup(tmp_path)
        result = await _tool(tmp_path).execute({})
        assert "main.py" in result.content

    async def test_empty_dir_does_not_error(self, tmp_path):
        result = await _tool(tmp_path).execute({})
        assert not result.error
        assert "# Project:" in result.content
