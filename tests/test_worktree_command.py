"""Tests for the /worktree slash command (list / add)."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

from taui.commands.git_workflows import WorktreeCommand, _parse_worktree_porcelain
from taui.commands.registry import CommandContext


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True
    )


def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "T")
    (repo / "f.txt").write_text("hi\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    return repo


def _ctx(*args):
    return CommandContext(raw_input="/worktree " + " ".join(args), args=list(args))


def _cmd(repo):
    cmd = WorktreeCommand()
    cmd._get_session = lambda: SimpleNamespace(working_dir=repo)
    return cmd


class TestWorktreePorcelainParse:
    def test_parses_branches_heads_and_detached(self):
        text = (
            "worktree /a\nHEAD abc\nbranch refs/heads/main\n\n"
            "worktree /b\nHEAD def\nbranch refs/heads/feature/x\n\n"
            "worktree /c\nHEAD ghi\ndetached\n"
        )
        entries = _parse_worktree_porcelain(text)
        assert [e["path"] for e in entries] == ["/a", "/b", "/c"]
        assert entries[0]["branch"] == "main"
        # Branch names with slashes are preserved.
        assert entries[1]["branch"] == "feature/x"
        assert entries[2]["branch"] is None


class TestWorktreeCommand:
    async def test_no_session_fails(self):
        result = await WorktreeCommand().execute(_ctx("list"))
        assert result.error

    async def test_list_shows_main_worktree(self, tmp_path):
        repo = _init_repo(tmp_path)
        result = await _cmd(repo).execute(_ctx("list"))
        assert not result.error
        assert "main" in result.output
        assert result.metadata["worktrees"]

    async def test_list_is_the_default(self, tmp_path):
        repo = _init_repo(tmp_path)
        result = await _cmd(repo).execute(_ctx())
        assert not result.error
        assert "Worktrees:" in result.output

    async def test_add_creates_worktree_and_lists_it(self, tmp_path):
        repo = _init_repo(tmp_path)
        result = await _cmd(repo).execute(_ctx("add", "feature/login"))
        assert not result.error, result.output
        target = repo / ".worktrees" / "feature-login"
        assert target.is_dir()
        assert result.metadata["worktree_path"] == str(target)

        listed = await _cmd(repo).execute(_ctx("list"))
        assert "feature/login" in listed.output

    async def test_add_existing_path_fails(self, tmp_path):
        repo = _init_repo(tmp_path)
        await _cmd(repo).execute(_ctx("add", "dup"))
        result = await _cmd(repo).execute(_ctx("add", "dup"))
        assert result.error
        assert "already exists" in result.output

    async def test_add_requires_a_branch(self, tmp_path):
        repo = _init_repo(tmp_path)
        result = await _cmd(repo).execute(_ctx("add"))
        assert result.error
        assert "Usage" in result.output

    async def test_unknown_subcommand_fails(self, tmp_path):
        repo = _init_repo(tmp_path)
        result = await _cmd(repo).execute(_ctx("frobnicate"))
        assert result.error
        assert "Unknown" in result.output
