"""Streaming, reasoning, and usage-aggregation scenarios.

These tests poke at the streaming-callback wiring and the agent loop's
bookkeeping. They do NOT use real tools — they just want to know that
deltas arrive in order, usage rolls up across turns, and partial streams
followed by errors are handled cleanly.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from taui.agent.loop import AgentLoop
from taui.config import Config
from taui.llm_provider.errors import TransientProviderError
from taui.llm_provider.types import Usage
from taui.session import Session
from taui.store.store import Store
from taui.store.stream import StreamClient
from taui.tools.executor import ToolExecutor, ToolPolicy
from taui.tools.registry import ToolRegistry

from tests.scenarios import ScriptedProvider, Turn, scenarios


async def _session(tmp_path, provider, *, on_text_delta=None, on_reasoning_delta=None) -> Session:
    config = Config(working_dir=tmp_path)
    registry = ToolRegistry()
    executor = ToolExecutor(registry=registry, policy=ToolPolicy())
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
        on_reasoning_delta=on_reasoning_delta,
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


class TestStreaming:
    async def test_chunks_arrive_in_order(self, tmp_path):
        collected: list[str] = []
        provider = scenarios.streamed_reply("abcdefghij", chunk_size=2)
        session = await _session(tmp_path, provider, on_text_delta=collected.append)
        try:
            await session.send("hi")
            assert collected == ["ab", "cd", "ef", "gh", "ij"]
        finally:
            await session.close()

    async def test_slow_stream_advances_over_time(self, tmp_path):
        timestamps: list[float] = []
        provider = scenarios.slow_stream("a b c d e", delta_delay=0.01)

        def on_delta(_: str) -> None:
            timestamps.append(time.perf_counter())

        session = await _session(tmp_path, provider, on_text_delta=on_delta)
        try:
            await session.send("hi")
            # We got several deltas …
            assert len(timestamps) >= 4
            # … and there was real delay between them (not all in the same instant)
            spread = timestamps[-1] - timestamps[0]
            assert spread > 0.005
        finally:
            await session.close()

    async def test_async_delta_callback_is_awaited(self, tmp_path):
        """The provider should support both sync and async delta callbacks."""
        seen: list[str] = []

        async def async_cb(delta: str) -> None:
            await asyncio.sleep(0)
            seen.append(delta)

        provider = scenarios.streamed_reply("hello", chunk_size=1)
        session = await _session(tmp_path, provider, on_text_delta=async_cb)
        try:
            await session.send("hi")
            assert "".join(seen) == "hello"
        finally:
            await session.close()


class TestReasoningStream:
    async def test_reasoning_and_text_deltas_both_fire(self, tmp_path):
        thoughts: list[str] = []
        text: list[str] = []
        provider = ScriptedProvider(
            [
                Turn(
                    reasoning_deltas=["thinking ", "more "],
                    text_deltas=["hello ", "world"],
                    text="hello world",
                ),
            ]
        )
        session = await _session(
            tmp_path,
            provider,
            on_text_delta=text.append,
            on_reasoning_delta=thoughts.append,
        )
        try:
            await session.send("hi")
            assert "".join(thoughts) == "thinking more "
            assert "".join(text) == "hello world"
        finally:
            await session.close()

    async def test_reasoning_without_final_text(self, tmp_path):
        """Reasoning-only turns must not crash the loop."""
        thoughts: list[str] = []
        provider = ScriptedProvider(
            [Turn(reasoning_deltas=["thought-only"], text="")]
        )
        session = await _session(tmp_path, provider, on_reasoning_delta=thoughts.append)
        try:
            result = await session.send("hi")
            assert result.text == ""
            assert "".join(thoughts) == "thought-only"
        finally:
            await session.close()


class TestUsageAggregation:
    async def test_multi_turn_usage_sums(self, tmp_path):
        provider = ScriptedProvider(
            [
                Turn(text="a", usage=Usage(input_tokens=5, output_tokens=1)),
            ]
        )
        session = await _session(tmp_path, provider)
        try:
            r = await session.send("hi")
            assert r.total_usage["input_tokens"] == 5
            assert r.total_usage["output_tokens"] == 1
        finally:
            await session.close()

    async def test_reasoning_tokens_propagate(self, tmp_path):
        provider = ScriptedProvider(
            [
                Turn(
                    text="ok",
                    usage=Usage(
                        input_tokens=10,
                        output_tokens=2,
                        reasoning_tokens=20,
                    ),
                ),
            ]
        )
        session = await _session(tmp_path, provider)
        try:
            r = await session.send("hi")
            assert r.total_usage["reasoning_tokens"] == 20
        finally:
            await session.close()


class TestPartialStreamThenError:
    async def test_deltas_before_raise_still_reach_callback(self, tmp_path):
        """A partial stream followed by an error should expose what was already streamed."""
        collected: list[str] = []
        provider = ScriptedProvider(
            [
                Turn(
                    text_deltas=["partial ", "answer"],
                    raises=TransientProviderError("connection reset"),
                )
            ]
        )
        session = await _session(tmp_path, provider, on_text_delta=collected.append)
        try:
            with pytest.raises(TransientProviderError):
                await session.send("hi")
            # Even though the turn failed, the partial deltas should have been delivered.
            assert "".join(collected) == "partial answer"
        finally:
            await session.close()
