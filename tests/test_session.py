"""Tests for taui.session — wiring tests with a mock provider."""

import pytest
from pathlib import Path

from taui.config import Config
from taui.llm_provider.types import ProviderTurnResult, Usage
from taui.session import Session
from taui.store.events import EventType
from taui.tools.builtins import register_builtins
from taui.tools.registry import ToolRegistry


class MockProvider:
    """Minimal mock that satisfies the LLM duck-type contract."""

    def __init__(self, responses: list[str] | None = None):
        self._responses = list(responses or ["Hello!"])
        self._call_count = 0

    async def create_turn(self, messages, model, *, tools=None, **kwargs):
        text = (
            self._responses[self._call_count]
            if self._call_count < len(self._responses)
            else "done"
        )
        self._call_count += 1
        return ProviderTurnResult(
            response_id=None,
            text=text,
            tool_calls=[],
            usage=Usage(input_tokens=10, output_tokens=5),
        )


class TestSessionWiring:
    async def test_session_manual_assembly(self, tmp_path):
        """Test session works with manually injected mock provider."""
        from taui.agent.loop import AgentLoop
        from taui.store.store import Store
        from taui.store.stream import StreamClient
        from taui.tools.executor import ToolExecutor, ToolPolicy

        config = Config(working_dir=tmp_path)
        provider = MockProvider(["I can help with that!"])

        registry = ToolRegistry()
        register_builtins(registry)
        executor = ToolExecutor(registry=registry, policy=ToolPolicy())

        store = Store(tmp_path)
        await store.connect()
        stream = StreamClient(store)

        loop = AgentLoop(
            llm=provider,
            executor=executor,
            stream=stream,
            system_prompt=config.system_prompt,
            model=config.model,
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

        result = await session.send("hello")
        assert result.text == "I can help with that!"
        assert result.turns == 1

        await session.close()

    async def test_resume_replays_tool_history(self, tmp_path):
        from taui.agent.loop import AgentLoop
        from taui.store.store import Store
        from taui.store.stream import StreamClient
        from taui.tools.executor import ToolExecutor, ToolPolicy

        config = Config(working_dir=tmp_path)
        provider = MockProvider()
        registry = ToolRegistry()
        register_builtins(registry)
        executor = ToolExecutor(registry=registry, policy=ToolPolicy())
        store = Store(tmp_path)
        await store.connect()
        stream = StreamClient(store)

        await store.create_stream("agents/ses-1")
        await store.create_session("ses-1", stream_id="agents/ses-1")
        await store.append("agents/ses-1", EventType.USER_MESSAGE, {"text": "hi"})
        await store.append(
            "agents/ses-1",
            EventType.ASSISTANT_MESSAGE,
            {
                "text": "",
                "tool_calls": [
                    {
                        "call_id": "c1",
                        "name": "echo",
                        "arguments": {"text": "hello"},
                    }
                ],
            },
        )
        await store.append(
            "agents/ses-1",
            EventType.TOOL_CALL,
            {"call_id": "c1", "name": "echo", "arguments": {"text": "hello"}},
        )
        await store.append(
            "agents/ses-1",
            EventType.TOOL_RESULT,
            {"call_id": "c1", "name": "echo", "content": "hello", "error": False},
        )
        await store.append(
            "agents/ses-1",
            EventType.ASSISTANT_MESSAGE,
            {"text": "done", "tool_calls": []},
        )

        loop = AgentLoop(llm=provider, executor=executor, stream=stream, model="test")
        session = Session(
            config=config,
            provider=provider,
            registry=registry,
            executor=executor,
            store=store,
            stream=stream,
            loop=loop,
        )
        session._system_prompt = "system"

        assert await session.resume_session("ses-1") is True
        roles = [msg.role for msg in session._loop.messages]
        assert roles == ["system", "user", "assistant", "tool", "assistant"]
        assistant_tool = session._loop.messages[2]
        assert assistant_tool.tool_calls
        assert assistant_tool.tool_calls[0].call_id == "c1"
        assert session.replay_items[0].kind == "user"
        assert session.replay_items[-1].text == "done"

        await session.close()

    async def test_resume_without_stream_mapping_fails_clearly(self, tmp_path):
        from taui.agent.loop import AgentLoop
        from taui.store.store import Store
        from taui.store.stream import StreamClient
        from taui.tools.executor import ToolExecutor, ToolPolicy

        config = Config(working_dir=tmp_path)
        provider = MockProvider()
        registry = ToolRegistry()
        executor = ToolExecutor(registry=registry, policy=ToolPolicy())
        store = Store(tmp_path)
        await store.connect()
        stream = StreamClient(store)
        await store.create_session("old")

        session = Session(
            config=config,
            provider=provider,
            registry=registry,
            executor=executor,
            store=store,
            stream=stream,
            loop=AgentLoop(llm=provider, executor=executor, stream=stream),
        )

        assert await session.resume_session("old") is False
        assert "no replayable stream" in session.last_resume_error
        await session.close()

    async def test_send_syncs_external_appends_before_continuing(self, tmp_path):
        from taui.agent.loop import AgentLoop
        from taui.store.store import Store
        from taui.store.stream import StreamClient
        from taui.tools.executor import ToolExecutor, ToolPolicy

        config = Config(working_dir=tmp_path)
        provider = MockProvider(["next"])
        registry = ToolRegistry()
        executor = ToolExecutor(registry=registry, policy=ToolPolicy())
        store = Store(tmp_path)
        await store.connect()
        stream = StreamClient(store)

        await store.create_stream("agents/shared")
        await store.create_session("shared", stream_id="agents/shared")
        await store.append("agents/shared", EventType.USER_MESSAGE, {"text": "first"})
        await store.append(
            "agents/shared",
            EventType.ASSISTANT_MESSAGE,
            {"text": "first response", "tool_calls": []},
        )

        loop = AgentLoop(
            agent_id="shared",
            llm=provider,
            executor=executor,
            stream=stream,
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
            session_id="shared",
        )
        session._system_prompt = "system"
        assert await session.resume_session("shared") is True

        await store.append("agents/shared", EventType.USER_MESSAGE, {"text": "other"})
        await store.append(
            "agents/shared",
            EventType.ASSISTANT_MESSAGE,
            {"text": "other response", "tool_calls": []},
        )

        await session.send("continue")
        sent_messages = provider._call_count
        assert sent_messages == 1
        contents = [msg.content for msg in session._loop.messages]
        assert "other" in contents
        assert "continue" in contents

        await session.close()

    async def test_session_multiple_messages(self, tmp_path):
        """Multiple messages maintain conversation."""
        from taui.agent.loop import AgentLoop
        from taui.store.store import Store
        from taui.store.stream import StreamClient
        from taui.tools.executor import ToolExecutor, ToolPolicy

        config = Config(working_dir=tmp_path)
        provider = MockProvider(["first", "second"])

        registry = ToolRegistry()
        register_builtins(registry)
        executor = ToolExecutor(registry=registry, policy=ToolPolicy())

        store = Store(tmp_path)
        await store.connect()
        stream = StreamClient(store)

        loop = AgentLoop(
            llm=provider,
            executor=executor,
            stream=stream,
            model=config.model,
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

        r1 = await session.send("hello")
        assert r1.text == "first"

        r2 = await session.send("followup")
        assert r2.text == "second"

        # Conversation should have system + user + assistant + user + assistant
        assert len(loop.messages) == 5

        await session.close()

    async def test_session_close_is_safe(self, tmp_path):
        """close() doesn't raise even if store is already closed."""
        from taui.agent.loop import AgentLoop
        from taui.store.store import Store
        from taui.store.stream import StreamClient
        from taui.tools.executor import ToolExecutor, ToolPolicy

        config = Config(working_dir=tmp_path)
        provider = MockProvider()

        registry = ToolRegistry()
        executor = ToolExecutor(registry=registry, policy=ToolPolicy())

        store = Store(tmp_path)
        await store.connect()
        stream = StreamClient(store)

        loop = AgentLoop(llm=provider, executor=executor, model="test")

        session = Session(
            config=config,
            provider=provider,
            registry=registry,
            executor=executor,
            store=store,
            stream=stream,
            loop=loop,
        )

        await session.close()
        await session.close()  # double close should be safe

    async def test_reload_extensions_no_registry(self, tmp_path):
        """reload_extensions works when no ext_registry is set."""
        from taui.agent.loop import AgentLoop
        from taui.store.store import Store
        from taui.store.stream import StreamClient
        from taui.tools.executor import ToolExecutor, ToolPolicy
        from taui.hooks import HookRegistry

        config = Config(working_dir=tmp_path)
        provider = MockProvider()

        registry = ToolRegistry()
        register_builtins(registry)
        executor = ToolExecutor(registry=registry, policy=ToolPolicy())

        store = Store(tmp_path)
        await store.connect()
        stream = StreamClient(store)

        loop = AgentLoop(llm=provider, executor=executor, model="test")
        hooks = HookRegistry()

        session = Session(
            config=config,
            provider=provider,
            registry=registry,
            executor=executor,
            store=store,
            stream=stream,
            loop=loop,
            hooks=hooks,
        )
        session._builtin_tool_names = set(registry.names)

        loaded = session.reload_extensions()
        assert loaded == []

        await session.close()

    async def test_reload_extensions_keeps_builtins_out_of_result(self, tmp_path):
        """reload_extensions keeps built-in extensions loaded but reports user files."""
        from taui.agent.loop import AgentLoop
        from taui.extensions import ExtensionRegistry
        from taui.hooks import HookRegistry
        from taui.store.store import Store
        from taui.store.stream import StreamClient
        from taui.tools.executor import ToolExecutor, ToolPolicy

        config = Config(working_dir=tmp_path)
        provider = MockProvider()
        registry = ToolRegistry()
        register_builtins(registry)
        executor = ToolExecutor(registry=registry, policy=ToolPolicy())
        store = Store(tmp_path)
        await store.connect()
        stream = StreamClient(store)
        ext_registry = ExtensionRegistry(tmp_path, include_builtins=True)
        ext_registry.discover()

        session = Session(
            config=config,
            provider=provider,
            registry=registry,
            executor=executor,
            store=store,
            stream=stream,
            loop=AgentLoop(llm=provider, executor=executor, model="test"),
            ext_registry=ext_registry,
            hooks=HookRegistry(),
        )
        session._builtin_tool_names = set(registry.names)

        assert session.reload_extensions() == []
        builtins = [ext for ext in ext_registry.list_all() if ext.scope == "builtin"]
        assert builtins
        assert all(ext.loaded for ext in builtins)

        await session.close()

    async def test_reload_extensions_removes_ext_tools(self, tmp_path):
        """reload_extensions removes tools that weren't in the builtin set."""
        from dataclasses import dataclass, field
        from taui.agent.loop import AgentLoop
        from taui.store.store import Store
        from taui.store.stream import StreamClient
        from taui.tools.executor import ToolExecutor, ToolPolicy
        from taui.hooks import HookRegistry
        from taui.tools.base import ToolResult

        @dataclass
        class FakeTool:
            name: str = "ext_tool"
            description: str = "test"
            parameters: dict = field(default_factory=dict)

            async def execute(self, arguments: dict) -> ToolResult:
                return ToolResult(content="ok")

        config = Config(working_dir=tmp_path)
        provider = MockProvider()

        registry = ToolRegistry()
        register_builtins(registry)
        builtin_names = set(registry.names)

        # Simulate extension adding a tool
        registry.register_or_replace(FakeTool())
        assert "ext_tool" in registry.names

        executor = ToolExecutor(registry=registry, policy=ToolPolicy())

        store = Store(tmp_path)
        await store.connect()
        stream = StreamClient(store)

        loop = AgentLoop(llm=provider, executor=executor, model="test")
        hooks = HookRegistry()

        session = Session(
            config=config,
            provider=provider,
            registry=registry,
            executor=executor,
            store=store,
            stream=stream,
            loop=loop,
            hooks=hooks,
        )
        session._builtin_tool_names = builtin_names

        loaded = session.reload_extensions()
        assert loaded == []
        assert "ext_tool" not in registry.names
        # Builtins still present
        for name in builtin_names:
            assert name in registry.names

        await session.close()
