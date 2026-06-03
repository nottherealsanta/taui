"""Agent-loop limit and lifecycle scenarios.

These tests cover the bookkeeping at the edges of the loop: max_turns,
empty input, multi-turn replay through the store, etc.
"""

from __future__ import annotations

from taui.agent.loop import AgentLoop, AgentState
from taui.config import Config
from taui.session import Session
from taui.store.store import Store
from taui.store.stream import StreamClient
from taui.tools.builtins import register_builtins
from taui.tools.executor import PolicyDecision, ToolExecutor, ToolPolicy
from taui.tools.registry import ToolRegistry
from tests.scenarios import ScriptedProvider, ScriptedToolCall, Turn, scenarios


async def _session(tmp_path, provider, *, max_turns: int = 50) -> Session:
    config = Config(working_dir=tmp_path)
    registry = ToolRegistry()
    register_builtins(registry)
    for name in registry.names:
        tool = registry.get(name)
        if hasattr(tool, "working_dir"):
            tool.working_dir = tmp_path
    policy = ToolPolicy(overrides={"read": PolicyDecision.AUTO})
    executor = ToolExecutor(registry=registry, policy=policy)
    store = Store(tmp_path)
    await store.connect()
    stream = StreamClient(store)
    loop = AgentLoop(
        llm=provider,
        executor=executor,
        stream=stream,
        system_prompt="test",
        model="m",
        max_turns=max_turns,
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


class TestMaxTurns:
    async def test_loop_terminates_at_max_turns_with_repeated_tool_calls(self, tmp_path):
        """A provider that always returns a tool call should cap at max_turns."""
        target = tmp_path / "t.txt"
        target.write_text("data")
        # Build a script that returns a read tool call every turn.
        turns = [
            Turn(
                tool_calls=[ScriptedToolCall(name="read", arguments={"path": "t.txt"})],
                stop_reason="tool_use",
            )
            for _ in range(10)
        ]
        provider = ScriptedProvider(turns)
        session = await _session(tmp_path, provider, max_turns=3)
        try:
            result = await session.send("loop forever")
            assert result.turns == 3
            assert result.state == AgentState.DONE
            # max_turns tool-calling turns, then one tool-free wrap-up turn.
            assert provider.call_count == 4
        finally:
            await session.close()

    async def test_loop_stops_early_when_final_text_arrives(self, tmp_path):
        """Even with high max_turns, a turn without tool calls terminates immediately."""
        provider = scenarios.happy_path("done")
        session = await _session(tmp_path, provider, max_turns=50)
        try:
            result = await session.send("hi")
            assert result.turns == 1
        finally:
            await session.close()


class TestSendInputs:
    async def test_empty_user_message(self, tmp_path):
        """An empty user message should still produce a turn (no crash)."""
        provider = scenarios.happy_path("ack")
        session = await _session(tmp_path, provider)
        try:
            result = await session.send("")
            assert result.text == "ack"
        finally:
            await session.close()

    async def test_two_successive_sends_continue_conversation(self, tmp_path):
        provider = ScriptedProvider(
            [
                Turn(text="first"),
                Turn(text="second"),
            ]
        )
        session = await _session(tmp_path, provider)
        try:
            r1 = await session.send("a")
            r2 = await session.send("b")
            assert r1.text == "first"
            assert r2.text == "second"
            # Conversation history grows across sends.
            roles = [m.role for m in session._loop.messages]
            assert roles.count("user") == 2
            assert roles.count("assistant") == 2
        finally:
            await session.close()


class TestCallbackTracking:
    async def test_on_tool_call_callback_fires(self, tmp_path):
        """The agent loop should invoke on_tool_call for each tool call it executes."""
        target = tmp_path / "x.txt"
        target.write_text("data")
        seen: list[tuple[str, str]] = []

        async def cb(call_id: str, name: str, arguments: dict) -> None:
            seen.append((name, arguments.get("path", "")))

        provider = ScriptedProvider(
            [
                Turn(
                    tool_calls=[ScriptedToolCall(name="read", arguments={"path": "x.txt"})],
                    stop_reason="tool_use",
                ),
                Turn(text="ok"),
            ]
        )
        session = await _session(tmp_path, provider)
        try:
            session._loop._on_tool_call = cb
            await session.send("read x")
            assert seen == [("read", "x.txt")]
        finally:
            await session.close()

    async def test_on_tool_result_callback_fires(self, tmp_path):
        target = tmp_path / "y.txt"
        target.write_text("hello")
        seen: list[tuple[str, bool]] = []

        async def cb(call_id: str, name: str, content: str, is_error: bool) -> None:
            seen.append((name, is_error))

        provider = ScriptedProvider(
            [
                Turn(
                    tool_calls=[ScriptedToolCall(name="read", arguments={"path": "y.txt"})],
                    stop_reason="tool_use",
                ),
                Turn(text="ok"),
            ]
        )
        session = await _session(tmp_path, provider)
        try:
            session._loop._on_tool_result = cb
            await session.send("read y")
            assert seen == [("read", False)]
        finally:
            await session.close()
