from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Final

_DEFAULT_LEVEL: Final[str] = "INFO"
_RICH_FORMAT: Final[str] = "%(name)s | %(message)s"
_FALLBACK_FORMAT: Final[str] = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DEFAULT_DATE_FORMAT: Final[str] = "[%X]"

_configured = False


def configure_logging(
    level: str | int | None = None,
    *,
    enable_file_logging: bool = True,
    log_dir: Path | None = None,
) -> None:
    """Configure process-wide logging once.

    Parameters
    ----------
    level:
        Console log level.  Defaults to ``TAUI_LOG_LEVEL`` env or ``INFO``.
    enable_file_logging:
        When True (the default), attach a ``TimedRotatingFileHandler`` that
        writes DEBUG-level logs to ``~/.taui/logs/taui.log``.  Disabled
        automatically when ``TAUI_LOG_FILE=0`` is set, or can be turned off
        programmatically (useful in tests).
    log_dir:
        Override the file-log directory.  Defaults to ``~/.taui/logs/`` or
        whatever ``TAUI_LOG_DIR`` specifies.
    """
    global _configured
    if _configured:
        return

    configured_level = level or os.getenv("TAUI_LOG_LEVEL", _DEFAULT_LEVEL)
    numeric_level = _to_numeric_level(configured_level)

    handlers: list[logging.Handler] = []

    # ── Console handler (Rich when available, plain fallback) ─────────
    try:
        from rich.console import Console
        from rich.logging import RichHandler

        console_handler = RichHandler(
            console=Console(stderr=True),
            show_path=False,
            rich_tracebacks=True,
            markup=False,
        )
        console_handler.setFormatter(
            logging.Formatter(_RICH_FORMAT, datefmt=_DEFAULT_DATE_FORMAT)
        )
        handlers.append(console_handler)
    except ModuleNotFoundError:
        fallback_handler = logging.StreamHandler()
        fallback_handler.setFormatter(
            logging.Formatter(_FALLBACK_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
        )
        handlers.append(fallback_handler)

    # ── File handler (detailed, DEBUG-level, rotated daily) ───────────
    if enable_file_logging and os.getenv("TAUI_LOG_FILE", "1") != "0":
        try:
            from taui.logging_file import create_file_handler

            file_handler = create_file_handler(log_dir=log_dir, level=logging.DEBUG)
            handlers.append(file_handler)
        except Exception:
            # Never let file logging setup break startup
            pass

    # ── Apply configuration ───────────────────────────────────────────
    # Use the lowest level between console and file so root logger captures
    # everything, then individual handlers filter by their own level.
    root_level = (
        min(numeric_level, logging.DEBUG) if len(handlers) > 1 else numeric_level
    )
    logging.basicConfig(level=root_level, handlers=handlers)

    # Ensure console handler respects the user's chosen level even when
    # root is DEBUG (for the file handler).
    for h in handlers:
        if not isinstance(h, logging.FileHandler):
            h.setLevel(numeric_level)

    _configured = True


def _to_numeric_level(value: str | int) -> int:
    if isinstance(value, int):
        return value
    candidate = value.strip().upper()
    numeric_level = logging.getLevelName(candidate)
    if isinstance(numeric_level, int):
        return numeric_level
    return logging.INFO
