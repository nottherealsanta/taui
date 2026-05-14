"""Tests for SubAgentTool — child agent spawning."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from taui.agent.loop import AgentLoop
from taui.llm_provider.types import ProviderToolCall, ProviderTurnResult
from taui.tools.base import ToolCategory, ToolResult
from taui.tools.builtins.sub_agent import SubAgentTool
from taui.tools.executor import ToolExecutor, ToolPolicy
from taui.tools.registry import ToolRegistry

# ── Mock LLM ──────────────────────────────────────────────────────────────────


class MockLLM:
    """LLM that returns scripted responses."""

    def __init__(self, responses: list[ProviderTurnResult]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    async def create_turn(self, messages, model="mock", *, tools=None, **kw):
        self.call_count += 1
        if not self._responses:
            return ProviderTurnResult(response_id=None, text="(exhausted)", tool_calls=[])
        return self._responses.pop(0)


# ── Mock tool ─────────────────────────────────────────────────────────────────


@dataclass
class EchoTool:
    name: str = "echo"
    description: str = "Echo input."
    category: ToolCategory = ToolCategory.FILE_READ
    schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    })

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.ok(f"echo: {arguments.get('text', '')}")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _text(text: str) -> ProviderTurnResult:
    return ProviderTurnResult(response_id=None, text=text, tool_calls=[])


def _tool_call(text: str | None, calls: list[tuple[str, str, dict]]) -> ProviderTurnResult:
    return ProviderTurnResult(
        response_id=None,
        text=text or "",
        tool_calls=[
            ProviderToolCall(call_id=cid, name=name, arguments=args)
            for cid, name, args in calls
        ],
    )


def _make_sub_agent_tool(
    llm: MockLLM,
    *tools,
    model: str = "mock",
) -> SubAgentTool:
    """Create a SubAgentTool wired with a mock LLM and tools."""
    registry = ToolRegistry()
    for t in tools:
        registry.register(t)
    # Register a dummy sub_agent entry so the parent registry has it
    sub = SubAgentTool()
    registry.register(sub)

    executor = ToolExecutor(registry=registry, policy=ToolPolicy())

    sub._llm = llm
    sub._stream = None
    sub._parent_executor = executor
    sub._model = model
    return sub


# ═══ Tests ════════════════════════════════════════════════════════════════════


class TestSubAgentTool:
    """SubAgentTool unit tests."""

    async def test_simple_text_task(self):
        """Sub-agent receives task, LLM responds with text."""
        llm = MockLLM([_text("The answer is 42.")])
        tool = _make_sub_agent_tool(llm)

        result = await tool.execute({"task": "What is the meaning of life?"})
        assert not result.error
        assert "42" in result.content
        assert result.metadata["turns"] == 1

    async def test_sub_agent_uses_tools(self):
        """Sub-agent can use tools from its scoped registry."""
        llm = MockLLM([
            _tool_call(None, [("c1", "echo", {"text": "hello"})]),
            _text("The echo said: hello"),
        ])
        tool = _make_sub_agent_tool(llm, EchoTool())

        result = await tool.execute({
            "task": "Echo hello",
            "tools": ["echo"],
        })
        assert not result.error
        assert "echo" in result.content.lower()
        assert result.metadata["turns"] == 2

    async def test_respects_max_turns(self):
        """Sub-agent stops at max_turns."""
        # LLM always calls tools, never stops
        responses = [
            _tool_call(None, [("c1", "echo", {"text": "loop"})])
            for _ in range(10)
        ]
        llm = MockLLM(responses)
        tool = _make_sub_agent_tool(llm, EchoTool())

        result = await tool.execute({
            "task": "Keep going",
            "tools": ["echo"],
            "max_turns": 3,
        })
        assert not result.error
        assert result.metadata["turns"] == 3

    async def test_max_turns_capped_at_25(self):
        """max_turns cannot exceed 25."""
        llm = MockLLM([_text("Done.")])
        tool = _make_sub_agent_tool(llm)

        result = await tool.execute({
            "task": "Do something",
            "max_turns": 100,
        })
        # Should run fine (capped to 25, but only needs 1 turn)
        assert not result.error

    async def test_sub_agent_excludes_itself(self):
        """Sub-agent tool should not be available to child (no recursion)."""
        llm = MockLLM([
            # Child LLM tries to call sub_agent — should get unknown tool error
            _tool_call(None, [("c1", "sub_agent", {"task": "recurse"})]),
            _text("Could not recurse."),
        ])
        tool = _make_sub_agent_tool(llm, EchoTool())

        result = await tool.execute({
            "task": "Try to recurse",
            "tools": ["echo", "sub_agent"],
        })
        assert not result.error
        # sub_agent was filtered out, so child only has echo

    async def test_empty_task_rejected(self):
        """Empty task string should fail."""
        llm = MockLLM([_text("Done.")])
        tool = _make_sub_agent_tool(llm)

        result = await tool.execute({"task": ""})
        assert result.error
        assert "non-empty" in result.content

    async def test_missing_task_rejected(self):
        """Missing task key should fail."""
        llm = MockLLM([_text("Done.")])
        tool = _make_sub_agent_tool(llm)

        result = await tool.execute({})
        assert result.error

    async def test_no_llm_configured(self):
        """Fails gracefully if LLM not wired."""
        tool = SubAgentTool()
        result = await tool.execute({"task": "Do something"})
        assert result.error
        assert "not configured" in result.content

    async def test_default_tools(self):
        """Without explicit tools, uses defaults (read, glob, grep, bash)."""
        llm = MockLLM([_text("Found files.")])
        tool = _make_sub_agent_tool(llm, EchoTool())

        # echo is in registry but not in default tools list
        # Since none of the defaults are registered, child gets empty registry
        result = await tool.execute({"task": "List files"})
        # Still succeeds — sub-agent can run with no tools (thinking only)
        assert not result.error

    async def test_default_tools_with_available(self):
        """Default tools used when they exist in registry."""
        @dataclass
        class FakeReadTool:
            name: str = "read"
            description: str = "Read files."
            category: ToolCategory = ToolCategory.FILE_READ
            schema: dict[str, Any] = field(default_factory=lambda: {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            })

            async def execute(self, arguments: dict[str, Any]) -> ToolResult:
                return ToolResult.ok("file content")

        llm = MockLLM([_text("Read the file.")])
        tool = _make_sub_agent_tool(llm, FakeReadTool())

        result = await tool.execute({"task": "Read main.py"})
        assert not result.error

    async def test_invalid_tool_names_filtered(self):
        """Requested tools that don't exist are silently filtered."""
        llm = MockLLM([_text("Done.")])
        tool = _make_sub_agent_tool(llm, EchoTool())

        result = await tool.execute({
            "task": "Do something",
            "tools": ["echo", "nonexistent_tool"],
        })
        assert not result.error

    async def test_llm_error_handled(self):
        """LLM failure is caught and returned as tool error."""
        class FailingLLM:
            async def create_turn(self, *args, **kwargs):
                raise RuntimeError("LLM down")

        tool = _make_sub_agent_tool(MockLLM([]), EchoTool())
        tool._llm = FailingLLM()

        result = await tool.execute({
            "task": "Do something",
            "tools": ["echo"],
        })
        assert result.error
        assert "failed" in result.content.lower()


class TestSubAgentIntegration:
    """Integration tests: parent agent delegates to sub-agent."""

    async def test_parent_delegates_to_sub_agent(self):
        """Full flow: parent calls sub_agent tool, child runs, result fed back."""
        # Child LLM: responds with analysis
        child_responses = [_text("The code has 3 functions and 2 classes.")]

        # Parent LLM: calls sub_agent, then summarizes
        parent_responses = [
            _tool_call(None, [
                ("c1", "sub_agent", {
                    "task": "Analyze the codebase structure",
                    "tools": ["echo"],
                }),
            ]),
            _text("Based on the analysis: 3 functions and 2 classes found."),
        ]

        # We need two separate LLM instances since the parent and child
        # share the LLM reference but consume different response queues.
        # For this test, we'll use a single LLM that serves both.
        all_responses = [
            parent_responses[0],   # Parent turn 1: call sub_agent
            child_responses[0],     # Child turn 1: text response
            parent_responses[1],   # Parent turn 2: summarize
        ]
        shared_llm = MockLLM(all_responses)

        # Build parent registry with echo + sub_agent
        echo = EchoTool()
        sub_agent = SubAgentTool()
        parent_registry = ToolRegistry()
        parent_registry.register(echo)
        parent_registry.register(sub_agent)

        parent_executor = ToolExecutor(registry=parent_registry, policy=ToolPolicy())

        # Wire sub-agent tool
        sub_agent._llm = shared_llm
        sub_agent._stream = None
        sub_agent._parent_executor = parent_executor
        sub_agent._model = "mock"

        # Run parent agent
        parent_loop = AgentLoop(
            llm=shared_llm,
            executor=parent_executor,
            model="mock",
            max_turns=5,
        )
        result = await parent_loop.run("Analyze the codebase")

        assert result.turns == 2
        assert "3 functions" in result.text
