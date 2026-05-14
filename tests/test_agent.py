"""Tests for taui.agent — AgentLoop with a mock LLM provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from taui.agent.loop import AgentLoop, AgentState
from taui.llm_provider.types import ProviderToolCall, ProviderTurnResult
from taui.store import EventType, Store, StreamClient
from taui.tools.base import ToolCategory, ToolResult
from taui.tools.executor import ToolExecutor
from taui.tools.registry import ToolRegistry

# ── Mock LLM Provider ────────────────────────────────────────────────────────


class MockLLMProvider:
    """LLM provider that returns scripted responses.

    Each call to create_turn pops the next response from the queue.
    Satisfies the interface AgentLoop needs without inheriting BaseLLMProvider.
    """

    def __init__(self, responses: list[ProviderTurnResult]) -> None:
        self._responses = list(responses)
        self._call_count = 0
        self.calls: list[dict[str, Any]] = []

    async def create_turn(
        self,
        messages: list[dict[str, Any]],
        model: str = "mock",
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ProviderTurnResult:
        self.calls.append({"messages": messages, "tools": tools})
        self._call_count += 1
        if not self._responses:
            return ProviderTurnResult(
                response_id=None,
                text="(no more scripted responses)",
                tool_calls=[],
            )
        return self._responses.pop(0)


# ── Mock tool ─────────────────────────────────────────────────────────────────


@dataclass
class ListFilesTool:
    name: str = "list_files"
    description: str = "List files in a directory."
    category: ToolCategory = ToolCategory.FILE_READ
    schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    })

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.ok("main.py\ntest.py\nREADME.md")


@dataclass
class AddTool:
    name: str = "add"
    description: str = "Add two numbers."
    category: ToolCategory = ToolCategory.MEMORY
    schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "a": {"type": "number"},
            "b": {"type": "number"},
        },
        "required": ["a", "b"],
    })

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.ok(str(arguments["a"] + arguments["b"]))


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_executor(*tools) -> ToolExecutor:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return ToolExecutor(reg)


def _text_response(text: str) -> ProviderTurnResult:
    return ProviderTurnResult(response_id=None, text=text, tool_calls=[])


def _tool_response(
    text: str | None, calls: list[tuple[str, str, dict]]
) -> ProviderTurnResult:
    return ProviderTurnResult(
        response_id=None,
        text=text or "",
        tool_calls=[
            ProviderToolCall(call_id=cid, name=name, arguments=args)
            for cid, name, args in calls
        ],
    )


# ═══ Tests ════════════════════════════════════════════════════════════════════


class TestAgentLoopSimple:
    """Basic loop behavior without Store."""

    async def test_simple_text_response(self):
        llm = MockLLMProvider([_text_response("Hello!")])
        loop = AgentLoop(llm=llm, executor=_make_executor())
        result = await loop.run("Hi")
        assert result.text == "Hello!"
        assert result.turns == 1
        assert result.state == AgentState.DONE

    async def test_tool_call_then_response(self):
        llm = MockLLMProvider([
            _tool_response(None, [("c1", "list_files", {"path": "."})]),
            _text_response("Found 3 files: main.py, test.py, README.md"),
        ])
        loop = AgentLoop(llm=llm, executor=_make_executor(ListFilesTool()))
        result = await loop.run("What files are here?")
        assert result.turns == 2
        assert "3 files" in result.text

    async def test_multiple_tool_calls_in_one_turn(self):
        llm = MockLLMProvider([
            _tool_response(None, [
                ("c1", "add", {"a": 1, "b": 2}),
                ("c2", "add", {"a": 10, "b": 20}),
            ]),
            _text_response("1+2=3, 10+20=30"),
        ])
        loop = AgentLoop(llm=llm, executor=_make_executor(AddTool()))
        result = await loop.run("Add 1+2 and 10+20")
        assert result.turns == 2
        assert result.turn_results[0].tool_calls_count == 2

    async def test_max_turns_limit(self):
        # LLM always calls tools, never finishes
        responses = [
            _tool_response(None, [("c1", "add", {"a": 1, "b": 1})])
            for _ in range(5)
        ]
        llm = MockLLMProvider(responses)
        loop = AgentLoop(llm=llm, executor=_make_executor(AddTool()), max_turns=3)
        result = await loop.run("Keep going")
        assert result.turns == 3

    async def test_messages_accumulate(self):
        llm = MockLLMProvider([
            _tool_response(None, [("c1", "list_files", {"path": "."})]),
            _text_response("Done."),
        ])
        loop = AgentLoop(llm=llm, executor=_make_executor(ListFilesTool()))
        await loop.run("List files")

        roles = [m.role for m in loop.messages]
        # system, user, assistant (with tool call), tool (result), assistant (final)
        assert roles == ["system", "user", "assistant", "tool", "assistant"]

    async def test_unknown_tool_handled(self):
        """If LLM calls a tool that doesn't exist, loop continues gracefully."""
        llm = MockLLMProvider([
            _tool_response(None, [("c1", "nonexistent", {})]),
            _text_response("Sorry, that tool doesn't exist."),
        ])
        loop = AgentLoop(llm=llm, executor=_make_executor())
        result = await loop.run("Do something")
        assert result.turns == 2
        # The tool result message should contain the error
        tool_msgs = [m for m in loop.messages if m.role == "tool"]
        assert len(tool_msgs) == 1
        assert "Unknown tool" in tool_msgs[0].content


class TestAgentLoopWithStore:
    """Loop with Store integration — events are persisted."""

    async def test_events_written_to_store(self, tmp_path: Path):
        store = Store(tmp_path)
        await store.connect()
        stream = StreamClient(store)

        llm = MockLLMProvider([_text_response("Hello from agent!")])
        loop = AgentLoop(
            llm=llm,
            executor=_make_executor(),
            stream=stream,
            agent_id="test-agent",
        )
        result = await loop.run("Hi")
        assert result.text == "Hello from agent!"

        # Read events from the stream
        events = await stream.read_all("agents/test-agent")
        event_types = [e.type for e in events]
        assert EventType.STREAM_START in event_types
        assert EventType.USER_MESSAGE in event_types
        assert EventType.ASSISTANT_MESSAGE in event_types
        assert EventType.STREAM_END in event_types

        await store.close()

    async def test_tool_events_written(self, tmp_path: Path):
        store = Store(tmp_path)
        await store.connect()
        stream = StreamClient(store)

        llm = MockLLMProvider([
            _tool_response(None, [("c1", "list_files", {"path": "."})]),
            _text_response("Done."),
        ])
        loop = AgentLoop(
            llm=llm,
            executor=_make_executor(ListFilesTool()),
            stream=stream,
            agent_id="test-agent",
        )
        await loop.run("List files")

        events = await stream.read_all("agents/test-agent")
        event_types = [e.type for e in events]
        assert EventType.TOOL_CALL in event_types
        assert EventType.TOOL_RESULT in event_types

        # Verify tool call event data
        tc_event = next(e for e in events if e.type == EventType.TOOL_CALL)
        assert tc_event.data["name"] == "list_files"

        # Verify tool result event data
        tr_event = next(e for e in events if e.type == EventType.TOOL_RESULT)
        assert "main.py" in tr_event.data["content"]
        assert tr_event.data["error"] is False

        await store.close()


class TestAgentState:
    async def test_state_done_after_run(self):
        llm = MockLLMProvider([_text_response("Done.")])
        loop = AgentLoop(llm=llm, executor=_make_executor())
        await loop.run("Hi")
        assert loop.state == AgentState.DONE

    async def test_state_error_on_llm_failure(self):
        class FailingProvider:
            async def create_turn(self, *args, **kwargs):
                raise RuntimeError("LLM is down")

        loop = AgentLoop(llm=FailingProvider(), executor=_make_executor())
        with pytest.raises(RuntimeError, match="LLM is down"):
            await loop.run("Hi")
        assert loop.state == AgentState.ERROR


class TestAgentLoopCallbacks:
    """Tests for the on_tool_call, on_tool_result, on_approval, on_text callbacks."""

    async def test_on_text_fires(self):
        """on_text callback fires when the LLM returns text."""
        texts: list[str] = []

        async def capture_text(text: str):
            texts.append(text)

        llm = MockLLMProvider([_text_response("Hello!")])
        loop = AgentLoop(llm=llm, executor=_make_executor(), on_text=capture_text)
        await loop.run("Hi")
        assert texts == ["Hello!"]

    async def test_on_tool_call_fires(self):
        """on_tool_call fires for each tool call."""
        calls: list[tuple[str, str]] = []

        async def capture_call(call_id: str, name: str, arguments: dict):
            calls.append((call_id, name))

        llm = MockLLMProvider([
            _tool_response(None, [("c1", "list_files", {"path": "."})]),
            _text_response("Done."),
        ])
        loop = AgentLoop(
            llm=llm,
            executor=_make_executor(ListFilesTool()),
            on_tool_call=capture_call,
        )
        await loop.run("List files")
        assert calls == [("c1", "list_files")]

    async def test_on_tool_result_fires(self):
        """on_tool_result fires with content and error status."""
        results: list[tuple[str, bool]] = []

        async def capture_result(call_id: str, name: str, content: str, is_error: bool):
            results.append((name, is_error))

        llm = MockLLMProvider([
            _tool_response(None, [("c1", "list_files", {"path": "."})]),
            _text_response("Done."),
        ])
        loop = AgentLoop(
            llm=llm,
            executor=_make_executor(ListFilesTool()),
            on_tool_result=capture_result,
        )
        await loop.run("List files")
        assert results == [("list_files", False)]

    async def test_on_approval_approves(self):
        """on_approval returning True allows the tool to run."""
        from taui.tools.executor import PolicyDecision, ToolPolicy

        async def auto_approve(call_id, name, arguments) -> bool:
            return True

        reg = ToolRegistry()
        reg.register(ListFilesTool())
        policy = ToolPolicy()
        policy.set("list_files", PolicyDecision.CONFIRM)
        executor = ToolExecutor(reg, policy)

        llm = MockLLMProvider([
            _tool_response(None, [("c1", "list_files", {"path": "."})]),
            _text_response("Done."),
        ])
        loop = AgentLoop(llm=llm, executor=executor, on_approval=auto_approve)
        await loop.run("List files")
        # Should succeed because approval was granted
        tool_msgs = [m for m in loop.messages if m.role == "tool"]
        assert "main.py" in tool_msgs[0].content

    async def test_on_approval_denies(self):
        """on_approval returning False blocks the tool."""
        from taui.tools.executor import PolicyDecision, ToolPolicy

        async def deny_all(call_id, name, arguments) -> bool:
            return False

        reg = ToolRegistry()
        reg.register(ListFilesTool())
        policy = ToolPolicy()
        policy.set("list_files", PolicyDecision.CONFIRM)
        executor = ToolExecutor(reg, policy)

        llm = MockLLMProvider([
            _tool_response(None, [("c1", "list_files", {"path": "."})]),
            _text_response("OK, I won't do that."),
        ])
        loop = AgentLoop(llm=llm, executor=executor, on_approval=deny_all)
        await loop.run("List files")
        tool_msgs = [m for m in loop.messages if m.role == "tool"]
        assert "denied" in tool_msgs[0].content.lower()
