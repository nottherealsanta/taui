"""Tests for FileTracker."""

from __future__ import annotations

import time
from pathlib import Path

from taui.tools.file_tracker import FileTracker


def _write(path: Path, content: str) -> None:
    path.write_text(content)


def test_record_and_check_no_change(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    _write(f, "hello")
    tracker = FileTracker()
    tracker.record_read(f)
    assert tracker.check_before_write(f) is None


def test_check_after_external_modification(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    _write(f, "original")
    tracker = FileTracker()
    tracker.record_read(f)
    # Ensure mtime changes
    time.sleep(0.01)
    _write(f, "modified by someone else")
    result = tracker.check_before_write(f)
    assert result is not None
    assert "modified externally" in result


def test_check_never_read_existing_file(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    _write(f, "existing")
    tracker = FileTracker()
    result = tracker.check_before_write(f)
    assert result is not None
    assert "has not been read" in result


def test_check_never_read_new_file(tmp_path: Path) -> None:
    f = tmp_path / "new_file.txt"
    assert not f.exists()
    tracker = FileTracker()
    assert tracker.check_before_write(f) is None


def test_check_after_external_deletion(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    _write(f, "content")
    tracker = FileTracker()
    tracker.record_read(f)
    f.unlink()
    result = tracker.check_before_write(f)
    assert result is not None
    assert "deleted" in result


def test_update_after_write(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    _write(f, "v1")
    tracker = FileTracker()
    tracker.record_read(f)
    # Simulate write
    time.sleep(0.01)
    _write(f, "v2")
    tracker.update_after_write(f)
    assert tracker.check_before_write(f) is None


def test_mtime_change_but_same_content(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    _write(f, "same content")
    tracker = FileTracker()
    tracker.record_read(f)
    # touch: change mtime without changing content
    time.sleep(0.01)
    f.write_text("same content")
    assert tracker.check_before_write(f) is None


def test_read_then_read_then_edit(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    _write(f, "data")
    tracker = FileTracker()
    tracker.record_read(f)
    tracker.record_read(f)  # second read updates snapshot
    assert tracker.check_before_write(f) is None


def test_clear_resets_state(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    _write(f, "data")
    tracker = FileTracker()
    tracker.record_read(f)
    tracker.clear()
    # After clear, file is treated as never read
    result = tracker.check_before_write(f)
    assert result is not None
    assert "has not been read" in result


def test_tracked_files_list(tmp_path: Path) -> None:
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    _write(a, "a")
    _write(b, "b")
    tracker = FileTracker()
    assert tracker.tracked_files == []
    tracker.record_read(a)
    assert len(tracker.tracked_files) == 1
    tracker.record_read(b)
    assert len(tracker.tracked_files) == 2
    assert a.resolve() in tracker.tracked_files
    assert b.resolve() in tracker.tracked_files
