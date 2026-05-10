"""Tool executor — policy gate and dispatch layer between the agent loop and tools."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from taui.tools.base import ToolResult
from taui.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


# ── Policy ────────────────────────────────────────────────────────────────────


class PolicyDecision(StrEnum):
    """What happens when a tool is invoked."""

    AUTO = "auto"  # Execute without asking
    CONFIRM = "confirm"  # Ask user before executing
    DENY = "deny"  # Block entirely


class ToolPolicy:
    """Resolves the policy decision for a given tool.

    Policies are layered: per-tool overrides > defaults.
    """

    # Sensible defaults per architecture doc
    _DEFAULTS: dict[str, PolicyDecision] = {}

    def __init__(self, overrides: dict[str, PolicyDecision] | None = None) -> None:
        self._overrides = dict(overrides or {})

    def decide(self, tool_name: str) -> PolicyDecision:
        """Resolve the policy for a tool name."""
        if tool_name in self._overrides:
            return self._overrides[tool_name]
        if tool_name in self._DEFAULTS:
            return self._DEFAULTS[tool_name]
        return PolicyDecision.AUTO

    def set(self, tool_name: str, decision: PolicyDecision) -> None:
        """Override the policy for a specific tool."""
        self._overrides[tool_name] = decision


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
    ) -> None:
        self._registry = registry
        self._policy = policy or ToolPolicy()
        self._timeout = timeout

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
        decision = self._policy.decide(tool_name)
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

        # Execute
        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                tool.execute(arguments), timeout=self._timeout
            )
        except TimeoutError:
            elapsed = time.perf_counter() - start
            logger.warning(
                "Tool timed out tool=%s timeout=%.1fs", tool_name, elapsed
            )
            return Completed(
                result=ToolResult.fail(
                    f"Tool {tool_name!r} timed out after {self._timeout:.0f}s."
                )
            )
        except Exception as exc:
            elapsed = time.perf_counter() - start
            logger.exception("Tool raised tool=%s elapsed=%.3fs", tool_name, elapsed)
            return Completed(
                result=ToolResult.fail(f"Tool {tool_name!r} failed: {exc}")
            )

        elapsed = time.perf_counter() - start
        result.metadata.setdefault("duration_ms", int(elapsed * 1000))
        return Completed(result=result)
