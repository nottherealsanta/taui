"""Structured logging with context propagation.

When configured, log records carry session_id, turn number, and tool_call_id
via contextvars. Switch to JSON format with TAUI_LOG_JSON=1.
"""

from __future__ import annotations

import contextvars
import json
import logging
from typing import Any

# ── Context variables ────────────────────────────────────────────────────────

session_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "session_id", default=""
)
turn_var: contextvars.ContextVar[int] = contextvars.ContextVar(
    "turn", default=-1
)
tool_call_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "tool_call_id", default=""
)


def set_context(
    *,
    session_id: str | None = None,
    turn: int | None = None,
    tool_call_id: str | None = None,
) -> None:
    """Set context variables for structured logging."""
    if session_id is not None:
        session_id_var.set(session_id)
    if turn is not None:
        turn_var.set(turn)
    if tool_call_id is not None:
        tool_call_id_var.set(tool_call_id)


def clear_context() -> None:
    """Reset all context variables."""
    session_id_var.set("")
    turn_var.set(-1)
    tool_call_id_var.set("")


# ── JSON formatter ───────────────────────────────────────────────────────────


class StructuredFormatter(logging.Formatter):
    """JSON log formatter that includes context variables."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # Add context vars
        sid = session_id_var.get("")
        if sid:
            entry["session_id"] = sid
        turn = turn_var.get(-1)
        if turn >= 0:
            entry["turn"] = turn
        tcid = tool_call_id_var.get("")
        if tcid:
            entry["tool_call_id"] = tcid

        if record.exc_info and record.exc_info[1]:
            entry["exception"] = str(record.exc_info[1])

        return json.dumps(entry, default=str)


def configure_logging(*, json_format: bool = False, level: int = logging.INFO) -> None:
    """Configure logging with optional JSON output.

    Call once at startup. When json_format=True (or TAUI_LOG_JSON=1),
    all log output uses structured JSON with context variables.
    """
    import os

    if os.environ.get("TAUI_LOG_JSON", "").strip() in ("1", "true"):
        json_format = True

    root = logging.getLogger()
    root.setLevel(level)

    handler = logging.StreamHandler()
    if json_format:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )

    # Remove existing handlers to avoid duplicates
    root.handlers.clear()
    root.addHandler(handler)
