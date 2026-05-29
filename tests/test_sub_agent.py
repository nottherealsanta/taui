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

    async def test_max_turns_does_final_wrap_up_turn(self):
        """On hitting max_turns the loop makes one final tool-free turn so the
        agent returns its findings rather than empty 'Max turns reached.' text."""
        # Two tool-calling turns exhaust the budget, then the wrap-up turn
        # (3rd create_turn) produces the actual answer.
        responses = [
            _tool_call(None, [("c1", "echo", {"text": "loop"})]),
            _tool_call(None, [("c2", "echo", {"text": "loop"})]),
            _text("Final summary of findings."),
        ]
        llm = MockLLM(responses)
        tool = _make_sub_agent_tool(llm, EchoTool())

        result = await tool.execute({
            "task": "Keep going",
            "tools": ["echo"],
            "max_turns": 2,
        })
        assert not result.error
        assert result.content == "Final summary of findings."
        # turns still reports the budget; the wrap-up is an extra LLM call.
        assert result.metadata["turns"] == 2
        assert llm.call_count == 3

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


class TestSubAgentLiveCallbacks:
    """The TUI relies on the child loop's tool events being forwarded so the
    sub-agent widget shows live activity instead of staying at "starting…"."""

    async def test_forwards_callbacks_to_child_loop(self):
        """execute() copies the parent's tool callbacks onto the child loop."""

        @dataclass
        class FakeLoop:
            _on_tool_call: Any = None
            _on_tool_result: Any = None
            _on_tool_delta: Any = None
            _on_text: Any = None
            _on_reasoning_delta: Any = None

        class FakeResult:
            text = "done"
            turns = 1

            class state:  # noqa: N801 - mimic enum-like .value
                value = "completed"

        class FakeSubSession:
            def __init__(self, loop):
                self._loop = loop

            async def send(self, task):
                return FakeResult()

        captured_loop = FakeLoop()

        class FakeParentSession:
            class config:
                model = "mock"

            async def create_sub_session(self, **kwargs):
                return FakeSubSession(captured_loop)

        async def on_call(*a):
            ...

        async def on_result(*a):
            ...

        async def on_delta(*a):
            ...

        async def on_text(*a):
            ...

        def on_reasoning(*a):
            ...

        tool = SubAgentTool()
        tool._session = FakeParentSession()
        tool._on_tool_call = on_call
        tool._on_tool_result = on_result
        tool._on_tool_delta = on_delta
        tool._on_child_text = on_text
        tool._on_child_reasoning = on_reasoning

        result = await tool.execute({"task": "do work"})

        assert not result.error
        # The child loop must end up wired to the parent's callbacks; without
        # this the sub-agent widget never receives inner-tool events.
        assert captured_loop._on_tool_call is on_call
        assert captured_loop._on_tool_result is on_result
        assert captured_loop._on_tool_delta is on_delta
        # Text and reasoning are routed too so the status line can reflect them.
        assert captured_loop._on_text is on_text
        assert captured_loop._on_reasoning_delta is on_reasoning

    async def test_legacy_path_forwards_callbacks(self):
        """The legacy (no-session) path must also forward callbacks so the
        child's tool calls reach the TUI."""
        calls: list[tuple[str, str]] = []

        async def on_call(call_id, name, args):
            calls.append(("call", name))

        async def on_result(call_id, name, content, is_error):
            calls.append(("result", name))

        llm = MockLLM([
            _tool_call(None, [("c1", "echo", {"text": "hi"})]),
            _text("All done."),
        ])
        tool = _make_sub_agent_tool(llm, EchoTool())  # legacy: no _session
        tool._on_tool_call = on_call
        tool._on_tool_result = on_result

        result = await tool.execute({"task": "Echo hi", "tools": ["echo"]})

        assert not result.error
        assert ("call", "echo") in calls
        assert ("result", "echo") in calls

    def test_configure_sub_agents_injects_session(self):
        """Live wiring must set `_session` so execute() uses the preferred path
        (which forwards callbacks). The legacy path can't reach the TUI."""
        from taui.extensions.builtins import _configure_sub_agents

        registry = ToolRegistry()
        registry.register(SubAgentTool())

        class FakeSession:
            _registry = registry
            _provider = object()
            _stream = object()
            _executor = ToolExecutor(registry=registry, policy=ToolPolicy())

            class config:
                model = "mock"

        session = FakeSession()
        _configure_sub_agents(session)

        assert registry.get("sub_agent")._session is session

    def test_refresh_agent_catalog_advertises_profiles(self, tmp_path):
        """Spawnable profiles (e.g. EXP) must appear in the agent_id schema so
        the main agent can discover and use them."""
        from taui.self_edit.store import SelfEditStore

        SelfEditStore(tmp_path).ensure_default_agents()

        class FakeSession:
            class config:
                working_dir = tmp_path

        tool = SubAgentTool()
        tool._session = FakeSession()
        tool.refresh_agent_catalog()

        prop = tool.schema["properties"]["agent_id"]
        assert "EXP" in prop["enum"]
        assert "EXP" in prop["description"]
        assert "Explorer" in prop["description"]


class TestSubAgentWidgetStatus:
    """The widget's inline status is always one line; the modal activity log
    keeps tool lines short but text/reasoning in full."""

    def _widget(self):
        from taui.tui.widgets.sub_agent_widget import SubAgentWidget

        return SubAgentWidget("sub_agent", "", arguments={"task": "do x"})

    def test_status_starts_at_starting(self):
        assert self._widget()._status_line() == "starting…"

    def test_tool_is_one_line_in_log_and_status(self):
        w = self._widget()
        w.record_activity("▸ grep  pattern=auth")
        assert w._activity_log[-1] == "▸ grep  pattern=auth"
        assert w._status_line() == "▸ grep  pattern=auth"

    def test_reasoning_live_one_line_but_logged_in_full(self):
        w = self._widget()
        w.record_reasoning_delta("Thinking about auth\nand then tokens")
        # Live status collapses to the first line…
        assert w._status_line() == "Thinking about auth"
        # …and the next discrete event flushes the full reasoning to the log.
        w.record_activity("▸ read  path=auth.py")
        flushed = next(s for s in w._activity_log if s.startswith("🤔"))
        assert flushed == "🤔 Thinking about auth\nand then tokens"
        assert w._status_line() == "▸ read  path=auth.py"

    def test_text_full_in_log_one_line_in_status(self):
        w = self._widget()
        w.record_text("Summary:\n- a\n- b")
        assert w._activity_log[-1] == "💬 Summary:\n- a\n- b"
        assert w._status_line() == "💬 Summary:"
