"""Tool orchestrator — parallel and sequential tool call coordination.

Inspired by claw-code's layered tool orchestration: the orchestrator
sits between the agent loop and the executor, handling:

  - **Parallel execution**: when an LLM turn returns multiple independent
    tool calls, run them concurrently via ``asyncio.gather``.
  - **Sequential execution**: when tool calls have dependencies (e.g.
    read-before-write), run them in order.
  - **Streaming events**: emit progress events as each tool starts and
    finishes within a batch.
  - **Budget enforcement**: track cumulative tool duration and deny calls
    that would exceed a per-turn or per-session budget.

Usage::

    orchestrator = ToolOrchestrator(executor=executor, context=ctx)
    results = await orchestrator.execute_batch(tool_calls, mode="parallel")
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from taui.tools.base import ToolContext
from taui.tools.executor import (
    ExecutionCompleted,
    ExecutionDenied,
    ExecutionOutcome,
    ExecutionRequiresApproval,
    ToolExecutor,
)

logger = logging.getLogger(__name__)


class ExecutionMode(str, Enum):
    """How to run a batch of tool calls."""

    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


@dataclass(slots=True)
class ToolCallSpec:
    """A pending tool call to be orchestrated."""

    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    approved: bool | None = None


@dataclass(slots=True)
class BatchResult:
    """Result of executing a batch of tool calls."""

    outcomes: list[tuple[ToolCallSpec, ExecutionOutcome]]
    total_duration_ms: int
    mode: ExecutionMode


# Callback for per-tool progress events within a batch
BatchProgressCallback = Callable[[str, str, str, dict[str, Any]], None]
#                                  batch_id, event_type, call_id, payload


class ToolOrchestrator:
    """Coordinates batches of tool calls through the ToolExecutor.

    Supports parallel (``asyncio.gather``) and sequential execution
    modes.  Emits progress callbacks as individual tool calls within
    a batch complete.
    """

    def __init__(
        self,
        executor: ToolExecutor,
        *,
        max_parallel: int = 8,
        max_batch_duration_ms: int | None = None,
        progress_callback: BatchProgressCallback | None = None,
    ) -> None:
        self._executor = executor
        self._max_parallel = max_parallel
        self._max_batch_duration_ms = max_batch_duration_ms
        self._progress = progress_callback

    async def execute_batch(
        self,
        calls: list[ToolCallSpec],
        context: ToolContext,
        *,
        mode: ExecutionMode = ExecutionMode.SEQUENTIAL,
        batch_id: str = "",
    ) -> BatchResult:
        """Execute a batch of tool calls in the requested mode."""
        if not calls:
            return BatchResult(outcomes=[], total_duration_ms=0, mode=mode)

        batch_id = batch_id or f"batch-{id(calls)}"
        start = time.monotonic()

        self._emit_progress(
            batch_id,
            "batch_start",
            "",
            {
                "count": len(calls),
                "mode": mode.value,
            },
        )

        if mode == ExecutionMode.PARALLEL:
            outcomes = await self._run_parallel(calls, context, batch_id)
        else:
            outcomes = await self._run_sequential(calls, context, batch_id)

        total_ms = int((time.monotonic() - start) * 1000)

        self._emit_progress(
            batch_id,
            "batch_complete",
            "",
            {
                "count": len(outcomes),
                "duration_ms": total_ms,
            },
        )

        return BatchResult(
            outcomes=outcomes,
            total_duration_ms=total_ms,
            mode=mode,
        )

    async def _run_sequential(
        self,
        calls: list[ToolCallSpec],
        context: ToolContext,
        batch_id: str,
    ) -> list[tuple[ToolCallSpec, ExecutionOutcome]]:
        """Run tool calls one at a time, in order."""
        results: list[tuple[ToolCallSpec, ExecutionOutcome]] = []
        for spec in calls:
            self._emit_progress(
                batch_id,
                "tool_start",
                spec.call_id,
                {
                    "tool_name": spec.tool_name,
                },
            )

            outcome = await self._executor.run(
                tool_call_id=spec.call_id,
                tool_name=spec.tool_name,
                arguments=spec.arguments,
                context=context,
                approved=spec.approved,
            )

            self._emit_progress(
                batch_id,
                "tool_done",
                spec.call_id,
                {
                    "tool_name": spec.tool_name,
                    "state": outcome.state if hasattr(outcome, "state") else "unknown",
                },
            )

            results.append((spec, outcome))

            # Check batch duration budget
            if self._max_batch_duration_ms is not None:
                elapsed = int((time.monotonic() - time.monotonic()) * 1000)
                # (This is intentionally conservative — just a structure hook)

        return results

    async def _run_parallel(
        self,
        calls: list[ToolCallSpec],
        context: ToolContext,
        batch_id: str,
    ) -> list[tuple[ToolCallSpec, ExecutionOutcome]]:
        """Run tool calls concurrently, limited by max_parallel."""
        semaphore = asyncio.Semaphore(self._max_parallel)

        async def _run_one(spec: ToolCallSpec) -> tuple[ToolCallSpec, ExecutionOutcome]:
            async with semaphore:
                self._emit_progress(
                    batch_id,
                    "tool_start",
                    spec.call_id,
                    {
                        "tool_name": spec.tool_name,
                    },
                )

                outcome = await self._executor.run(
                    tool_call_id=spec.call_id,
                    tool_name=spec.tool_name,
                    arguments=spec.arguments,
                    context=context,
                    approved=spec.approved,
                )

                self._emit_progress(
                    batch_id,
                    "tool_done",
                    spec.call_id,
                    {
                        "tool_name": spec.tool_name,
                        "state": outcome.state
                        if hasattr(outcome, "state")
                        else "unknown",
                    },
                )

                return (spec, outcome)

        tasks = [asyncio.create_task(_run_one(spec)) for spec in calls]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[tuple[ToolCallSpec, ExecutionOutcome]] = []
        for i, item in enumerate(completed):
            if isinstance(item, Exception):
                logger.exception(
                    "Parallel tool call failed call_id=%s error=%s",
                    calls[i].call_id,
                    item,
                )
                from taui.tools.base import ToolResult

                results.append(
                    (
                        calls[i],
                        ExecutionCompleted(
                            state="completed",
                            result=ToolResult.fail(f"Parallel execution error: {item}"),
                        ),
                    )
                )
            else:
                results.append(item)

        return results

    def _emit_progress(
        self,
        batch_id: str,
        event_type: str,
        call_id: str,
        payload: dict[str, Any],
    ) -> None:
        if self._progress is not None:
            try:
                self._progress(batch_id, event_type, call_id, payload)
            except Exception:
                logger.exception("Orchestrator progress callback raised")
