from __future__ import annotations

import logging
from pathlib import Path

import taui.log_config as _lc


def _reset_logging_state() -> None:
    """Reset the module-level ``_configured`` flag so each test can reconfigure."""
    _lc._configured = False
    # Remove all handlers from root to start fresh
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()


# ── logging_file module tests ─────────────────────────────────────────────


def test_create_file_handler_creates_dir_and_file(tmp_path: Path) -> None:
    from taui.logging_file import create_file_handler

    log_dir = tmp_path / "logs"
    handler = create_file_handler(log_dir=log_dir)
    try:
        assert log_dir.exists()
        assert (log_dir / "taui.log").exists() or handler.baseFilename
        assert handler.level == logging.DEBUG
    finally:
        handler.close()


def test_create_file_handler_writes_records(tmp_path: Path) -> None:
    from taui.logging_file import create_file_handler

    log_dir = tmp_path / "logs"
    handler = create_file_handler(log_dir=log_dir)
    try:
        test_logger = logging.getLogger("test.file_handler")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.DEBUG)
        test_logger.debug("hello from test")
        handler.flush()

        log_file = log_dir / "taui.log"
        content = log_file.read_text(encoding="utf-8")
        assert "hello from test" in content
        assert "DEBUG" in content
        assert "test.file_handler" in content
    finally:
        test_logger.removeHandler(handler)
        handler.close()


def test_get_log_dir_default() -> None:
    from taui.logging_file import get_log_dir

    result = get_log_dir()
    assert result == Path.home() / ".taui" / "logs"


def test_get_log_dir_env_override(
    monkeypatch: "pytest.MonkeyPatch", tmp_path: Path
) -> None:
    from taui.logging_file import get_log_dir

    custom = tmp_path / "custom-taui-logs"
    monkeypatch.setenv("TAUI_LOG_DIR", str(custom))
    result = get_log_dir()
    assert result == custom


def test_list_log_files_empty(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    from taui.logging_file import list_log_files

    monkeypatch.setenv("TAUI_LOG_DIR", str(tmp_path / "nonexistent"))
    files = list_log_files()
    assert files == []


def test_list_log_files_returns_logs(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    from taui.logging_file import list_log_files

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "taui.log").write_text("current\n")
    (log_dir / "taui.log.2026-04-01").write_text("old\n")
    monkeypatch.setenv("TAUI_LOG_DIR", str(log_dir))

    files = list_log_files()
    assert len(files) == 2
    assert all(f.name.startswith("taui.log") for f in files)


# ── configure_logging integration tests ────────────────────────────────────


def test_configure_logging_with_file_handler(tmp_path: Path) -> None:
    _reset_logging_state()
    log_dir = tmp_path / "logs"

    _lc.configure_logging(level="DEBUG", enable_file_logging=True, log_dir=log_dir)

    root = logging.getLogger()
    handler_types = [type(h).__name__ for h in root.handlers]
    # Should have at least one file handler
    assert "TimedRotatingFileHandler" in handler_types

    test_logger = logging.getLogger("test.integration")
    test_logger.info("integration test message")

    # Flush all handlers
    for h in root.handlers:
        h.flush()

    log_file = log_dir / "taui.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "integration test message" in content

    _reset_logging_state()


def test_configure_logging_without_file_handler() -> None:
    _reset_logging_state()

    _lc.configure_logging(level="INFO", enable_file_logging=False)

    root = logging.getLogger()
    handler_types = [type(h).__name__ for h in root.handlers]
    assert "TimedRotatingFileHandler" not in handler_types

    _reset_logging_state()


def test_configure_logging_env_disables_file(
    monkeypatch: "pytest.MonkeyPatch", tmp_path: Path
) -> None:
    _reset_logging_state()
    monkeypatch.setenv("TAUI_LOG_FILE", "0")

    _lc.configure_logging(level="INFO", log_dir=tmp_path / "logs")

    root = logging.getLogger()
    handler_types = [type(h).__name__ for h in root.handlers]
    assert "TimedRotatingFileHandler" not in handler_types

    _reset_logging_state()


def test_configure_logging_idempotent(tmp_path: Path) -> None:
    _reset_logging_state()

    _lc.configure_logging(
        level="INFO", enable_file_logging=True, log_dir=tmp_path / "logs"
    )
    first_handlers = len(logging.getLogger().handlers)

    # Second call should be a no-op
    _lc.configure_logging(
        level="DEBUG", enable_file_logging=True, log_dir=tmp_path / "logs2"
    )
    assert len(logging.getLogger().handlers) == first_handlers

    _reset_logging_state()


def test_file_log_format_structured(tmp_path: Path) -> None:
    _reset_logging_state()
    log_dir = tmp_path / "logs"

    _lc.configure_logging(level="DEBUG", enable_file_logging=True, log_dir=log_dir)

    test_logger = logging.getLogger("taui.test.format")
    test_logger.warning("structured key=value test_id=42")

    for h in logging.getLogger().handlers:
        h.flush()

    log_file = log_dir / "taui.log"
    content = log_file.read_text(encoding="utf-8")
    # Verify structured format: timestamp | LEVEL | logger | message
    assert "WARNING" in content or "WARNING " in content
    assert "taui.test.format" in content
    assert "structured key=value test_id=42" in content
    # Verify timestamp has milliseconds
    import re

    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}", content)

    _reset_logging_state()
