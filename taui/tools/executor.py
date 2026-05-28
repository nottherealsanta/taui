"""Tool executor — policy gate and dispatch layer between the agent loop and tools."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from taui.tools.base import (
    ToolCategory,
    ToolOutputDeltaCallback,
    ToolResult,
    reset_tool_output_delta_callback,
    set_tool_output_delta_callback,
    tool_requires_approval,
)
from taui.tools.registry import ToolRegistry
from taui.tools.truncation import TruncationStore

logger = logging.getLogger(__name__)


# ── Retry config ─────────────────────────────────────────────────────────────

_RETRY_CATEGORIES: frozenset[ToolCategory] = frozenset(
    {ToolCategory.FILE_READ, ToolCategory.SEARCH}
)
_RETRY_DELAYS: tuple[float, ...] = (0.25, 1.0, 4.0)


# ── Policy ────────────────────────────────────────────────────────────────────


class PolicyDecision(StrEnum):
    """What happens when a tool is invoked."""

    AUTO = "auto"  # Execute without asking
    CONFIRM = "confirm"  # Ask user before executing
    DENY = "deny"  # Block entirely


class ToolPolicy:
    """Resolves the policy decision for a given tool call.

    Decisions are derived from:
      1. Per-tool overrides (set via `set()` — used by tests / config).
      2. Pattern-based PermissionRuleset (optional).
      3. The tool's own `requires_approval` attribute.
      4. The session-level `auto_approve` flag — when True, skips approval
         for tools that would otherwise need it.

    A `DENY` from a ruleset still blocks even with auto-approve on.
    """

    def __init__(self, overrides: dict[str, PolicyDecision] | None = None) -> None:
        self._overrides = dict(overrides or {})
        self._ruleset: PermissionRuleset | None = None
        self._auto_approve: bool = False

    @property
    def auto_approve(self) -> bool:
        return self._auto_approve

    @auto_approve.setter
    def auto_approve(self, value: bool) -> None:
        self._auto_approve = bool(value)

    def decide(
        self,
        tool_name: str,
        arguments: dict | None = None,
        *,
        tool: Any = None,
    ) -> PolicyDecision:
        """Resolve the policy for a tool call.

        Ruleset > per-tool overrides > tool.requires_approval. Auto-approve
        downgrades a CONFIRM to AUTO; it never weakens a DENY.
        """
        if self._ruleset is not None:
            subject = self._ruleset.extract_subject(tool_name, arguments or {})
            decision = self._ruleset.decide(tool_name, subject)
            if decision is not None:
                return self._maybe_auto(decision)
        if tool_name in self._overrides:
            return self._maybe_auto(self._overrides[tool_name])
        if tool is not None and tool_requires_approval(tool, arguments or {}):
            return self._maybe_auto(PolicyDecision.CONFIRM)
        return PolicyDecision.AUTO

    def _maybe_auto(self, decision: PolicyDecision) -> PolicyDecision:
        if decision == PolicyDecision.CONFIRM and self._auto_approve:
            return PolicyDecision.AUTO
        return decision

    def set(self, tool_name: str, decision: PolicyDecision) -> None:
        """Override the policy for a specific tool."""
        self._overrides[tool_name] = decision

    def set_overrides(self, overrides: dict[str, PolicyDecision]) -> None:
        """Replace per-tool policy overrides."""
        self._overrides = dict(overrides)

    def set_ruleset(self, ruleset: PermissionRuleset | None) -> None:
        """Attach a PermissionRuleset for pattern-based decisions."""
        self._ruleset = ruleset


# Late-binding import to avoid a circular dependency: permissions imports from
# executor, so we annotate with a string and import only for type checks.
from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:
    from taui.permissions import PermissionRuleset


# ── Execution outcomes ────────────────────────────────────────────────────────


@dataclass(slots=True)
class Completed:
    """Tool ran successfully (or failed gracefully with error in result)."""

    result: ToolResult


@dataclass(slots=True)
class NeedsApproval:
    """Tool requires user confirmation before running."""

    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class Denied:
    """Tool execution was blocked by policy."""

    result: ToolResult


Outcome = Completed | NeedsApproval | Denied


# ── Executor ──────────────────────────────────────────────────────────────────


class ToolExecutor:
    """Policy gate that sits between the agent loop and tools.

    Evaluates policy, dispatches to the tool, handles timeouts and errors.

    Usage::

        executor = ToolExecutor(registry, policy)
        outcome = await executor.run("call_1", "read_file", {"path": "main.py"})
        match outcome:
            case Completed(result=r): ...
            case NeedsApproval(): ...
            case Denied(result=r): ...
    """

    def __init__(
        self,
        registry: ToolRegistry,
        policy: ToolPolicy | None = None,
        *,
        timeout: float = 120.0,
        truncation_store: TruncationStore | None = None,
    ) -> None:
        self._registry = registry
        self._policy = policy or ToolPolicy()
        self._timeout = timeout
        self._truncation_store = truncation_store

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def policy(self) -> ToolPolicy:
        return self._policy

    async def run(
        self,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        approved: bool | None = None,
        on_output_delta: ToolOutputDeltaCallback | None = None,
    ) -> Outcome:
        """Execute a tool call with policy enforcement.

        Args:
            tool_call_id: Unique ID for this call (from the LLM).
            tool_name: Name of the tool to invoke.
            arguments: Arguments dict from the LLM.
            approved: None = not yet asked. True = user approved. False = user rejected.

        Returns:
            Completed, NeedsApproval, or Denied.
        """
        # Resolve tool
        try:
            tool = self._registry.get(tool_name)
        except ValueError:
            return Completed(
                result=ToolResult.fail(f"Unknown tool: {tool_name!r}")
            )

        # Check policy
        decision = self._policy.decide(tool_name, arguments, tool=tool)
        if decision == PolicyDecision.DENY:
            return Denied(
                result=ToolResult.fail(f"Tool {tool_name!r} is denied by policy.")
            )
        if decision == PolicyDecision.CONFIRM:
            if approved is None:
                return NeedsApproval(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    arguments=arguments,
                )
            if approved is False:
                return Denied(
                    result=ToolResult.fail("Tool execution rejected by user.")
                )

        # Schema-level validation — catch missing required args before the tool
        # raises a KeyError, which would otherwise be retried 3× for FILE_READ /
        # SEARCH categories and surface as a cryptic "Tool 'x' failed: 'path'".
        missing = _missing_required_args(tool, arguments)
        if missing:
            msg = (
                f"Tool {tool_name!r} called with missing required argument(s): "
                + ", ".join(missing)
            )
            return Completed(result=ToolResult.fail(msg))

        # Execute with optional retry for idempotent categories
        start = time.perf_counter()
        token = set_tool_output_delta_callback(on_output_delta)
        try:
            result = await self._execute_with_retry(tool_name, tool, arguments)
        finally:
            reset_tool_output_delta_callback(token)
        elapsed = time.perf_counter() - start
        result.metadata.setdefault("duration_ms", int(elapsed * 1000))

        # Truncate large outputs so the LLM context window isn't flooded.
        # The full content is stored in the truncation store behind a peek handle.
        if (
            self._truncation_store is not None
            and not result.error
            and result.content
            # Never truncate the peek tool itself — that would be circular.
            and tool_name != "peek"
        ):
            result = ToolResult(
                content=self._truncation_store.maybe_truncate(result.content, tool_name),
                error=result.error,
                metadata=result.metadata,
            )

        return Completed(result=result)

    async def _execute_with_retry(
        self, tool_name: str, tool: Any, arguments: dict[str, Any],
    ) -> ToolResult:
        """Execute a tool, retrying on failure for idempotent categories."""
        delays = _RETRY_DELAYS if tool.category in _RETRY_CATEGORIES else ()
        max_attempts = len(delays) + 1
        last_result: ToolResult | None = None

        # Per-tool override: `tool.timeout` may be a float (custom limit) or
        # None to disable the timeout entirely (e.g. for sub_agent, which has
        # its own max_turns budget and can legitimately run for minutes).
        tool_timeout = getattr(tool, "timeout", self._timeout)

        for attempt in range(max_attempts):
            try:
                if tool_timeout is None:
                    result = await tool.execute(arguments)
                else:
                    result = await asyncio.wait_for(
                        tool.execute(arguments), timeout=tool_timeout
                    )
            except TimeoutError:
                logger.warning("Tool timed out tool=%s timeout=%.1fs", tool_name, tool_timeout)
                result = ToolResult.fail(
                    f"Tool {tool_name!r} timed out after {tool_timeout:.0f}s."
                )
            except Exception as exc:
                logger.exception("Tool raised tool=%s attempt=%d", tool_name, attempt + 1)
                result = ToolResult.fail(f"Tool {tool_name!r} failed: {exc}")

            if not result.error:
                return result

            last_result = result
            if attempt < len(delays):
                logger.debug(
                    "Retrying idempotent tool tool=%s attempt=%d delay=%.2fs",
                    tool_name, attempt + 1, delays[attempt],
                )
                await asyncio.sleep(delays[attempt])

        assert last_result is not None
        return last_result


def _missing_required_args(tool: Any, arguments: dict[str, Any]) -> list[str]:
    """Return the list of required schema fields that aren't in `arguments`."""
    schema = getattr(tool, "schema", None)
    if not isinstance(schema, dict):
        return []
    required = schema.get("required") or []
    if not isinstance(required, list):
        return []
    return [name for name in required if name not in arguments]
