"""Edge-case provider scenarios — encoding, truncation, large content.

These tests catch the sort of bug that doesn't show up until production
content lands: non-ASCII characters, huge tool outputs, abnormally long
streams, and so on.
"""

from __future__ import annotations

from taui.agent.loop import AgentLoop
from taui.config import Config
from taui.session import Session
from taui.store.store import Store
from taui.store.stream import StreamClient
from taui.tools.builtins import register_builtins
from taui.tools.executor import PolicyDecision, ToolExecutor, ToolPolicy
from taui.tools.registry import ToolRegistry
from taui.tools.truncation import TruncationStore

from tests.scenarios import ScriptedProvider, ScriptedToolCall, Turn, scenarios


async def _session_with_truncation(tmp_path, provider) -> Session:
    config = Config(working_dir=tmp_path)
    registry = ToolRegistry()
    register_builtins(registry)
    for name in registry.names:
        tool = registry.get(name)
        if hasattr(tool, "working_dir"):
            tool.working_dir = tmp_path
    policy = ToolPolicy(overrides={"read": PolicyDecision.AUTO})
    truncation = TruncationStore(max_inline_bytes=512)  # small for fast tests
    executor = ToolExecutor(registry=registry, policy=policy, truncation_store=truncation)
    executor._truncation_store = truncation
    store = Store(tmp_path)
    await store.connect()
    stream = StreamClient(store)
    loop = AgentLoop(
        llm=provider,
        executor=executor,
        stream=stream,
        system_prompt="test",
        model="m",
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


class TestUnicodeContent:
    async def test_cjk_reply_round_trips(self, tmp_path):
        reply = "你好世界 — emoji ✨ 🎉 — café naïve"
        collected: list[str] = []
        from tests.test_scenario_streaming import _session

        provider = scenarios.streamed_reply(reply, chunk_size=5)
        session = await _session(tmp_path, provider, on_text_delta=collected.append)
        try:
            result = await session.send("hi")
            assert result.text == reply
            assert "".join(collected) == reply
        finally:
            await session.close()

    async def test_unicode_in_tool_call_arguments(self, tmp_path):
        target = tmp_path / "héllo.txt"
        target.write_text("naïve content 中文")
        provider = ScriptedProvider(
            [
                Turn(
                    tool_calls=[ScriptedToolCall(name="read", arguments={"path": "héllo.txt"})],
                    stop_reason="tool_use",
                ),
                Turn(text="✓"),
            ]
        )
        session = await _session_with_truncation(tmp_path, provider)
        try:
            result = await session.send("read it")
            assert result.text == "✓"
            tool_msg = next(m for m in session._loop.messages if m.role == "tool")
            assert "naïve content 中文" in tool_msg.content
        finally:
            await session.close()


class TestTruncation:
    async def test_large_tool_output_gets_truncated(self, tmp_path):
        # Build a 4 KiB file — over the 512-byte truncation threshold.
        big = tmp_path / "big.txt"
        big.write_text("xxxxxxxx\n" * 500)
        provider = ScriptedProvider(
            [
                Turn(
                    tool_calls=[ScriptedToolCall(name="read", arguments={"path": "big.txt"})],
                    stop_reason="tool_use",
                ),
                Turn(text="ack"),
            ]
        )
        session = await _session_with_truncation(tmp_path, provider)
        try:
            await session.send("read big")
            tool_msg = next(m for m in session._loop.messages if m.role == "tool")
            assert "truncated" in tool_msg.content
            assert "peek" in tool_msg.content
            # And the full content is recoverable via the peek handle.
            handles = session._executor._truncation_store.handles
            assert len(handles) == 1
            full = session._executor._truncation_store.peek(handles[0], offset=0, limit=10_000)
            assert "xxxxxxxx" in full
        finally:
            await session.close()


class TestEmptyDeltas:
    async def test_empty_delta_list_does_not_call_callback(self, tmp_path):
        from tests.test_scenario_streaming import _session

        collected: list[str] = []
        provider = ScriptedProvider([Turn(text="abc")])  # no text_deltas
        session = await _session(tmp_path, provider, on_text_delta=collected.append)
        try:
            result = await session.send("hi")
            assert result.text == "abc"
            assert collected == []  # no streaming → no deltas
        finally:
            await session.close()


class TestVeryLongStream:
    async def test_many_small_chunks(self, tmp_path):
        from tests.test_scenario_streaming import _session

        reply = "x" * 1000
        provider = scenarios.streamed_reply(reply, chunk_size=10)
        collected: list[str] = []
        session = await _session(tmp_path, provider, on_text_delta=collected.append)
        try:
            await session.send("hi")
            assert "".join(collected) == reply
            assert len(collected) == 100
        finally:
            await session.close()
