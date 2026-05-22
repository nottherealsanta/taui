"""Tool executor — policy gate and dispatch layer between the agent loop and tools."""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from taui.tools.base import ToolCategory, ToolResult
from taui.tools.registry import ToolRegistry
from taui.tools.truncation import TruncationStore

logger = logging.getLogger(__name__)


# ── Retry config ─────────────────────────────────────────────────────────────

_RETRY_CATEGORIES: frozenset[ToolCategory] = frozenset(
    {ToolCategory.FILE_READ, ToolCategory.SEARCH}
)
_RETRY_DELAYS: tuple[float, ...] = (0.25, 1.0, 4.0)

_READ_ONLY_GIT_OPS: frozenset[str] = frozenset(
    {"status", "diff", "log", "show", "blame", "branch_list", "branch_current", "stash_list"}
)

# ── Policy ────────────────────────────────────────────────────────────────────


class PolicyDecision(StrEnum):
    """What happens when a tool is invoked."""

    AUTO = "auto"  # Execute without asking
    CONFIRM = "confirm"  # Ask user before executing
    DENY = "deny"  # Block entirely


class ToolPolicy:
    """Resolves the policy decision for a given tool.

    Policies are layered: ruleset > per-tool overrides > defaults.
    """

    # Sensible defaults — destructive / side-effecting tools require confirmation
    _DEFAULTS: dict[str, PolicyDecision] = {
        "bash": PolicyDecision.CONFIRM,
        "write": PolicyDecision.CONFIRM,
        "edit": PolicyDecision.CONFIRM,
        "worktree": PolicyDecision.CONFIRM,
    }

    def __init__(self, overrides: dict[str, PolicyDecision] | None = None) -> None:
        self._overrides = dict(overrides or {})
        self._patterns: list[tuple[str, str]] = []
        self._ruleset: PermissionRuleset | None = None

    def decide(self, tool_name: str, arguments: dict | None = None) -> PolicyDecision:
        """Resolve the policy for a tool name.

        If a ruleset is set, it is consulted first using the tool arguments to
        extract the subject for pattern matching.  Falls back to per-tool
        overrides and built-in defaults when no ruleset rule matches.
        """
        if self._ruleset is not None:
            subject = self._ruleset.extract_subject(tool_name, arguments or {})
            decision = self._ruleset.decide(tool_name, subject)
            if decision is not None:
                return decision
        if tool_name in self._overrides:
            return self._overrides[tool_name]
        if tool_name == "git":
            operation = (arguments or {}).get("operation")
            if operation in _READ_ONLY_GIT_OPS:
                return PolicyDecision.AUTO
            return PolicyDecision.CONFIRM
        if tool_name in self._DEFAULTS:
            return self._DEFAULTS[tool_name]
        return PolicyDecision.AUTO

    def set(self, tool_name: str, decision: PolicyDecision) -> None:
        """Override the policy for a specific tool."""
        self._overrides[tool_name] = decision

    def set_overrides(self, overrides: dict[str, PolicyDecision]) -> None:
        """Replace per-tool policy overrides while preserving session patterns."""
        self._overrides = dict(overrides)

    def set_ruleset(self, ruleset: PermissionRuleset | None) -> None:
        """Attach a PermissionRuleset for pattern-based decisions."""
        self._ruleset = ruleset

    def add_pattern(self, tool_name: str, pattern: str) -> None:
        """Add a glob pattern for auto-approving similar tool calls."""
        self._patterns.append((tool_name, pattern))

    def should_auto_approve(self, tool_name: str, arguments: dict) -> bool:
        """Return True if arguments match a stored auto-approve pattern or ruleset AUTO rule."""
        # Check ruleset first
        if self._ruleset is not None:
            subject = self._ruleset.extract_subject(tool_name, arguments)
            decision = self._ruleset.decide(tool_name, subject)
            if decision == PolicyDecision.AUTO:
                return True
            if decision is not None:
                return False
        for pat_tool, pat_glob in self._patterns:
            if pat_tool != tool_name:
                continue
            if tool_name == "bash":
                subject = arguments.get("command", "")
            elif tool_name in ("write", "edit"):
                subject = arguments.get("file_path", "") or arguments.get("filePath", "")
            elif tool_name == "git":
                subject = _git_subject(arguments)
            else:
                subject = ""
            if fnmatch.fnmatch(subject, pat_glob):
                return True
        return False


def _git_subject(arguments: dict[str, Any]) -> str:
    operation = arguments.get("operation", "")
    args = arguments.get("args", {})
    if not isinstance(operation, str):
        return ""
    if not isinstance(args, dict) or not args:
        return operation
    parts = [operation]
    for key in sorted(args):
        value = args[key]
        if isinstance(value, str | int | bool):
            parts.append(f"{key}={value}")
    return " ".join(parts)


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
        decision = self._policy.decide(tool_name, arguments)
        if decision == PolicyDecision.DENY:
            return Denied(
                result=ToolResult.fail(f"Tool {tool_name!r} is denied by policy.")
            )
        if decision == PolicyDecision.CONFIRM:
            if approved is None:
                if not self._policy.should_auto_approve(tool_name, arguments):
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
        result = await self._execute_with_retry(tool_name, tool, arguments)
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
