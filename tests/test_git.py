"""Tests for GitTool."""


import pytest

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


def _git(cwd, *args):
    import subprocess

    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True
    )


def _init_repo_with_remote(tmp_path):
    """A working repo with one commit and a local bare 'origin' remote."""
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "main")
    _git(work, "config", "user.email", "t@t.com")
    _git(work, "config", "user.name", "T")
    (work / "f.txt").write_text("hello\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "init")
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(bare))
    _git(work, "remote", "add", "origin", str(bare))
    return work, bare


class TestGitNetworkOps:
    """fetch / pull / push / branch_create against a local bare remote."""

    def test_network_ops_require_approval(self):
        for op in ("fetch", "pull", "push", "branch_create"):
            assert GitTool.requires_approval({"operation": op}) is True
        assert GitTool.requires_approval({"operation": "status"}) is False

    async def test_branch_create_switches_branch(self, tmp_path):
        work, _ = _init_repo_with_remote(tmp_path)
        tool = GitTool()
        tool.working_dir = work
        result = await tool.execute(
            {"operation": "branch_create", "args": {"name": "feature"}}
        )
        assert not result.error, result.content
        current = await tool.execute({"operation": "branch_current"})
        assert "feature" in current.content

    async def test_branch_create_requires_name(self, tmp_path):
        work, _ = _init_repo_with_remote(tmp_path)
        tool = GitTool()
        tool.working_dir = work
        result = await tool.execute({"operation": "branch_create", "args": {}})
        assert result.error
        assert "name" in result.content

    async def test_push_then_fetch(self, tmp_path):
        work, _ = _init_repo_with_remote(tmp_path)
        tool = GitTool()
        tool.working_dir = work
        pushed = await tool.execute(
            {
                "operation": "push",
                "args": {"remote": "origin", "branch": "main", "set_upstream": True},
            }
        )
        assert not pushed.error, pushed.content
        fetched = await tool.execute(
            {"operation": "fetch", "args": {"remote": "origin", "prune": True}}
        )
        assert not fetched.error, fetched.content

    async def test_pull_brings_in_remote_commit(self, tmp_path):
        work, bare = _init_repo_with_remote(tmp_path)
        tool = GitTool()
        tool.working_dir = work
        await tool.execute(
            {
                "operation": "push",
                "args": {"remote": "origin", "branch": "main", "set_upstream": True},
            }
        )
        # A second clone adds a commit and pushes it to the shared remote.
        clone2 = tmp_path / "clone2"
        _git(tmp_path, "clone", str(bare), str(clone2))
        _git(clone2, "config", "user.email", "u@u.com")
        _git(clone2, "config", "user.name", "U")
        (clone2 / "g.txt").write_text("world\n")
        _git(clone2, "add", "-A")
        _git(clone2, "commit", "-m", "second")
        _git(clone2, "push", "origin", "main")

        result = await tool.execute(
            {"operation": "pull", "args": {"remote": "origin", "branch": "main"}}
        )
        assert not result.error, result.content
        assert (work / "g.txt").exists()

    async def test_push_without_remote_configured_fails_cleanly(self, tmp_path):
        # A bare repo with no 'origin' — push should fail, not raise.
        work = tmp_path / "solo"
        work.mkdir()
        _git(work, "init", "-b", "main")
        _git(work, "config", "user.email", "t@t.com")
        _git(work, "config", "user.name", "T")
        (work / "a.txt").write_text("x\n")
        _git(work, "add", "-A")
        _git(work, "commit", "-m", "init")
        tool = GitTool()
        tool.working_dir = work
        result = await tool.execute(
            {"operation": "push", "args": {"remote": "origin", "branch": "main"}}
        )
        assert result.error
        assert "push failed" in result.content
