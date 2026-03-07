from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import time
from typing import Literal
import asyncio

from taui.tools.base import ToolContext, ToolResult
from taui.tools.registry import ToolRegistry

ExecutionState = Literal["completed", "approval_required", "denied"]


@dataclass(slots=True)
class ExecutionCompleted:
    state: Literal["completed"]
    result: ToolResult


@dataclass(slots=True)
class ExecutionRequiresApproval:
    state: Literal["approval_required"]
    tool_call_id: str
    tool_name: str
    arguments_preview: str
    reason: str


@dataclass(slots=True)
class ExecutionDenied:
    state: Literal["denied"]
    result: ToolResult


ExecutionOutcome = ExecutionCompleted | ExecutionRequiresApproval | ExecutionDenied

logger = logging.getLogger(__name__)


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, default_timeout_sec: int = 120) -> None:
        self._registry = registry
        self._default_timeout_sec = default_timeout_sec

    async def run(
        self,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, object],
        context: ToolContext,
        *,
        approved: bool | None = None,
        timeout_sec: int | None = None,
    ) -> ExecutionOutcome:
        start = time.perf_counter()
        logger.info(
            "Tool execution requested call_id=%s tool=%s approved=%s",
            tool_call_id,
            tool_name,
            approved,
        )
        try:
            tool = self._registry.get(tool_name)
        except ValueError as exc:
            logger.warning(
                "Tool not found call_id=%s tool=%s error=%s", tool_call_id, tool_name, exc
            )
            return ExecutionCompleted(
                state="completed", result=ToolResult.fail(str(exc))
            )

        validation_error = _validate_schema(tool.schema, arguments)
        if validation_error:
            logger.warning(
                "Tool argument validation failed call_id=%s tool=%s error=%s",
                tool_call_id,
                tool_name,
                validation_error,
            )
            return ExecutionCompleted(
                state="completed", result=ToolResult.fail(validation_error)
            )

        decision = context.policy.evaluate(tool_name)
        if decision.decision == "deny":
            logger.warning(
                "Tool denied by policy call_id=%s tool=%s reason=%s",
                tool_call_id,
                tool_name,
                decision.reason,
            )
            return ExecutionDenied(
                state="denied", result=ToolResult.fail(decision.reason)
            )
        if decision.decision == "confirm" and approved is None:
            logger.info(
                "Tool requires approval call_id=%s tool=%s reason=%s",
                tool_call_id,
                tool_name,
                decision.reason,
            )
            return ExecutionRequiresApproval(
                state="approval_required",
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments_preview=_preview(arguments),
                reason=decision.reason,
            )
        if decision.decision == "confirm" and approved is False:
            logger.info("Tool rejected by user call_id=%s tool=%s", tool_call_id, tool_name)
            return ExecutionDenied(
                state="denied",
                result=ToolResult.fail("Tool execution rejected by user."),
            )

        limit = (
            timeout_sec
            or context.policy.bash.default_timeout_sec
            or self._default_timeout_sec
        )
        try:
            logger.debug(
                "Running tool call_id=%s tool=%s timeout_sec=%s",
                tool_call_id,
                tool_name,
                limit,
            )
            result = await asyncio.wait_for(
                tool.execute(arguments, context), timeout=limit
            )
        except TimeoutError:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.warning(
                "Tool timed out call_id=%s tool=%s timeout_sec=%s duration_ms=%s",
                tool_call_id,
                tool_name,
                limit,
                elapsed_ms,
            )
            return ExecutionCompleted(
                state="completed",
                result=ToolResult.fail(
                    f"Tool '{tool_name}' timed out after {limit} seconds.",
                    metadata={
                        "duration_ms": elapsed_ms,
                        "tool_name": tool_name,
                        "arguments_digest": _digest(arguments),
                    },
                ),
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "Tool raised unexpected error call_id=%s tool=%s duration_ms=%s",
                tool_call_id,
                tool_name,
                elapsed_ms,
            )
            return ExecutionCompleted(
                state="completed",
                result=ToolResult.fail(
                    f"Tool '{tool_name}' failed unexpectedly.",
                    metadata={
                        "duration_ms": elapsed_ms,
                        "tool_name": tool_name,
                        "arguments_digest": _digest(arguments),
                        "exception": str(exc),
                    },
                ),
            )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        metadata = dict(result.metadata or {})
        metadata.setdefault("duration_ms", elapsed_ms)
        metadata.setdefault("tool_name", tool_name)
        metadata.setdefault("arguments_digest", _digest(arguments))
        result.metadata = metadata
        logger.info(
            "Tool execution completed call_id=%s tool=%s error=%s duration_ms=%s",
            tool_call_id,
            tool_name,
            result.error,
            elapsed_ms,
        )
        return ExecutionCompleted(state="completed", result=result)


def _preview(arguments: dict[str, object], max_chars: int = 200) -> str:
    payload = json.dumps(arguments, sort_keys=True)
    if len(payload) <= max_chars:
        return payload
    return payload[: max_chars - 3] + "..."


def _digest(arguments: dict[str, object]) -> str:
    payload = json.dumps(arguments, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_schema(
    schema: dict[str, object], arguments: dict[str, object]
) -> str | None:
    if not schema:
        return None
    if schema.get("type") != "object":
        return "Tool schema validation error: only object schemas are supported."

    required = schema.get("required", [])
    if isinstance(required, list):
        for key in required:
            if isinstance(key, str) and key not in arguments:
                return (
                    f"Tool argument validation error: missing required field '{key}'."
                )

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return None

    for field_name, field_schema_raw in properties.items():
        if field_name not in arguments:
            continue
        if not isinstance(field_schema_raw, dict):
            continue
        expected_type = field_schema_raw.get("type")
        if expected_type and not _matches_type(expected_type, arguments[field_name]):
            return (
                "Tool argument validation error: "
                f"field '{field_name}' expected type '{expected_type}'."
            )
    return None


def _matches_type(expected_type: object, value: object) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, dict)
    return True
