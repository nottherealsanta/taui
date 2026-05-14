"""End-to-end session resume test."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from taui.agent.loop import AgentLoop
from taui.config import Config
from taui.llm_provider.types import ProviderToolCall, ProviderTurnResult
from taui.session import Session
from taui.store.store import Store
from taui.store.stream import StreamClient
from taui.tools.builtins import register_builtins
from taui.tools.executor import ToolExecutor, ToolPolicy
from taui.tools.registry import ToolRegistry


@dataclass(slots=True)
class MockProvider:
    """Mock LLM that returns canned responses."""

    responses: list[ProviderTurnResult] = field(default_factory=list)
    _call_count: int = 0
    on_text_delta: Any = None
    on_reasoning_delta: Any = None

    async def create_turn(self, messages, model=None, tools=None, **kw):
        if self._call_count < len(self.responses):
            resp = self.responses[self._call_count]
            self._call_count += 1
            return resp
        return ProviderTurnResult(response_id=None, text="(no more responses)", tool_calls=[])


class TestResumeEndToEnd:
    async def test_resume_send_another_turn(self, tmp_path):
        """Full cycle: create → send → resume → send again."""
        config = Config(working_dir=tmp_path)

        provider = MockProvider(responses=[
            ProviderTurnResult(response_id=None, text="Hello! I can help.", tool_calls=[]),
        ])
        registry = ToolRegistry()
        register_builtins(registry)
        executor = ToolExecutor(registry=registry, policy=ToolPolicy())

        store = Store(tmp_path)
        await store.connect()
        stream = StreamClient(store)

        loop = AgentLoop(
            agent_id="test1",
            llm=provider,
            executor=executor,
            stream=stream,
            system_prompt="You are helpful.",
            model="test-model",
        )

        session = Session(
            config=config,
            provider=provider,
            registry=registry,
            executor=executor,
            store=store,
            stream=stream,
            loop=loop,
            session_id="sess-001",
        )
        session._system_prompt = "You are helpful."

        await store.create_session("sess-001", stream_id=loop.stream_id)
        await stream.ensure_stream(loop.stream_id)

        result1 = await session.send("Hello")
        assert "Hello! I can help." in result1.text
        assert session._message_count == 1

        # Now create a new session object (simulating restart)
        provider2 = MockProvider(responses=[
            ProviderTurnResult(
                response_id=None, text="Welcome back! Here's more help.", tool_calls=[]
            ),
        ])
        loop2 = AgentLoop(
            agent_id="test2",
            llm=provider2,
            executor=executor,
            stream=stream,
            system_prompt="You are helpful.",
            model="test-model",
        )

        session2 = Session(
            config=config,
            provider=provider2,
            registry=registry,
            executor=executor,
            store=store,
            stream=stream,
            loop=loop2,
            session_id="temp",
        )
        session2._system_prompt = "You are helpful."

        ok = await session2.resume_session("sess-001")
        assert ok, f"Resume failed: {session2.last_resume_error}"
        assert session2.session_id == "sess-001"
        assert session2._message_count == 1

        msgs = session2._loop._messages
        roles = [m.role for m in msgs]
        assert "system" in roles
        assert "user" in roles
        assert "assistant" in roles

        result2 = await session2.send("What's next?")
        assert "Welcome back" in result2.text
        assert session2._message_count == 2

        await store.close()

    async def test_resume_with_tool_calls(self, tmp_path):
        """Resume preserves tool-call/result pairs."""
        config = Config(working_dir=tmp_path)

        provider = MockProvider(responses=[
            ProviderTurnResult(
                response_id=None,
                text="",
                tool_calls=[
                    ProviderToolCall(
                        call_id="call_1",
                        name="glob",
                        arguments={"pattern": "*.py"},
                    )
                ],
            ),
            ProviderTurnResult(response_id=None, text="Found some files.", tool_calls=[]),
        ])
        registry = ToolRegistry()
        register_builtins(registry)
        for name in registry.names:
            tool = registry.get(name)
            if hasattr(tool, "working_dir"):
                tool.working_dir = tmp_path

        executor = ToolExecutor(registry=registry, policy=ToolPolicy())

        store = Store(tmp_path)
        await store.connect()
        stream = StreamClient(store)

        loop = AgentLoop(
            agent_id="test-tc",
            llm=provider,
            executor=executor,
            stream=stream,
            system_prompt="You are helpful.",
            model="test-model",
        )

        session = Session(
            config=config,
            provider=provider,
            registry=registry,
            executor=executor,
            store=store,
            stream=stream,
            loop=loop,
            session_id="sess-tc",
        )
        session._system_prompt = "You are helpful."

        await store.create_session("sess-tc", stream_id=loop.stream_id)
        await stream.ensure_stream(loop.stream_id)

        result = await session.send("Find files")
        assert "Found some files" in result.text

        provider2 = MockProvider(responses=[
            ProviderTurnResult(response_id=None, text="Continuing.", tool_calls=[]),
        ])
        loop2 = AgentLoop(
            agent_id="test-tc2",
            llm=provider2,
            executor=executor,
            stream=stream,
            system_prompt="You are helpful.",
            model="test-model",
        )
        session2 = Session(
            config=config,
            provider=provider2,
            registry=registry,
            executor=executor,
            store=store,
            stream=stream,
            loop=loop2,
            session_id="temp",
        )
        session2._system_prompt = "You are helpful."

        ok = await session2.resume_session("sess-tc")
        assert ok

        tool_msgs = [m for m in session2._loop._messages if m.role == "tool"]
        assert len(tool_msgs) >= 1

        result2 = await session2.send("Continue")
        assert "Continuing" in result2.text

        await store.close()

    async def test_resume_nonexistent_fails(self, tmp_path):
        """Resuming a non-existent session fails gracefully."""
        config = Config(working_dir=tmp_path)
        provider = MockProvider()
        registry = ToolRegistry()
        executor = ToolExecutor(registry=registry, policy=ToolPolicy())
        store = Store(tmp_path)
        await store.connect()
        stream = StreamClient(store)
        loop = AgentLoop(
            agent_id="t",
            llm=provider,
            executor=executor,
            stream=stream,
            system_prompt="sys",
            model="m",
        )
        session = Session(
            config=config,
            provider=provider,
            registry=registry,
            executor=executor,
            store=store,
            stream=stream,
            loop=loop,
        )
        session._system_prompt = "sys"

        ok = await session.resume_session("nonexistent")
        assert not ok
        assert "not found" in session.last_resume_error.lower()

        await store.close()
