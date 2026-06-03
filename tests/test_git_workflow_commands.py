"""Tests for the git workflow slash commands (/diff, /review, /commit).

These had no coverage; they also pin the behavior across the change that moved
their blocking git calls onto a worker thread.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

from taui.commands.git_workflows import (
    GitCommitCommand,
    GitDiffCommand,
    GitReviewCommand,
)
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
    return CommandContext(raw_input="/x " + " ".join(args), args=list(args))


def _diff_cmd(repo):
    cmd = GitDiffCommand()
    cmd._get_session = lambda: SimpleNamespace(working_dir=repo)
    return cmd


class TestGitDiffCommand:
    async def test_no_session_fails(self):
        result = await GitDiffCommand().execute(_ctx())
        assert result.error

    async def test_clean_repo_reports_no_changes(self, tmp_path):
        repo = _init_repo(tmp_path)
        result = await _diff_cmd(repo).execute(_ctx())
        assert not result.error
        assert "No working tree changes" in result.output

    async def test_unstaged_change_opens_diff_view(self, tmp_path):
        repo = _init_repo(tmp_path)
        (repo / "f.txt").write_text("changed\n")
        result = await _diff_cmd(repo).execute(_ctx())
        assert not result.error
        assert result.metadata.get("action") == "open_diff_view"
        assert "f.txt" in result.metadata.get("diff", "")

    async def test_staged_scope(self, tmp_path):
        repo = _init_repo(tmp_path)
        (repo / "f.txt").write_text("staged change\n")
        _git(repo, "add", "-A")
        result = await _diff_cmd(repo).execute(_ctx("--staged"))
        assert not result.error
        assert result.metadata.get("title") == "Staged Diff"

    async def test_bad_option_fails(self, tmp_path):
        repo = _init_repo(tmp_path)
        result = await _diff_cmd(repo).execute(_ctx("--bogus"))
        assert result.error


class TestGitReviewCommand:
    async def test_builds_review_prompt(self):
        result = await GitReviewCommand().execute(_ctx())
        assert result.metadata.get("action") == "send_prompt"
        assert "code review" in result.output.lower()

    async def test_security_focus(self):
        result = await GitReviewCommand().execute(_ctx("--security"))
        assert "security" in result.output.lower()

    async def test_rejects_conflicting_options(self):
        result = await GitReviewCommand().execute(_ctx("--staged", "--ref", "HEAD~1"))
        assert result.error


class TestGitCommitCommand:
    async def test_builds_commit_prompt(self):
        result = await GitCommitCommand().execute(_ctx("fix", "the", "bug"))
        assert result.metadata.get("action") == "send_prompt"
        assert "commit" in result.output.lower()
        assert "fix the bug" in result.output
