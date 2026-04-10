"""File-based logging to ~/.taui/logs/ for persistent, referenceable logs.

Writes detailed (DEBUG-level) log files with daily rotation and automatic
cleanup of old files.  The console handler continues to respect the user's
TAUI_LOG_LEVEL — file logging captures *everything* so you can always go
back and trace what happened.

Log location:
    ~/.taui/logs/taui-YYYY-MM-DD.log

Override with the ``TAUI_LOG_DIR`` environment variable.

Each line uses a structured, grep-friendly format::

    2026-04-09 14:23:01.123 | DEBUG    | taui.agent.runner | AgentRunner starting agent_id=abc …
"""

from __future__ import annotations

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Final

_LOG_DIR_ENV: Final[str] = "TAUI_LOG_DIR"
_DEFAULT_LOG_DIR: Final[Path] = Path.home() / ".taui" / "logs"
_LOG_FILENAME: Final[str] = "taui.log"
_FILE_FORMAT: Final[str] = (
    "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s | %(message)s"
)
_FILE_DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"
_ROTATION_WHEN: Final[str] = "midnight"
_ROTATION_BACKUP_COUNT: Final[int] = 30  # keep 30 days of logs


def get_log_dir() -> Path:
    """Return the log directory, respecting the TAUI_LOG_DIR env override."""
    env_dir = os.getenv(_LOG_DIR_ENV)
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    return _DEFAULT_LOG_DIR


def create_file_handler(
    log_dir: Path | None = None,
    level: int = logging.DEBUG,
) -> TimedRotatingFileHandler:
    """Create a TimedRotatingFileHandler that writes to ``log_dir/taui.log``.

    The handler rotates at midnight and keeps ``_ROTATION_BACKUP_COUNT`` days
    of history.  Rotated files are named ``taui.log.YYYY-MM-DD``.

    Parameters
    ----------
    log_dir:
        Directory for log files.  Defaults to :func:`get_log_dir`.
    level:
        Logging level for the file handler (default: DEBUG).

    Returns
    -------
    TimedRotatingFileHandler
        Ready-to-add handler instance.
    """
    resolved_dir = log_dir or get_log_dir()
    resolved_dir.mkdir(parents=True, exist_ok=True)

    log_path = resolved_dir / _LOG_FILENAME

    handler = TimedRotatingFileHandler(
        filename=str(log_path),
        when=_ROTATION_WHEN,
        backupCount=_ROTATION_BACKUP_COUNT,
        encoding="utf-8",
        utc=False,
    )
    handler.setLevel(level)

    formatter = logging.Formatter(
        fmt=_FILE_FORMAT,
        datefmt=_FILE_DATE_FORMAT,
    )
    handler.setFormatter(formatter)
    handler.namer = _log_namer
    return handler


def _log_namer(default_name: str) -> str:
    """Custom namer so rotated files look like ``taui.log.2026-04-09``
    instead of the default ``taui.log.2026-04-09`` with no suffix.
    """
    # The default TimedRotatingFileHandler already uses this pattern
    # for ``when="midnight"``.  We keep a namer hook in case we want to
    # customise later (e.g. add .gz compression).
    return default_name


def get_latest_log_path() -> Path | None:
    """Return the path to the current (today's) log file, or None if it
    doesn't exist yet."""
    log_path = get_log_dir() / _LOG_FILENAME
    return log_path if log_path.exists() else None


def list_log_files() -> list[Path]:
    """Return all log files sorted newest-first."""
    log_dir = get_log_dir()
    if not log_dir.exists():
        return []
    files = sorted(
        log_dir.glob("taui.log*"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return files
