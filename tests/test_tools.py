"""Tests for taui.tools — ToolRegistry, ToolExecutor, and ToolPolicy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from taui.tools.base import ToolCategory, ToolResult
from taui.tools.executor import (
    Completed,
    Denied,
    NeedsApproval,
    PolicyDecision,
    ToolExecutor,
    ToolPolicy,
)
from taui.tools.registry import ToolRegistry

# ── Test tool implementations ─────────────────────────────────────────────────


@dataclass
class EchoTool:
    """A simple tool that echoes its input."""

    name: str = "echo"
    description: str = "Echoes the input text."
    category: ToolCategory = ToolCategory.MEMORY
    schema: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.ok(arguments.get("text", ""))


@dataclass
class FailTool:
    """A tool that always fails."""

    name: str = "fail_tool"
    description: str = "Always fails."
    category: ToolCategory = ToolCategory.SHELL
    schema: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.schema is None:
            self.schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.fail("Something went wrong")


@dataclass
class ExplodeTool:
    """A tool that raises an exception."""

    name: str = "explode"
    description: str = "Raises an exception."
    category: ToolCategory = ToolCategory.SHELL
    schema: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.schema is None:
            self.schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        raise RuntimeError("boom")


@dataclass
class SlowTool:
    """A tool that takes too long."""

    name: str = "slow"
    description: str = "Takes forever."
    category: ToolCategory = ToolCategory.SHELL
    schema: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.schema is None:
            self.schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        import asyncio

        await asyncio.sleep(100)
        return ToolResult.ok("done")


# ═══ ToolRegistry ═════════════════════════════════════════════════════════════


class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = EchoTool()
        reg.register(tool)
        assert reg.get("echo") is tool

    def test_register_duplicate_raises(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        with pytest.raises(ValueError, match="already registered"):
            reg.register(EchoTool())

    def test_register_or_replace(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        new_echo = EchoTool(description="New echo")
        reg.register_or_replace(new_echo)
        assert reg.get("echo").description == "New echo"

    def test_get_unknown_raises(self):
        reg = ToolRegistry()
        with pytest.raises(ValueError, match="Unknown tool"):
            reg.get("nope")

    def test_unregister(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        removed = reg.unregister("echo")
        assert removed.name == "echo"
        assert "echo" not in reg

    def test_unregister_unknown_raises(self):
        reg = ToolRegistry()
        with pytest.raises(ValueError, match="not registered"):
            reg.unregister("nope")

    def test_contains(self):
        reg = ToolRegistry()
        assert "echo" not in reg
        reg.register(EchoTool())
        assert "echo" in reg

    def test_len(self):
        reg = ToolRegistry()
        assert len(reg) == 0
        reg.register(EchoTool())
        assert len(reg) == 1

    def test_names(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        reg.register(FailTool())
        assert reg.names == ["echo", "fail_tool"]

    def test_by_category(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        reg.register(FailTool())
        shell_tools = reg.by_category(ToolCategory.SHELL)
        assert len(shell_tools) == 1
        assert shell_tools[0].name == "fail_tool"

    def test_schemas(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        schemas = reg.schemas()
        assert len(schemas) == 1
        assert schemas[0]["type"] == "function"
        assert schemas[0]["function"]["name"] == "echo"

    def test_schemas_with_include(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        reg.register(FailTool())
        schemas = reg.schemas(include={ToolCategory.MEMORY})
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "echo"

    def test_schemas_with_exclude(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        reg.register(FailTool())
        schemas = reg.schemas(exclude={ToolCategory.SHELL})
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "echo"

    def test_subset(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        reg.register(FailTool())
        sub = reg.subset(["echo"])
        assert len(sub) == 1
        assert "echo" in sub
        assert "fail_tool" not in sub

    def test_subset_unknown_raises(self):
        reg = ToolRegistry()
        with pytest.raises(ValueError):
            reg.subset(["nope"])

    def test_guidelines_collects_from_tools(self):
        @dataclass
        class ToolWithGuide:
            name: str = "guided"
            description: str = "A tool with guidelines."
            category: ToolCategory = ToolCategory.MEMORY
            schema: dict[str, Any] = None  # type: ignore[assignment]
            guidelines: str = "Always read before editing."

            def __post_init__(self):
                if self.schema is None:
                    self.schema = {"type": "object", "properties": {}}

            async def execute(self, arguments: dict[str, Any]) -> ToolResult:
                return ToolResult.ok("ok")

        reg = ToolRegistry()
        reg.register(ToolWithGuide())
        result = reg.guidelines()
        assert "## Tool Guidelines" in result
        assert "**guided**" in result
        assert "Always read before editing." in result

    def test_guidelines_empty_when_no_guidelines(self):
        reg = ToolRegistry()
        reg.register(EchoTool())  # No guidelines field
        assert reg.guidelines() == ""

    def test_guidelines_with_builtins(self):
        from taui.tools.builtins import register_builtins
        reg = ToolRegistry()
        register_builtins(reg)
        result = reg.guidelines()
        assert "## Tool Guidelines" in result
        assert "**read**" in result
        assert "**edit**" in result
        assert "**bash**" in result


# ═══ ToolPolicy ═══════════════════════════════════════════════════════════════


class TestToolPolicy:
    def test_default_is_auto(self):
        policy = ToolPolicy()
        assert policy.decide("anything") == PolicyDecision.AUTO

    def test_override(self):
        policy = ToolPolicy(overrides={"bash": PolicyDecision.CONFIRM})
        assert policy.decide("bash") == PolicyDecision.CONFIRM
        assert policy.decide("echo") == PolicyDecision.AUTO

    def test_set(self):
        policy = ToolPolicy()
        policy.set("bash", PolicyDecision.DENY)
        assert policy.decide("bash") == PolicyDecision.DENY

    def test_git_read_only_ops_auto_approve(self):
        policy = ToolPolicy()
        assert policy.decide("git", {"operation": "status"}) == PolicyDecision.AUTO
        assert policy.decide("git", {"operation": "diff"}) == PolicyDecision.AUTO
        assert policy.decide("git", {"operation": "show"}) == PolicyDecision.AUTO

    def test_git_mutating_ops_require_confirmation(self):
        policy = ToolPolicy()
        assert policy.decide("git", {"operation": "commit"}) == PolicyDecision.CONFIRM
        assert policy.decide("git", {"operation": "checkout"}) == PolicyDecision.CONFIRM


# ═══ ToolExecutor ═════════════════════════════════════════════════════════════


class TestToolExecutor:
    async def test_execute_auto(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        executor = ToolExecutor(reg)
        outcome = await executor.run("c1", "echo", {"text": "hello"})
        assert isinstance(outcome, Completed)
        assert outcome.result.content == "hello"
        assert outcome.result.error is False

    async def test_execute_unknown_tool(self):
        reg = ToolRegistry()
        executor = ToolExecutor(reg)
        outcome = await executor.run("c1", "nope", {})
        assert isinstance(outcome, Completed)
        assert outcome.result.error is True
        assert "Unknown tool" in outcome.result.content

    async def test_execute_tool_failure(self):
        reg = ToolRegistry()
        reg.register(FailTool())
        executor = ToolExecutor(reg)
        outcome = await executor.run("c1", "fail_tool", {})
        assert isinstance(outcome, Completed)
        assert outcome.result.error is True
        assert outcome.result.content == "Something went wrong"

    async def test_execute_tool_exception(self):
        reg = ToolRegistry()
        reg.register(ExplodeTool())
        executor = ToolExecutor(reg)
        outcome = await executor.run("c1", "explode", {})
        assert isinstance(outcome, Completed)
        assert outcome.result.error is True
        assert "boom" in outcome.result.content

    async def test_execute_tool_timeout(self):
        reg = ToolRegistry()
        reg.register(SlowTool())
        executor = ToolExecutor(reg, timeout=0.05)
        outcome = await executor.run("c1", "slow", {})
        assert isinstance(outcome, Completed)
        assert outcome.result.error is True
        assert "timed out" in outcome.result.content

    async def test_policy_confirm_needs_approval(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        policy = ToolPolicy(overrides={"echo": PolicyDecision.CONFIRM})
        executor = ToolExecutor(reg, policy)
        outcome = await executor.run("c1", "echo", {"text": "hi"})
        assert isinstance(outcome, NeedsApproval)
        assert outcome.tool_name == "echo"
        assert outcome.arguments == {"text": "hi"}

    async def test_policy_confirm_approved(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        policy = ToolPolicy(overrides={"echo": PolicyDecision.CONFIRM})
        executor = ToolExecutor(reg, policy)
        outcome = await executor.run("c1", "echo", {"text": "hi"}, approved=True)
        assert isinstance(outcome, Completed)
        assert outcome.result.content == "hi"

    async def test_policy_confirm_rejected(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        policy = ToolPolicy(overrides={"echo": PolicyDecision.CONFIRM})
        executor = ToolExecutor(reg, policy)
        outcome = await executor.run("c1", "echo", {"text": "hi"}, approved=False)
        assert isinstance(outcome, Denied)
        assert "rejected" in outcome.result.content

    async def test_policy_deny(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        policy = ToolPolicy(overrides={"echo": PolicyDecision.DENY})
        executor = ToolExecutor(reg, policy)
        outcome = await executor.run("c1", "echo", {"text": "hi"})
        assert isinstance(outcome, Denied)
        assert "denied" in outcome.result.content

    async def test_duration_in_metadata(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        executor = ToolExecutor(reg)
        outcome = await executor.run("c1", "echo", {"text": "hi"})
        assert isinstance(outcome, Completed)
        assert "duration_ms" in outcome.result.metadata

    async def test_registry_property(self):
        reg = ToolRegistry()
        executor = ToolExecutor(reg)
        assert executor.registry is reg

    async def test_policy_property(self):
        policy = ToolPolicy()
        executor = ToolExecutor(ToolRegistry(), policy)
        assert executor.policy is policy
