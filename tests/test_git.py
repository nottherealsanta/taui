"""Tests for GitTool."""

import pytest
from pathlib import Path

from taui.tools.builtins.git import GitTool


@pytest.fixture
def git_tool(tmp_path):
    tool = GitTool()
    tool.working_dir = tmp_path
    return tool


class TestGitTool:
    def test_schema(self):
        tool = GitTool()
        assert tool.name == "git"
        assert "operation" in tool.schema["required"]

    async def test_unknown_operation(self, git_tool):
        result = await git_tool.execute({"operation": "rebase"})
        assert result.error
        assert "Unknown operation" in result.content

    async def test_missing_operation(self, git_tool):
        result = await git_tool.execute({})
        assert result.error

    async def test_status_in_git_repo(self, tmp_path):
        """Test status in an actual git repo."""
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), capture_output=True,
        )

        tool = GitTool()
        tool.working_dir = tmp_path
        result = await tool.execute({"operation": "status"})
        assert not result.error
        # Brand new repo, clean or shows untracked
        assert result.content is not None

    async def test_branch_current(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init", "-b", "main"], cwd=str(tmp_path), capture_output=True)

        tool = GitTool()
        tool.working_dir = tmp_path
        result = await tool.execute({"operation": "branch_current"})
        assert not result.error
        assert "main" in result.content

    async def test_log_in_empty_repo(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)

        tool = GitTool()
        tool.working_dir = tmp_path
        # Log in empty repo fails but shouldn't crash
        result = await tool.execute({"operation": "log"})
        # Git log on empty repo returns error or empty
        assert result.content is not None

    async def test_diff_clean(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), capture_output=True,
        )
        (tmp_path / "file.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(tmp_path), capture_output=True,
        )

        tool = GitTool()
        tool.working_dir = tmp_path
        result = await tool.execute({"operation": "diff"})
        assert not result.error
        assert "No changes" in result.content

    async def test_commit_no_message(self, git_tool):
        result = await git_tool.execute({"operation": "commit", "args": {}})
        assert result.error
        assert "message" in result.content

    async def test_blame_no_file(self, git_tool):
        result = await git_tool.execute({"operation": "blame", "args": {}})
        assert result.error
        assert "file" in result.content

    async def test_checkout_no_ref(self, git_tool):
        result = await git_tool.execute({"operation": "checkout", "args": {}})
        assert result.error
        assert "ref" in result.content
