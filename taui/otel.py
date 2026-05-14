"""Optional OpenTelemetry integration.

Provides span wrappers for agent turns, provider calls, and tool
executions. Requires the opentelemetry-api package (not a hard dep).

Enable via: TAUI_OTEL=1 or config otel_enabled=true.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)

_tracer: Any = None


def _get_tracer() -> Any:
    """Get or create the OpenTelemetry tracer, or None."""
    global _tracer
    if _tracer is not None:
        return _tracer
    try:
        from opentelemetry import trace
        _tracer = trace.get_tracer("taui")
        return _tracer
    except ImportError:
        return None


@asynccontextmanager
async def agent_turn_span(
    *,
    session_id: str = "",
    turn: int = 0,
    model: str = "",
) -> AsyncIterator[Any]:
    """Wrap an agent turn in an OTel span."""
    tracer = _get_tracer()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(
        "agent.turn",
        attributes={
            "session.id": session_id,
            "agent.turn": turn,
            "agent.model": model,
        },
    ) as span:
        yield span


@asynccontextmanager
async def provider_call_span(
    *,
    provider: str = "",
    model: str = "",
    message_count: int = 0,
) -> AsyncIterator[Any]:
    """Wrap a provider LLM call in an OTel span."""
    tracer = _get_tracer()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(
        "provider.create_turn",
        attributes={
            "provider.name": provider,
            "provider.model": model,
            "provider.message_count": message_count,
        },
    ) as span:
        yield span


@asynccontextmanager
async def tool_run_span(
    *,
    tool_name: str = "",
    call_id: str = "",
) -> AsyncIterator[Any]:
    """Wrap a tool execution in an OTel span."""
    tracer = _get_tracer()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(
        "tool.run",
        attributes={
            "tool.name": tool_name,
            "tool.call_id": call_id,
        },
    ) as span:
        yield span


def is_enabled() -> bool:
    """Check if OTel integration is available and enabled."""
    import os
    if os.environ.get("TAUI_OTEL", "").strip() not in ("1", "true"):
        return False
    return _get_tracer() is not None
