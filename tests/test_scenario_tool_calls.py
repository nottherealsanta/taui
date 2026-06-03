"""End-to-end tool-call scenarios.

Drives the full think → tool → observe cycle by combining `ScriptedProvider`
turns with the real built-in tools. The scripted provider returns tool calls
in the first turn; the executor runs the real tool; the second scripted turn
sees the tool result in conversation history and produces a final reply.

If something in the loop's tool plumbing regresses, these tests catch it
without any LLM round trip.
"""

from __future__ import annotations

import pytest

from taui.agent.loop import AgentLoop
from taui.config import Config
from taui.llm_provider.types import Usage
from taui.session import Session
from taui.store.store import Store
from taui.store.stream import StreamClient
from taui.tools.builtins import register_builtins
from taui.tools.executor import PolicyDecision, ToolExecutor, ToolPolicy
from taui.tools.registry import ToolRegistry
from tests.scenarios import ScriptedProvider, ScriptedToolCall, Turn, scenarios


async def _session_with_tools(
    tmp_path,
    provider: ScriptedProvider,
    *,
    auto_approve: tuple[str, ...] = (
        "read",
        "glob",
        "grep",
        "write",
        "edit",
        "bash",
    ),
    on_text_delta=None,
) -> Session:
    """Build a Session with real builtin tools and auto-approval for the listed names."""
    config = Config(working_dir=tmp_path)
    registry = ToolRegistry()
    register_builtins(registry)
    for name in registry.names:
        tool = registry.get(name)
        if hasattr(tool, "working_dir"):
            tool.working_dir = tmp_path
    overrides = {name: PolicyDecision.AUTO for name in auto_approve}
    policy = ToolPolicy(overrides=overrides)
    executor = ToolExecutor(registry=registry, policy=policy)
    store = Store(tmp_path)
    await store.connect()
    stream = StreamClient(store)
    loop = AgentLoop(
        llm=provider,
        executor=executor,
        stream=stream,
        system_prompt="test",
        model="test-model",
        on_text_delta=on_text_delta,
    )
    return Session(
        config=config,
        provider=provider,
        registry=registry,
        executor=executor,
        store=store,
        stream=stream,
        loop=loop,
    )


class TestSingleToolCall:
    async def test_read_tool_executes_and_loop_continues(self, tmp_path):
        target = tmp_path / "hello.txt"
        target.write_text("file contents")
        provider = scenarios.with_tool_call(
            "read", {"path": "hello.txt"}, final_reply="I read it."
        )
        session = await _session_with_tools(tmp_path, provider)
        try:
            result = await session.send("read hello.txt")
            assert result.text == "I read it."
            # Provider was called twice: once for the tool-call turn, once for the reply.
            assert provider.call_count == 2
            # Conversation history contains the tool result.
            roles = [m.role for m in session._loop.messages]
            assert "tool" in roles
            tool_msg = next(m for m in session._loop.messages if m.role == "tool")
            assert "file contents" in tool_msg.content
        finally:
            await session.close()

    async def test_read_tool_missing_path_returns_failure_to_loop(self, tmp_path):
        provider = scenarios.with_tool_call(
            "read", {"path": "nope.txt"}, final_reply="That file didn't exist."
        )
        session = await _session_with_tools(tmp_path, provider)
        try:
            result = await session.send("read nope.txt")
            assert result.text == "That file didn't exist."
            tool_msg = next(m for m in session._loop.messages if m.role == "tool")
            assert "not found" in tool_msg.content.lower()
        finally:
            await session.close()


class TestParallelToolCalls:
    async def test_two_reads_executed_and_results_returned(self, tmp_path):
        a = tmp_path / "a.txt"
        a.write_text("aaa")
        b = tmp_path / "b.txt"
        b.write_text("bbb")
        provider = ScriptedProvider(
            [
                Turn(
                    tool_calls=[
                        ScriptedToolCall(name="read", arguments={"path": "a.txt"}),
                        ScriptedToolCall(name="read", arguments={"path": "b.txt"}),
                    ],
                    stop_reason="tool_use",
                ),
                Turn(text="Both read."),
            ]
        )
        session = await _session_with_tools(tmp_path, provider)
        try:
            result = await session.send("read both")
            assert result.text == "Both read."
            tool_msgs = [m for m in session._loop.messages if m.role == "tool"]
            assert len(tool_msgs) == 2
            combined = " ".join(m.content for m in tool_msgs)
            assert "aaa" in combined and "bbb" in combined
        finally:
            await session.close()


class TestMalformedToolArguments:
    async def test_unknown_tool_yields_error_to_loop(self, tmp_path):
        provider = ScriptedProvider(
            [
                Turn(
                    tool_calls=[
                        ScriptedToolCall(name="not_a_real_tool", arguments={})
                    ],
                    stop_reason="tool_use",
                ),
                Turn(text="Recovered."),
            ]
        )
        session = await _session_with_tools(tmp_path, provider)
        try:
            result = await session.send("try fake tool")
            assert result.text == "Recovered."
            tool_msg = next(m for m in session._loop.messages if m.role == "tool")
            # Either the executor surfaces "unknown" or the tool name. Both are fine —
            # what matters is the loop survived and the assistant got a chance to recover.
            assert tool_msg.content  # something was reported back
        finally:
            await session.close()

    async def test_read_with_missing_required_argument(self, tmp_path):
        provider = ScriptedProvider(
            [
                Turn(
                    tool_calls=[ScriptedToolCall(name="read", arguments={})],
                    stop_reason="tool_use",
                ),
                Turn(text="Will try again."),
            ]
        )
        session = await _session_with_tools(tmp_path, provider)
        try:
            result = await session.send("read with no args")
            assert result.text == "Will try again."
            tool_msg = next(m for m in session._loop.messages if m.role == "tool")
            # Executor pre-validates required args; the message must call this out
            # specifically so the LLM can self-correct rather than guessing.
            assert "missing required argument" in tool_msg.content.lower()
            assert "path" in tool_msg.content.lower()
        finally:
            await session.close()


class TestMultiTurnConversation:
    async def test_three_turn_tool_chain(self, tmp_path):
        (tmp_path / "first.txt").write_text("one")
        (tmp_path / "second.txt").write_text("two")
        provider = ScriptedProvider(
            [
                Turn(
                    tool_calls=[
                        ScriptedToolCall(name="read", arguments={"path": "first.txt"})
                    ],
                    stop_reason="tool_use",
                ),
                Turn(
                    tool_calls=[
                        ScriptedToolCall(name="read", arguments={"path": "second.txt"})
                    ],
                    stop_reason="tool_use",
                ),
                Turn(text="Got both files."),
            ]
        )
        session = await _session_with_tools(tmp_path, provider)
        try:
            result = await session.send("read both files in sequence")
            assert result.text == "Got both files."
            assert provider.call_count == 3
            tool_msgs = [m for m in session._loop.messages if m.role == "tool"]
            assert len(tool_msgs) == 2
        finally:
            await session.close()


class TestUsageAggregation:
    async def test_usage_aggregates_across_turns(self, tmp_path):
        (tmp_path / "f.txt").write_text("x")
        provider = ScriptedProvider(
            [
                Turn(
                    tool_calls=[ScriptedToolCall(name="read", arguments={"path": "f.txt"})],
                    stop_reason="tool_use",
                    usage=Usage(input_tokens=100, output_tokens=10),
                ),
                Turn(
                    text="done",
                    usage=Usage(input_tokens=120, output_tokens=20),
                ),
            ]
        )
        session = await _session_with_tools(tmp_path, provider)
        try:
            result = await session.send("read")
            totals = result.total_usage
            assert totals["input_tokens"] == 220
            assert totals["output_tokens"] == 30
        finally:
            await session.close()


class TestReasoningPlusTool:
    async def test_reasoning_before_tool_call(self, tmp_path):
        (tmp_path / "x").write_text("data")
        thoughts: list[str] = []
        provider = ScriptedProvider(
            [
                Turn(
                    reasoning_deltas=["Plan: ", "read the file."],
                    tool_calls=[ScriptedToolCall(name="read", arguments={"path": "x"})],
                    stop_reason="tool_use",
                ),
                Turn(text="Final."),
            ]
        )
        session = await _session_with_tools(tmp_path, provider)
        try:
            session._loop._on_reasoning_delta = lambda d: thoughts.append(d)
            result = await session.send("go")
            assert result.text == "Final."
            assert "".join(thoughts) == "Plan: read the file."
        finally:
            await session.close()


class TestStopReasonVariants:
    @pytest.mark.parametrize("stop_reason", ["stop", "length", "tool_use"])
    async def test_loop_handles_stop_reasons(self, tmp_path, stop_reason):
        provider = ScriptedProvider([Turn(text="ok", stop_reason=stop_reason)])
        session = await _session_with_tools(tmp_path, provider)
        try:
            result = await session.send("hi")
            assert result.text == "ok"
        finally:
            await session.close()
