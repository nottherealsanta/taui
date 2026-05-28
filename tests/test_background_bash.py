"""Tests for streaming/background bash and the truncation envelope."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from taui.tools.background import BackgroundProcessRegistry
from taui.tools.builtins.bash import BashKillTool, BashStatusTool, BashTool
from taui.tools.builtins.common import TruncationEnvelope
from taui.tools.builtins.files import GlobTool, GrepTool
from taui.tools.executor import Completed, PolicyDecision, ToolExecutor, ToolPolicy
from taui.tools.registry import ToolRegistry
from taui.tools.truncation import TruncationStore

# ── TruncationEnvelope ────────────────────────────────────────────────────────


class TestTruncationEnvelope:
    def test_footer_with_total(self):
        env = TruncationEnvelope(
            truncated_at=500, unit="matches", total_hint=1200,
            peek_handle="tr_abc", next_hint="narrow the regex",
        )
        footer = env.format_footer()
        assert "showing 500 of 1200 matches" in footer
        assert 'peek(handle="tr_abc")' in footer
        assert "narrow the regex" in footer

    def test_footer_without_total(self):
        env = TruncationEnvelope(truncated_at=50_000, unit="bytes")
        footer = env.format_footer()
        assert "first 50000 bytes" in footer
        assert "total unknown" in footer

    def test_to_metadata(self):
        env = TruncationEnvelope(
            truncated_at=200, unit="files", total_hint=500, peek_handle="tr_x",
        )
        meta = env.to_metadata()
        assert meta["truncated"] is True
        assert meta["truncated_at"] == 200
        assert meta["unit"] == "files"
        assert meta["total_hint"] == 500
        assert meta["peek_handle"] == "tr_x"


# ── glob / grep truncation envelopes ──────────────────────────────────────────


@pytest.fixture
def big_workspace(tmp_path: Path) -> Path:
    """Create a workspace with enough files to exceed glob's 200 cap."""
    for i in range(250):
        (tmp_path / f"f{i:04d}.py").write_text(f"# file {i}\nx = {i}\n")
    return tmp_path


class TestGlobEnvelope:
    async def test_glob_truncation_emits_envelope(self, big_workspace: Path):
        store = TruncationStore()
        tool = GlobTool(working_dir=big_workspace)
        tool._truncation_store = store

        result = await tool.execute({"pattern": "*.py"})
        assert not result.error
        assert "[truncated:" in result.content
        assert "showing 200 of 250 files" in result.content
        assert result.metadata["truncated"] is True
        assert result.metadata["total_hint"] == 250
        assert "peek_handle" in result.metadata

        # Peek into the stored full output
        peeked = store.peek(result.metadata["peek_handle"], offset=0, limit=100_000)
        assert peeked is not None
        # All 250 paths land in the stored content
        assert peeked.count(".py") >= 250

    async def test_glob_no_truncation_no_envelope(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        tool = GlobTool(working_dir=tmp_path)
        result = await tool.execute({"pattern": "*.py"})
        assert "[truncated:" not in result.content
        assert "truncated" not in result.metadata


class TestGrepEnvelope:
    async def test_grep_truncation_emits_envelope(self, tmp_path: Path):
        # Build a single file with lots of matches.
        big = "\n".join(f"hit line {i}" for i in range(800))
        (tmp_path / "big.txt").write_text(big)

        store = TruncationStore()
        tool = GrepTool(working_dir=tmp_path)
        tool._truncation_store = store
        result = await tool.execute({"pattern": "hit"})

        assert not result.error
        assert "[truncated:" in result.content
        assert "matches" in result.content
        assert result.metadata["truncated"] is True
        assert result.metadata["peek_handle"]
        # Stored content has all 800 matches
        peeked = store.peek(
            result.metadata["peek_handle"], offset=0, limit=200_000
        )
        assert peeked is not None
        assert peeked.count("hit line") >= 800


# ── BashTool foreground truncation ────────────────────────────────────────────


class TestBashForegroundTruncation:
    async def test_large_output_truncates_with_envelope(self, tmp_path: Path):
        store = TruncationStore()
        tool = BashTool(working_dir=tmp_path)
        tool._truncation_store = store
        # Produce ~120KB of output
        result = await tool.execute({
            "command": "yes hello | head -c 120000",
        })
        assert not result.error
        assert "[truncated:" in result.content
        assert result.metadata["truncated"] is True
        assert result.metadata["unit"] == "bytes"
        assert result.metadata["total_hint"] >= 100_000
        assert result.metadata["peek_handle"]

        # Peek returns more than the inline preview
        peeked = store.peek(
            result.metadata["peek_handle"], offset=0, limit=200_000
        )
        assert peeked is not None
        assert len(peeked) > 50_000

    async def test_foreground_streams_live_output_deltas(self, tmp_path: Path):
        registry = ToolRegistry()
        registry.register(BashTool(working_dir=tmp_path))
        executor = ToolExecutor(
            registry,
            policy=ToolPolicy({"bash": PolicyDecision.AUTO}),
        )
        chunks: list[str] = []

        async def capture(chunk: str) -> None:
            chunks.append(chunk)

        outcome = await executor.run(
            "call-1",
            "bash",
            {
                "command": "printf 'one\\n'; sleep 0.05; printf 'two\\n'",
                "timeout": 5,
            },
            on_output_delta=capture,
        )

        assert isinstance(outcome, Completed)
        assert not outcome.result.error
        assert "one" in outcome.result.content
        assert "two" in outcome.result.content
        streamed = "".join(chunks)
        assert "one" in streamed
        assert "two" in streamed


# ── BackgroundProcessRegistry ─────────────────────────────────────────────────


class TestBackgroundRegistry:
    async def test_start_read_kill(self, tmp_path: Path):
        reg = BackgroundProcessRegistry()
        bp = await reg.start(
            command="for i in 1 2 3 4 5; do echo line$i; sleep 0.05; done",
            cwd=str(tmp_path),
            env={"PATH": "/usr/bin:/bin"},
        )
        # Wait for the process to finish
        await bp.proc.wait()
        # Drain the reader task
        if bp.reader_task is not None:
            await bp.reader_task

        text, cursor = reg.read(bp.bash_id, max_bytes=4096)
        assert "line1" in text
        assert "line5" in text
        assert cursor > 0
        # Cursor advances — second read returns empty
        text2, _ = reg.read(bp.bash_id, max_bytes=4096)
        assert text2 == ""

    async def test_wait_for_chunk(self, tmp_path: Path):
        reg = BackgroundProcessRegistry()
        bp = await reg.start(
            command="sleep 0.1 && echo delayed",
            cwd=str(tmp_path),
            env={"PATH": "/usr/bin:/bin"},
        )
        # No output yet
        text, _ = reg.read(bp.bash_id)
        # Could be empty initially
        got_new = await reg.wait_for_chunk(bp.bash_id, timeout=2.0)
        assert got_new
        if bp.reader_task is not None:
            await bp.reader_task
        text2, _ = reg.read(bp.bash_id)
        assert "delayed" in (text + text2)

    async def test_kill_running(self, tmp_path: Path):
        reg = BackgroundProcessRegistry()
        bp = await reg.start(
            command="sleep 30",
            cwd=str(tmp_path),
            env={"PATH": "/usr/bin:/bin"},
        )
        killed = await reg.kill(bp.bash_id)
        assert killed
        assert bp.exit_code is not None

    async def test_kill_unknown(self):
        reg = BackgroundProcessRegistry()
        assert await reg.kill("nope") is False

    async def test_shutdown_terminates_all(self, tmp_path: Path):
        reg = BackgroundProcessRegistry()
        bp1 = await reg.start(
            command="sleep 30", cwd=str(tmp_path),
            env={"PATH": "/usr/bin:/bin"},
        )
        bp2 = await reg.start(
            command="sleep 30", cwd=str(tmp_path),
            env={"PATH": "/usr/bin:/bin"},
        )
        await reg.shutdown()
        # Both processes should now be done
        await asyncio.sleep(0.1)
        assert bp1.proc.returncode is not None
        assert bp2.proc.returncode is not None


# ── End-to-end: bash background → bash_status → bash_kill ─────────────────────


class TestBashBackgroundFlow:
    async def test_background_returns_bash_id(self, tmp_path: Path):
        reg = BackgroundProcessRegistry()
        bash = BashTool(working_dir=tmp_path)
        bash._bg_registry = reg

        result = await bash.execute({
            "command": "for i in 1 2 3; do echo step$i; sleep 0.05; done",
            "background": True,
            "initial_wait": 0.5,
        })
        assert not result.error
        bash_id = result.metadata["bash_id"]
        assert bash_id.startswith("bg_")
        # initial output likely captured (process is short)
        assert "step" in result.content or "no output yet" in result.content

    async def test_background_without_registry_fails(self, tmp_path: Path):
        bash = BashTool(working_dir=tmp_path)
        result = await bash.execute({
            "command": "echo hi", "background": True,
        })
        assert result.error
        assert "registry" in result.content.lower()

    async def test_status_streams_incremental(self, tmp_path: Path):
        reg = BackgroundProcessRegistry()
        bash = BashTool(working_dir=tmp_path)
        bash._bg_registry = reg
        status = BashStatusTool()
        status._bg_registry = reg

        start = await bash.execute({
            "command": (
                "echo one; sleep 0.1; echo two; sleep 0.1; echo three"
            ),
            "background": True,
            "initial_wait": 0.05,  # return fast, before everything streams
        })
        bash_id = start.metadata["bash_id"]

        # Drain until exit — include initial output from `start`
        collected = start.content
        for _ in range(20):
            s = await status.execute({"bash_id": bash_id, "wait": 1.0})
            collected += s.content
            if not s.metadata["running"]:
                break

        assert "one" in collected
        assert "two" in collected
        assert "three" in collected

    async def test_kill_via_tool(self, tmp_path: Path):
        reg = BackgroundProcessRegistry()
        bash = BashTool(working_dir=tmp_path)
        bash._bg_registry = reg
        kill = BashKillTool()
        kill._bg_registry = reg

        start = await bash.execute({
            "command": "sleep 30",
            "background": True,
            "initial_wait": 0.05,
        })
        bash_id = start.metadata["bash_id"]
        result = await kill.execute({"bash_id": bash_id})
        assert not result.error
        assert result.metadata["killed"] is True

    async def test_status_unknown_bash_id(self):
        reg = BackgroundProcessRegistry()
        status = BashStatusTool()
        status._bg_registry = reg
        result = await status.execute({"bash_id": "bg_nope"})
        assert result.error
        assert "unknown" in result.content.lower()

    async def test_kill_unknown_bash_id(self):
        reg = BackgroundProcessRegistry()
        kill = BashKillTool()
        kill._bg_registry = reg
        result = await kill.execute({"bash_id": "bg_nope"})
        assert result.error

    async def test_kill_after_exit_is_idempotent(self, tmp_path: Path):
        reg = BackgroundProcessRegistry()
        bash = BashTool(working_dir=tmp_path)
        bash._bg_registry = reg
        kill = BashKillTool()
        kill._bg_registry = reg

        start = await bash.execute({
            "command": "echo done", "background": True, "initial_wait": 0.5,
        })
        bash_id = start.metadata["bash_id"]
        # Make sure it has exited
        bp = reg.get(bash_id)
        assert bp is not None
        await bp.proc.wait()
        if bp.reader_task is not None:
            await bp.reader_task

        result = await kill.execute({"bash_id": bash_id})
        assert not result.error
        assert result.metadata["already_exited"] is True
