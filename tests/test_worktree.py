"""Tests for the worktree module and WorktreeTool."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from taui import worktree as wt
from taui.tools.builtins.worktree import WorktreeTool


def _init_repo(path: Path) -> None:
    """Initialise a git repo with one commit so HEAD resolves."""
    subprocess.run(["git", "init", "-b", "main"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(path), capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(path), capture_output=True)
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=str(path), capture_output=True, check=True
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _init_repo(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _isolated_worktree_root(monkeypatch, tmp_path):
    """Redirect ``~/.taui/worktrees/...`` inside each test."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    yield


class TestWorktreeModule:
    async def test_enter_creates_branch_and_path(self, repo):
        handle = await wt.enter(
            session_id="s1", origin=repo, branch="feat/sandbox"
        )
        assert handle.branch == "feat/sandbox"
        assert handle.path.exists()
        assert (handle.path / "README.md").exists()

    async def test_enter_invalid_branch(self, repo):
        with pytest.raises(wt.WorktreeError):
            await wt.enter(session_id="s1", origin=repo, branch="bad branch!")

    async def test_enter_outside_git_repo(self, tmp_path):
        nongit = tmp_path / "elsewhere"
        nongit.mkdir()
        with pytest.raises(wt.WorktreeError):
            await wt.enter(session_id="s1", origin=nongit, branch="x")

    async def test_enter_collision(self, repo):
        await wt.enter(session_id="s1", origin=repo, branch="a")
        with pytest.raises(wt.WorktreeError):
            await wt.enter(session_id="s1", origin=repo, branch="a")

    async def test_is_dirty_detects_change(self, repo):
        handle = await wt.enter(session_id="s1", origin=repo, branch="dirty")
        assert not await wt.is_dirty(handle)
        (handle.path / "new.txt").write_text("x")
        assert await wt.is_dirty(handle)

    async def test_exit_remove(self, repo):
        handle = await wt.enter(session_id="s1", origin=repo, branch="drop")
        path = handle.path
        await wt.exit_(handle, keep=False)
        assert not path.exists()
        # Branch is gone too (best-effort).
        out = subprocess.run(
            ["git", "branch", "--list", "drop"],
            cwd=str(repo), capture_output=True, text=True,
        ).stdout
        assert "drop" not in out

    async def test_exit_keep(self, repo):
        handle = await wt.enter(session_id="s1", origin=repo, branch="keep")
        await wt.exit_(handle, keep=True)
        assert handle.path.exists()


class TestWorktreeTool:
    def test_schema(self):
        tool = WorktreeTool()
        assert tool.name == "worktree"
        assert "operation" in tool.schema["required"]

    async def test_status_no_handle(self):
        tool = WorktreeTool()
        result = await tool.execute({"operation": "status"})
        assert not result.error
        assert "No active worktree" in result.content

    async def test_enter_requires_branch(self):
        tool = WorktreeTool()
        result = await tool.execute({"operation": "enter"})
        assert result.error
        assert "branch" in result.content

    async def test_enter_requires_session_wiring(self, repo):
        tool = WorktreeTool()
        tool.working_dir = repo
        # No _session_id set — must refuse.
        result = await tool.execute(
            {"operation": "enter", "branch": "feat/x"}
        )
        assert result.error
        assert "wired" in result.content

    async def test_enter_then_exit_cycle(self, repo):
        tool = WorktreeTool()
        tool.working_dir = repo
        tool._session_id = "s1"

        active: dict[str, wt.WorktreeHandle | None] = {"h": None}

        async def on_enter(handle: wt.WorktreeHandle) -> None:
            active["h"] = handle

        async def on_exit(keep: bool) -> None:
            active["h"] = None

        tool._on_enter = on_enter
        tool._on_exit = on_exit
        tool._get_handle = lambda: active["h"]

        result = await tool.execute(
            {"operation": "enter", "branch": "feat/iso"}
        )
        assert not result.error, result.content
        assert active["h"] is not None
        assert active["h"].branch == "feat/iso"

        # Second enter while active is rejected.
        again = await tool.execute(
            {"operation": "enter", "branch": "other"}
        )
        assert again.error
        assert "already active" in again.content

        # Exit removes worktree.
        exit_res = await tool.execute(
            {"operation": "exit", "keep": False}
        )
        assert not exit_res.error
        assert active["h"] is None

    async def test_exit_dirty_requires_keep(self, repo):
        tool = WorktreeTool()
        tool.working_dir = repo
        tool._session_id = "s1"

        active: dict[str, wt.WorktreeHandle | None] = {"h": None}

        async def on_enter(handle: wt.WorktreeHandle) -> None:
            active["h"] = handle

        async def on_exit(keep: bool) -> None:
            active["h"] = None

        tool._on_enter = on_enter
        tool._on_exit = on_exit
        tool._get_handle = lambda: active["h"]

        enter_res = await tool.execute(
            {"operation": "enter", "branch": "dirty"}
        )
        assert not enter_res.error
        handle = active["h"]
        assert handle is not None
        (handle.path / "scratch.txt").write_text("uncommitted\n")

        # keep=false must be refused while dirty.
        refused = await tool.execute(
            {"operation": "exit", "keep": False}
        )
        assert refused.error
        assert "uncommitted" in refused.content
        assert active["h"] is not None  # handle preserved

        # keep=true succeeds.
        kept = await tool.execute({"operation": "exit", "keep": True})
        assert not kept.error
        assert active["h"] is None

    async def test_unknown_operation(self):
        tool = WorktreeTool()
        result = await tool.execute({"operation": "nope"})
        assert result.error
        assert "Unknown" in result.content
