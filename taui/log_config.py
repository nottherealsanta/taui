from __future__ import annotations

import logging
import os
from typing import Final

_DEFAULT_LEVEL: Final[str] = "INFO"
_RICH_FORMAT: Final[str] = "%(name)s | %(message)s"
_FALLBACK_FORMAT: Final[str] = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DEFAULT_DATE_FORMAT: Final[str] = "[%X]"

_configured = False


def configure_logging(level: str | int | None = None) -> None:
    """Configure process-wide logging once."""
    global _configured
    if _configured:
        return

    configured_level = level or os.getenv("TAUI_LOG_LEVEL", _DEFAULT_LEVEL)
    numeric_level = _to_numeric_level(configured_level)

    try:
        from rich.console import Console
        from rich.logging import RichHandler

        logging.basicConfig(
            level=numeric_level,
            format=_RICH_FORMAT,
            datefmt=_DEFAULT_DATE_FORMAT,
            handlers=[
                RichHandler(
                    console=Console(stderr=True),
                    show_path=False,
                    rich_tracebacks=True,
                    markup=False,
                )
            ],
        )
    except ModuleNotFoundError:
        logging.basicConfig(
            level=numeric_level,
            format=_FALLBACK_FORMAT,
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    _configured = True


def _to_numeric_level(value: str | int) -> int:
    if isinstance(value, int):
        return value
    candidate = value.strip().upper()
    numeric_level = logging.getLevelName(candidate)
    if isinstance(numeric_level, int):
        return numeric_level
    return logging.INFO
