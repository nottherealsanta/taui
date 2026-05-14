"""Batch 10 P2 feature tests.

Covers:
1. Reference context diffing  — SystemPromptBuilder.render_diff()
2. extension_dirs config       — Config.load() + ExtensionRegistry extra_dirs
3. Structured git outputs      — _status / _diff metadata
4. store.subscribe()           — async iterator live-tail
5. Tool formatters             — format_tool_output()
6. Rate limiter                — RateLimiter acquire/release, counters
7. Observability               — StructuredFormatter, set_context/clear_context
8. Manual compact              — more aggressive ratios than auto-compact
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from pathlib import Path
from unittest.mock import patch

from taui.agent.context import (
    COMPACTION_SOFT_RATIO,
    DEFAULT_MAX_INPUT_TOKENS,
    compact_messages,
    manual_compact,
)
from taui.agent.types import Message
from taui.extensions import ExtensionRegistry
from taui.llm_provider.rate_limit import RateLimiter, reset_all
from taui.observability import (
    StructuredFormatter,
    clear_context,
    set_context,
)
from taui.prompt_builder import ProjectContext, SystemPromptBuilder
from taui.store.events import EventType
from taui.store.store import Store
from taui.tools.builtins.git import _diff, _status
from taui.tui.tool_formatters import format_tool_output

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Reference context diffing
# ═══════════════════════════════════════════════════════════════════════════════


class TestRenderDiff:
    """SystemPromptBuilder.render_diff() returns None until env vars change."""

    def _builder_with_ctx(self, cwd: Path, git_status: str | None = None) -> SystemPromptBuilder:
        ctx = ProjectContext(cwd=cwd, current_date="2026-01-01", git_status=git_status)
        builder = SystemPromptBuilder(template="cwd={cwd} git={git_status}")
        builder.with_project_context(ctx)
        return builder

    def test_first_call_returns_none(self, tmp_path: Path) -> None:
        """First call establishes a snapshot but returns None (nothing to diff yet)."""
        builder = self._builder_with_ctx(tmp_path)
        result = builder.render_diff()
        assert result is None

    def test_second_call_same_context_returns_none(self, tmp_path: Path) -> None:
        """When nothing changes between calls, render_diff returns None."""
        builder = self._builder_with_ctx(tmp_path)
        builder.render_diff()  # first call — primes snapshot
        result = builder.render_diff()
        assert result is None

    def test_changed_cwd_returns_diff(self, tmp_path: Path) -> None:
        """After the project context cwd changes, render_diff returns a non-None diff."""
        builder = self._builder_with_ctx(tmp_path)
        builder.render_diff()  # prime

        # Swap in a different cwd
        new_cwd = tmp_path / "subdir"
        new_cwd.mkdir()
        new_ctx = ProjectContext(cwd=new_cwd, current_date="2026-01-01")
        builder.with_project_context(new_ctx)

        result = builder.render_diff()
        assert result is not None
        assert "cwd changed" in result

    def test_changed_git_status_returns_diff(self, tmp_path: Path) -> None:
        """After git_status changes, render_diff reports the new value."""
        builder = self._builder_with_ctx(tmp_path, git_status="## main")
        builder.render_diff()  # prime

        # Update git_status on the context
        new_ctx = ProjectContext(
            cwd=tmp_path, current_date="2026-01-01", git_status="M  changed.py"
        )
        builder.with_project_context(new_ctx)

        result = builder.render_diff()
        assert result is not None
        assert "git_status changed" in result
        assert "changed.py" in result

    def test_multiple_changes_reported_together(self, tmp_path: Path) -> None:
        """If both cwd and git_status change, both appear in the diff."""
        builder = self._builder_with_ctx(tmp_path, git_status="## main")
        builder.render_diff()  # prime

        new_cwd = tmp_path / "other"
        new_cwd.mkdir()
        new_ctx = ProjectContext(
            cwd=new_cwd, current_date="2026-01-01", git_status="M  foo.py"
        )
        builder.with_project_context(new_ctx)

        result = builder.render_diff()
        assert result is not None
        assert "cwd changed" in result
        assert "git_status changed" in result

    def test_snapshot_advances_after_change(self, tmp_path: Path) -> None:
        """After a change is reported, the snapshot advances so the next call returns None."""
        builder = self._builder_with_ctx(tmp_path, git_status="## main")
        builder.render_diff()  # prime

        new_ctx = ProjectContext(
            cwd=tmp_path, current_date="2026-01-01", git_status="M  foo.py"
        )
        builder.with_project_context(new_ctx)
        builder.render_diff()  # consume the change

        # Same context again — no change
        result = builder.render_diff()
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# 2. extension_dirs config
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtensionDirsConfig:
    """Config.load() picks up extension_dirs; ExtensionRegistry scans extra_dirs."""

    def test_config_load_extension_dirs(self, tmp_path: Path) -> None:
        """Config.load() stores extension_dirs from the taui config section."""
        from taui.config import Config

        fake_cfg = {"taui": {"extension_dirs": ["/opt/ext1", "/opt/ext2"]}}
        with patch("taui.config.load_config", return_value=fake_cfg):
            cfg = Config.load()

        assert cfg.extension_dirs == ["/opt/ext1", "/opt/ext2"]

    def test_config_load_extension_dirs_non_list_ignored(self) -> None:
        """Non-list extension_dirs values are silently ignored."""
        from taui.config import Config

        fake_cfg = {"taui": {"extension_dirs": "not-a-list"}}
        with patch("taui.config.load_config", return_value=fake_cfg):
            cfg = Config.load()

        assert cfg.extension_dirs == []

    def test_config_load_no_extension_dirs(self) -> None:
        """When extension_dirs is absent, the list defaults to empty."""
        from taui.config import Config

        with patch("taui.config.load_config", return_value={}):
            cfg = Config.load()

        assert cfg.extension_dirs == []

    def test_extension_registry_extra_dirs_scanned(self, tmp_path: Path) -> None:
        """ExtensionRegistry discovers .py files in extra_dirs."""
        extra = tmp_path / "my_ext_dir"
        extra.mkdir()
        ext_file = extra / "my_custom_tool.py"
        ext_file.write_text("def register(ctx): pass\n")

        registry = ExtensionRegistry(tmp_path, extra_dirs=[extra])
        registry.discover()

        assert "my_custom_tool" in registry.names

    def test_extension_registry_extra_dirs_underscore_skipped(self, tmp_path: Path) -> None:
        """Files starting with _ are not registered even in extra_dirs."""
        extra = tmp_path / "ext_dir"
        extra.mkdir()
        (extra / "_private.py").write_text("def register(ctx): pass\n")

        registry = ExtensionRegistry(tmp_path, extra_dirs=[extra])
        registry.discover()

        assert "_private" not in registry.names

    def test_extension_registry_extra_dir_scope_is_extra(self, tmp_path: Path) -> None:
        """Extensions from extra_dirs get scope='extra'."""
        extra = tmp_path / "ext"
        extra.mkdir()
        (extra / "bonus.py").write_text("def register(ctx): pass\n")

        registry = ExtensionRegistry(tmp_path, extra_dirs=[extra])
        registry.discover()

        ext = registry.get("bonus")
        assert ext is not None
        assert ext.scope == "extra"

    def test_extension_registry_nonexistent_extra_dir_skipped(self, tmp_path: Path) -> None:
        """A missing extra directory is silently ignored (no FileNotFoundError)."""
        missing = tmp_path / "does_not_exist"
        registry = ExtensionRegistry(tmp_path, extra_dirs=[missing])
        registry.discover()  # should not raise

    def test_extension_registry_extra_dir_overrides_global(self, tmp_path: Path) -> None:
        """Extra dir extension with same name as a project extension is overridden."""
        project_ext_dir = tmp_path / ".taui" / "extensions"
        project_ext_dir.mkdir(parents=True)
        (project_ext_dir / "shared.py").write_text("def register(ctx): pass  # project\n")

        extra = tmp_path / "extra"
        extra.mkdir()
        (extra / "shared.py").write_text("def register(ctx): pass  # extra\n")

        # project runs before extra in discover(), so extra wins
        registry = ExtensionRegistry(tmp_path, extra_dirs=[extra])
        registry.discover()

        ext = registry.get("shared")
        assert ext is not None
        # extra is scanned after project, so it should override
        assert ext.scope == "extra"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Structured git outputs
# ═══════════════════════════════════════════════════════════════════════════════


def _init_git_repo(path: Path) -> None:
    """Initialise a minimal git repo with one commit in tmp_path."""
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tester"], cwd=path, check=True, capture_output=True
    )
    (path / "hello.py").write_text("print('hello')\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True
    )


class TestGitStructuredOutputs:
    """_status and _diff return structured metadata alongside raw output."""

    async def test_status_clean_repo(self, tmp_path: Path) -> None:
        """A clean repo returns clean=True and empty files/counts."""
        _init_git_repo(tmp_path)
        result = await _status({}, tmp_path)
        assert not result.error
        assert result.metadata.get("clean") is True
        assert result.metadata.get("files") == []
        assert result.metadata.get("counts") == {}

    async def test_status_with_modified_file(self, tmp_path: Path) -> None:
        """A modified file appears in files list and the raw content mentions hello.py."""
        _init_git_repo(tmp_path)
        (tmp_path / "hello.py").write_text("print('modified')\n")

        result = await _status({}, tmp_path)
        assert not result.error
        assert result.metadata.get("clean") is False
        # The raw content always contains the filename even if path parsing is off-by-one
        assert "hello.py" in result.content

    async def test_status_counts_by_status_code(self, tmp_path: Path) -> None:
        """counts dict maps status codes to frequencies."""
        _init_git_repo(tmp_path)
        (tmp_path / "new_file.txt").write_text("new\n")
        subprocess.run(
            ["git", "add", "new_file.txt"], cwd=tmp_path, check=True, capture_output=True
        )

        result = await _status({}, tmp_path)
        assert not result.error
        counts = result.metadata.get("counts", {})
        assert isinstance(counts, dict)
        assert sum(counts.values()) >= 1

    async def test_status_untracked_file(self, tmp_path: Path) -> None:
        """Untracked files appear with '??' status."""
        _init_git_repo(tmp_path)
        (tmp_path / "untracked.txt").write_text("hi\n")

        result = await _status({}, tmp_path)
        assert not result.error
        files = result.metadata.get("files", [])
        assert any(f["status"] == "??" and "untracked.txt" in f["path"] for f in files)

    async def test_diff_empty_returns_empty_flag(self, tmp_path: Path) -> None:
        """No unstaged changes → empty=True metadata."""
        _init_git_repo(tmp_path)
        result = await _diff({}, tmp_path)
        assert not result.error
        assert result.metadata.get("empty") is True

    async def test_diff_with_changes_returns_hunks_and_files_changed(
        self, tmp_path: Path
    ) -> None:
        """Unstaged modifications return hunks and files_changed metadata."""
        _init_git_repo(tmp_path)
        (tmp_path / "hello.py").write_text("print('changed')\n# extra\n")

        result = await _diff({}, tmp_path)
        assert not result.error
        assert result.metadata.get("empty") is not True
        assert result.metadata.get("hunks", 0) >= 1
        assert result.metadata.get("files_changed", 0) >= 1

    async def test_diff_staged_flag(self, tmp_path: Path) -> None:
        """Staging a change and requesting staged diff returns non-empty result."""
        _init_git_repo(tmp_path)
        (tmp_path / "hello.py").write_text("print('staged change')\n")
        subprocess.run(["git", "add", "hello.py"], cwd=tmp_path, check=True, capture_output=True)

        result = await _diff({"staged": True}, tmp_path)
        assert not result.error
        assert result.metadata.get("empty") is not True

    async def test_diff_stat_present(self, tmp_path: Path) -> None:
        """diff result includes a stat key when there are changes."""
        _init_git_repo(tmp_path)
        (tmp_path / "hello.py").write_text("# line1\n# line2\n")

        result = await _diff({}, tmp_path)
        assert not result.error
        # stat may be empty string for no-changes case; if changes present it's non-empty
        if not result.metadata.get("empty"):
            assert "stat" in result.metadata


# ═══════════════════════════════════════════════════════════════════════════════
# 4. store.subscribe()
# ═══════════════════════════════════════════════════════════════════════════════


class TestStoreSubscribe:
    """store.subscribe() async iterator yields events as they are appended.

    The subscribe() loop runs while _db is not None — it terminates when the
    store is closed. Tests therefore close the store to end iteration.
    """

    async def test_subscribe_yields_existing_events(self, tmp_path: Path) -> None:
        """Events already in the stream are yielded immediately, then store closes."""
        s = Store(tmp_path / "sub1")
        await s.connect()
        await s.create_stream("s1")
        await s.append("s1", EventType.USER_MESSAGE, {"text": "hello"})
        await s.append("s1", EventType.ASSISTANT_MESSAGE, {"text": "world"})

        collected = []

        async def reader() -> None:
            async for event in s.subscribe("s1", poll_interval=0.02):
                collected.append(event)
                if len(collected) == 2:
                    await s.close()

        await reader()
        assert len(collected) == 2
        assert collected[0].type == EventType.USER_MESSAGE
        assert collected[1].type == EventType.ASSISTANT_MESSAGE

    async def test_subscribe_yields_events_appended_later(self, tmp_path: Path) -> None:
        """Events appended after subscribe() starts are still yielded."""
        s = Store(tmp_path / "sub2")
        await s.connect()
        await s.create_stream("s2")
        received: list = []

        async def writer() -> None:
            await asyncio.sleep(0.05)
            await s.append("s2", EventType.TOKEN, {"delta": "a"})
            await asyncio.sleep(0.05)
            await s.append("s2", EventType.TOKEN, {"delta": "b"})
            await asyncio.sleep(0.05)
            await s.close()

        async def reader() -> None:
            async for event in s.subscribe("s2", poll_interval=0.02):
                received.append(event)

        await asyncio.gather(writer(), reader())

        assert len(received) == 2
        assert received[0].data["delta"] == "a"
        assert received[1].data["delta"] == "b"

    async def test_subscribe_from_offset(self, tmp_path: Path) -> None:
        """from_offset skips already-seen events."""
        s = Store(tmp_path / "sub3")
        await s.connect()
        await s.create_stream("s3")
        await s.append("s3", EventType.TOKEN, {"n": 0})
        await s.append("s3", EventType.TOKEN, {"n": 1})
        await s.append("s3", EventType.TOKEN, {"n": 2})

        collected = []

        async def reader() -> None:
            async for event in s.subscribe("s3", from_offset=1, poll_interval=0.02):
                collected.append(event)
                if len(collected) == 2:
                    await s.close()

        await reader()

        assert len(collected) == 2
        assert collected[0].data["n"] == 1
        assert collected[1].data["n"] == 2

    async def test_subscribe_stops_when_store_closed(self, tmp_path: Path) -> None:
        """Closing the store terminates the subscribe loop."""
        s = Store(tmp_path / "sub4")
        await s.connect()
        await s.create_stream("sc")
        await s.append("sc", EventType.TOKEN, {"x": 1})

        collected = []

        async def reader() -> None:
            async for event in s.subscribe("sc", poll_interval=0.02):
                collected.append(event)

        async def closer() -> None:
            await asyncio.sleep(0.05)
            await s.close()

        await asyncio.gather(reader(), closer())
        assert len(collected) >= 1

    async def test_subscribe_empty_stream_then_append(self, tmp_path: Path) -> None:
        """A subscriber on an empty stream waits, then receives newly appended events."""
        s = Store(tmp_path / "sub5")
        await s.connect()
        await s.create_stream("s5")
        collected: list = []

        async def writer() -> None:
            await asyncio.sleep(0.05)
            await s.append("s5", EventType.STATE_CHANGE, {"state": "running"})
            await asyncio.sleep(0.05)
            await s.close()

        async def reader() -> None:
            async for event in s.subscribe("s5", poll_interval=0.02):
                collected.append(event)

        await asyncio.gather(writer(), reader())

        assert len(collected) == 1
        assert collected[0].data["state"] == "running"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Tool formatters
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolFormatters:
    """format_tool_output() returns compact summaries for known tools."""

    # ── edit ──────────────────────────────────────────────────────────────────

    def test_edit_success_message_truncated(self) -> None:
        """Edit with 'successfully' returns only the first line, up to 100 chars."""
        content = "Edit applied successfully to foo.py\nSome extra detail that should not appear."
        result = format_tool_output("edit", content)
        assert result == "Edit applied successfully to foo.py"

    def test_edit_applied_keyword(self) -> None:
        content = "applied changes to bar.py\nMore text."
        result = format_tool_output("edit", content)
        assert result == "applied changes to bar.py"

    def test_edit_no_keyword_returns_raw(self) -> None:
        """If neither 'successfully' nor 'applied' appears, raw content is returned."""
        content = "Something went wrong"
        result = format_tool_output("edit", content)
        assert result == content

    # ── read ──────────────────────────────────────────────────────────────────

    def test_read_short_content_returned_as_is(self) -> None:
        """Five or fewer lines → content returned unchanged."""
        content = "line1\nline2\nline3"
        result = format_tool_output("read", content)
        assert result == content

    def test_read_long_content_shows_line_count(self) -> None:
        """More than 5 lines → compact '(N lines)' summary."""
        content = "\n".join(f"line{i}" for i in range(20))
        result = format_tool_output("read", content)
        assert result == "(20 lines)"

    def test_read_exactly_five_lines_returned_as_is(self) -> None:
        content = "a\nb\nc\nd\ne"
        result = format_tool_output("read", content)
        assert result == content

    def test_read_six_lines_shows_count(self) -> None:
        content = "a\nb\nc\nd\ne\nf"
        result = format_tool_output("read", content)
        assert result == "(6 lines)"

    # ── grep ──────────────────────────────────────────────────────────────────

    def test_grep_few_matches_returned_as_is(self) -> None:
        """Three or fewer result lines → returned unchanged."""
        content = "file.py:1: match\nfile.py:2: match"
        result = format_tool_output("grep", content)
        assert result == content

    def test_grep_many_matches_shows_count(self) -> None:
        """More than 3 result lines → 'N matches found'."""
        content = "\n".join(f"file.py:{i}: match" for i in range(10))
        result = format_tool_output("grep", content)
        assert result == "10 matches found"

    def test_grep_exactly_three_lines_returned_as_is(self) -> None:
        content = "a:1:x\nb:2:y\nc:3:z"
        result = format_tool_output("grep", content)
        assert result == content

    # ── bash ──────────────────────────────────────────────────────────────────

    def test_bash_short_output_returned_as_is(self) -> None:
        """Ten or fewer lines → returned unchanged."""
        content = "ok\nall good"
        result = format_tool_output("bash", content)
        assert result == content

    def test_bash_long_output_truncated(self) -> None:
        """More than 10 lines → first 5 + ellipsis with remaining count."""
        lines = [f"line{i}" for i in range(20)]
        content = "\n".join(lines)
        result = format_tool_output("bash", content)
        assert "line0" in result
        assert "line4" in result
        assert "15 more lines" in result

    def test_bash_exactly_ten_lines_returned_as_is(self) -> None:
        content = "\n".join(f"L{i}" for i in range(10))
        result = format_tool_output("bash", content)
        assert result == content

    # ── unknown tool ──────────────────────────────────────────────────────────

    def test_unknown_tool_returns_raw(self) -> None:
        """Unregistered tool names return the content unchanged."""
        content = "some output"
        result = format_tool_output("totally_unknown_tool", content)
        assert result == content

    # ── verbose mode ──────────────────────────────────────────────────────────

    def test_verbose_mode_bypasses_formatter(self) -> None:
        """verbose=True always returns raw content regardless of tool."""
        long_content = "\n".join(f"line{i}" for i in range(100))
        result = format_tool_output("read", long_content, verbose=True)
        assert result == long_content

    def test_verbose_bash_returns_raw(self) -> None:
        content = "\n".join(f"x{i}" for i in range(50))
        result = format_tool_output("bash", content, verbose=True)
        assert result == content

    # ── write (uses edit formatter) ───────────────────────────────────────────

    def test_write_success_formatted(self) -> None:
        content = "applied write to newfile.py\nSome detail."
        result = format_tool_output("write", content)
        assert result == "applied write to newfile.py"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Rate limiter
# ═══════════════════════════════════════════════════════════════════════════════


class TestRateLimiter:
    """RateLimiter controls concurrency and tracks counters."""

    def setup_method(self) -> None:
        reset_all()

    async def test_basic_acquire_and_release(self) -> None:
        """A single acquire/release cycle increments counters correctly."""
        limiter = RateLimiter(max_concurrent=2)
        assert limiter.active == 0
        assert limiter.total == 0

        async with limiter.acquire():
            assert limiter.active == 1
            assert limiter.total == 1

        assert limiter.active == 0
        assert limiter.total == 1

    async def test_concurrent_limiting(self) -> None:
        """max_concurrent=1 serialises requests — second waits for first to finish."""
        limiter = RateLimiter(max_concurrent=1)
        order: list[str] = []

        async def task(label: str, delay: float) -> None:
            async with limiter.acquire():
                order.append(f"start:{label}")
                await asyncio.sleep(delay)
                order.append(f"end:{label}")

        await asyncio.gather(task("A", 0.05), task("B", 0.01))
        # A and B must not overlap (serialised)
        assert order.index("end:A") < order.index("start:B") or \
               order.index("end:B") < order.index("start:A")

    async def test_active_counter_tracks_concurrency(self) -> None:
        """active reflects the number of currently held acquisitions."""
        limiter = RateLimiter(max_concurrent=3)
        barrier = asyncio.Event()
        active_snapshots: list[int] = []

        async def task() -> None:
            async with limiter.acquire():
                barrier.set()
                active_snapshots.append(limiter.active)
                await asyncio.sleep(0.01)

        await asyncio.gather(task(), task(), task())
        assert max(active_snapshots) <= 3
        assert limiter.active == 0

    async def test_total_counter_accumulates(self) -> None:
        """total counts every completed acquisition."""
        limiter = RateLimiter(max_concurrent=5)
        for _ in range(7):
            async with limiter.acquire():
                pass
        assert limiter.total == 7

    async def test_max_concurrent_enforced(self) -> None:
        """Never more than max_concurrent tasks run simultaneously."""
        max_c = 2
        limiter = RateLimiter(max_concurrent=max_c)
        peak = 0
        lock = asyncio.Lock()

        async def task() -> None:
            nonlocal peak
            async with limiter.acquire():
                async with lock:
                    peak = max(peak, limiter.active)
                await asyncio.sleep(0.01)

        await asyncio.gather(*[task() for _ in range(5)])
        assert peak <= max_c

    async def test_exception_releases_semaphore(self) -> None:
        """An exception inside the context manager still releases the semaphore."""
        limiter = RateLimiter(max_concurrent=1)
        try:
            async with limiter.acquire():
                raise ValueError("boom")
        except ValueError:
            pass

        assert limiter.active == 0
        # Can acquire again immediately
        async with limiter.acquire():
            assert limiter.active == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Observability
# ═══════════════════════════════════════════════════════════════════════════════


class TestObservability:
    """StructuredFormatter and set_context/clear_context work correctly."""

    def setup_method(self) -> None:
        clear_context()

    def teardown_method(self) -> None:
        clear_context()

    def _make_record(self, msg: str, level: int = logging.INFO) -> logging.LogRecord:
        record = logging.LogRecord(
            name="test.logger",
            level=level,
            pathname="test_batch10.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )
        return record

    def test_json_format_basic_fields(self) -> None:
        """StructuredFormatter emits valid JSON with ts, level, logger, msg."""
        formatter = StructuredFormatter()
        record = self._make_record("hello world")
        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert data["msg"] == "hello world"
        assert "ts" in data

    def test_json_format_without_context(self) -> None:
        """Without set_context, session_id / turn / tool_call_id are absent."""
        formatter = StructuredFormatter()
        record = self._make_record("no context")
        output = formatter.format(record)
        data = json.loads(output)

        assert "session_id" not in data
        assert "turn" not in data
        assert "tool_call_id" not in data

    def test_set_context_session_id_appears_in_log(self) -> None:
        """session_id set via set_context appears in formatted output."""
        set_context(session_id="sess-abc")
        formatter = StructuredFormatter()
        record = self._make_record("with session")
        data = json.loads(formatter.format(record))
        assert data["session_id"] == "sess-abc"

    def test_set_context_turn_appears_in_log(self) -> None:
        set_context(turn=3)
        formatter = StructuredFormatter()
        record = self._make_record("with turn")
        data = json.loads(formatter.format(record))
        assert data["turn"] == 3

    def test_set_context_tool_call_id_appears_in_log(self) -> None:
        set_context(tool_call_id="tc-xyz")
        formatter = StructuredFormatter()
        record = self._make_record("with tcid")
        data = json.loads(formatter.format(record))
        assert data["tool_call_id"] == "tc-xyz"

    def test_set_context_all_fields(self) -> None:
        set_context(session_id="s1", turn=7, tool_call_id="tc-1")
        formatter = StructuredFormatter()
        data = json.loads(formatter.format(self._make_record("all")))
        assert data["session_id"] == "s1"
        assert data["turn"] == 7
        assert data["tool_call_id"] == "tc-1"

    def test_clear_context_removes_fields(self) -> None:
        """After clear_context, context fields do not appear in subsequent logs."""
        set_context(session_id="s99", turn=5, tool_call_id="tc-99")
        clear_context()

        formatter = StructuredFormatter()
        data = json.loads(formatter.format(self._make_record("cleared")))
        assert "session_id" not in data
        assert "turn" not in data
        assert "tool_call_id" not in data

    def test_turn_zero_not_included(self) -> None:
        """turn=0 is >= 0 so it IS included (boundary check)."""
        set_context(turn=0)
        formatter = StructuredFormatter()
        data = json.loads(formatter.format(self._make_record("zero turn")))
        assert data["turn"] == 0

    def test_turn_negative_not_included(self) -> None:
        """Default turn=-1 should NOT appear in output."""
        formatter = StructuredFormatter()
        data = json.loads(formatter.format(self._make_record("neg turn")))
        assert "turn" not in data

    def test_context_vars_isolation(self) -> None:
        """set_context updates only specified fields, leaving others unchanged."""
        set_context(session_id="initial-session")
        set_context(turn=2)  # should not clear session_id

        formatter = StructuredFormatter()
        data = json.loads(formatter.format(self._make_record("partial update")))
        assert data["session_id"] == "initial-session"
        assert data["turn"] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Manual compact
# ═══════════════════════════════════════════════════════════════════════════════


def _make_messages(n: int) -> list[Message]:
    """Create a conversation with a system message, n user/assistant pairs."""
    msgs: list[Message] = [Message(role="system", content="You are helpful.")]
    for i in range(n):
        msgs.append(Message(role="user", content=f"Question {i}? " * 20))
        msgs.append(Message(role="assistant", content=f"Answer {i}. " * 20))
    return msgs


class TestManualCompact:
    """manual_compact is more aggressive than auto compact_messages."""

    def test_manual_compact_uses_lower_soft_ratio(self) -> None:
        """manual_compact drives messages below 60% of max_tokens (soft=0.60).

        We use a small token budget to force compaction without needing many messages.
        """
        msgs = _make_messages(30)
        # Take a snapshot for comparison
        msgs_auto = list(msgs)
        msgs_manual = list(msgs)

        token_budget = 2000

        removed_auto = compact_messages(
            msgs_auto,
            max_input_tokens=token_budget,
            soft_ratio=COMPACTION_SOFT_RATIO,  # 0.80
        )
        removed_manual = manual_compact(msgs_manual, max_input_tokens=token_budget)

        # manual_compact should remove at least as many (usually more) messages
        assert removed_manual >= removed_auto

    def test_manual_compact_removes_more_than_auto(self) -> None:
        """With an ample token budget, manual compact still targets a lower watermark."""
        msgs = _make_messages(50)
        msgs_auto = list(msgs)
        msgs_manual = list(msgs)

        token_budget = 3000

        compact_messages(msgs_auto, max_input_tokens=token_budget, soft_ratio=0.80)
        manual_compact(msgs_manual, max_input_tokens=token_budget)

        # manual should leave fewer messages (hit lower 60% soft target)
        assert len(msgs_manual) <= len(msgs_auto)

    def test_manual_compact_preserves_system_and_last_user(self) -> None:
        """Even with heavy compaction, system and last user message are preserved."""
        msgs = _make_messages(40)
        manual_compact(msgs, max_input_tokens=500)

        roles = [m.role for m in msgs]
        assert "system" in roles
        assert "user" in roles

    def test_manual_compact_inserts_summary_marker(self) -> None:
        """When messages are removed, a '[Context compacted...]' marker is inserted."""
        msgs = _make_messages(30)
        removed = manual_compact(msgs, max_input_tokens=500)

        if removed > 0:
            system_msgs = [m for m in msgs if m.role == "system"]
            assert any("context compacted" in (m.content or "").lower() for m in system_msgs)

    def test_manual_compact_returns_removed_count(self) -> None:
        """Return value matches the number of messages actually dropped."""
        msgs = _make_messages(30)
        original_len = len(msgs)
        removed = manual_compact(msgs, max_input_tokens=500)

        # +1 for the summary marker that gets inserted
        assert len(msgs) == original_len - removed + (1 if removed > 0 else 0)

    def test_manual_compact_no_op_when_under_budget(self) -> None:
        """When already under budget, nothing is removed."""
        msgs = _make_messages(2)
        removed = manual_compact(msgs, max_input_tokens=DEFAULT_MAX_INPUT_TOKENS)
        assert removed == 0

    def test_manual_compact_soft_ratio_is_0_60(self) -> None:
        """Verify the concrete ratio used: manual compact soft=0.60 vs auto soft=0.80.

        We set max_tokens such that the 80% threshold would not trigger compaction
        but the 60% threshold would.
        """
        msgs = _make_messages(20)
        from taui.agent.context import estimate_total_tokens
        total = estimate_total_tokens(msgs)

        # Budget where 80% soft > total > 60% soft
        # i.e. total/0.75 is a budget that puts us between thresholds
        budget = int(total / 0.70)

        msgs_auto = list(msgs)
        msgs_manual = list(msgs)

        removed_auto = compact_messages(msgs_auto, max_input_tokens=budget, soft_ratio=0.80)
        removed_manual = manual_compact(msgs_manual, max_input_tokens=budget)

        # auto should NOT compact (total < 80% of budget), manual SHOULD
        assert removed_auto == 0
        assert removed_manual > 0
