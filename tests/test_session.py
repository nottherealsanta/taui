"""Tests for taui.session — wiring tests with a mock provider."""

import pytest
from pathlib import Path

from taui.config import Config
from taui.llm_provider.types import ProviderTurnResult, Usage
from taui.session import Session
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
