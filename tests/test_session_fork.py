"""Tests for Session.fork() and create_sub_session()."""

from __future__ import annotations

from pathlib import Path

import pytest

from taui.agent.loop import AgentLoop
from taui.config import Config
from taui.llm_provider.types import ProviderTurnResult
from taui.session import Session
from taui.store.store import Store
from taui.store.stream import StreamClient
from taui.tools.builtins import register_builtins
from taui.tools.executor import ToolExecutor, ToolPolicy
from taui.tools.registry import ToolRegistry


class MockProvider:
    async def create_turn(self, messages, model, *, tools=None, **kwargs):
        return ProviderTurnResult(
            response_id=None,
            text="Hello!",
            tool_calls=[],
        )


async def _make_session(tmp_path: Path) -> Session:
    config = Config(working_dir=tmp_path)
    provider = MockProvider()
    registry = ToolRegistry()
    register_builtins(registry)
    for name in registry.names:
        tool = registry.get(name)
        if hasattr(tool, "working_dir"):
            tool.working_dir = tmp_path
    policy = ToolPolicy()
    executor = ToolExecutor(registry=registry, policy=policy)
    store = Store(tmp_path)
    await store.connect()
    stream = StreamClient(store)

    session_id = "test-session"
    loop = AgentLoop(
        agent_id=session_id,
        llm=provider,
        executor=executor,
        stream=stream,
        system_prompt="You are helpful.",
        model="test",
    )

    session = Session(
        config=config,
        provider=provider,
        registry=registry,
        executor=executor,
        store=store,
        stream=stream,
        loop=loop,
        session_id=session_id,
    )
    session._system_prompt = "You are helpful."
    session._extensions_prompt = "Extensions mode."

    await store.create_session(session_id, stream_id=loop.stream_id)
    await stream.ensure_stream(loop.stream_id)

    return session


@pytest.mark.asyncio
class TestSessionFork:
    async def test_fork_creates_new_session(self, tmp_path):
        session = await _make_session(tmp_path)
        await session.send("Hello")

        forked = await session.fork()
        assert forked.session_id != session.session_id
        assert forked._loop.stream_id != session._loop.stream_id
        await session._store.close()

    async def test_fork_at_offset(self, tmp_path):
        session = await _make_session(tmp_path)
        await session.send("First message")
        await session.send("Second message")

        length = await session._stream.get_length(session._loop.stream_id)
        forked = await session.fork(at_offset=length // 2)
        assert forked.session_id != session.session_id
        await session._store.close()

    async def test_fork_preserves_original(self, tmp_path):
        session = await _make_session(tmp_path)
        await session.send("Original")
        original_messages = len(session._loop._messages)

        forked = await session.fork()
        await forked.send("Forked question")

        assert len(session._loop._messages) == original_messages
        await session._store.close()


@pytest.mark.asyncio
class TestCreateSubSession:
    async def test_basic_sub_session(self, tmp_path):
        session = await _make_session(tmp_path)
        sub = await session.create_sub_session()
        assert sub.session_id != session.session_id

        result = await sub.send("Hi")
        assert result.text == "Hello!"
        await session._store.close()

    async def test_sub_session_with_tool_subset(self, tmp_path):
        session = await _make_session(tmp_path)
        sub = await session.create_sub_session(tools=["read", "glob"])
        assert len(sub._registry) == 2
        assert "read" in sub._registry
        assert "write" not in sub._registry
        await session._store.close()

    async def test_sub_session_with_custom_prompt(self, tmp_path):
        session = await _make_session(tmp_path)
        sub = await session.create_sub_session(system_prompt="You are a code reviewer.")
        assert sub._system_prompt == "You are a code reviewer."
        await session._store.close()

    async def test_sub_session_with_model_override(self, tmp_path):
        session = await _make_session(tmp_path)
        sub = await session.create_sub_session(model="custom-model")
        assert sub._loop._model == "custom-model"
        await session._store.close()
