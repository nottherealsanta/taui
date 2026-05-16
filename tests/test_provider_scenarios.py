"""Scenario tests — run the ScriptedProvider scenarios through Session/AgentLoop.

These tests are the contract between the scripted-provider harness and the
rest of taui. If a scenario regresses here, the visual snapshot tests built on
the same harness will be unreliable too.

Each test follows the same shape as `tests/test_session.py::TestSessionWiring`:
build a Session manually with the scripted provider, send one user message,
and assert on the observable behavior (text, deltas, errors).
"""

from __future__ import annotations

import pytest

from taui.agent.loop import AgentLoop
from taui.config import Config
from taui.llm_provider.errors import AuthExpiredError, QuotaExceededError
from taui.session import Session
from taui.store.store import Store
from taui.store.stream import StreamClient
from taui.tools.executor import ToolExecutor, ToolPolicy
from taui.tools.registry import ToolRegistry
from tests.scenarios import ScriptedProvider, scenarios


async def _build_session(
    tmp_path,
    provider: ScriptedProvider,
    *,
    register_tools: bool = False,
    on_text_delta=None,
) -> Session:
    config = Config(working_dir=tmp_path)
    registry = ToolRegistry()
    if register_tools:
        from taui.tools.builtins import register_builtins

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


class TestHappyPath:
    async def test_returns_final_text(self, tmp_path):
        session = await _build_session(tmp_path, scenarios.happy_path("Hi!"))
        try:
            result = await session.send("hello")
            assert result.text == "Hi!"
            assert result.turns == 1
        finally:
            await session.close()

    async def test_streamed_reply_emits_deltas(self, tmp_path):
        collected: list[str] = []
        session = await _build_session(
            tmp_path,
            scenarios.streamed_reply("Hello world", chunk_size=3),
            on_text_delta=lambda d: collected.append(d),
        )
        try:
            result = await session.send("hi")
            assert result.text == "Hello world"
            assert "".join(collected) == "Hello world"
            assert len(collected) > 1
        finally:
            await session.close()


class TestRecovery:
    async def test_rate_limit_then_recover(self, tmp_path):
        # AgentLoop does NOT catch TransientProviderError today — surface that
        # explicitly so any future retry behavior is a conscious change.
        from taui.llm_provider.errors import TransientProviderError

        session = await _build_session(
            tmp_path, scenarios.rate_limit_then_recover("recovered")
        )
        try:
            with pytest.raises(TransientProviderError):
                await session.send("hi")
        finally:
            await session.close()

    async def test_context_overflow_triggers_compaction_retry(self, tmp_path):
        session = await _build_session(
            tmp_path, scenarios.context_overflow_then_recover("ok")
        )
        try:
            # The loop's auto-recovery path compacts and retries on overflow,
            # so the second scripted turn returns successfully.
            result = await session.send("hi")
            assert result.text == "ok"
            assert session._provider.call_count == 2
        finally:
            await session.close()


class TestTerminalErrors:
    async def test_auth_expired_propagates(self, tmp_path):
        session = await _build_session(tmp_path, scenarios.auth_expired())
        try:
            with pytest.raises(AuthExpiredError):
                await session.send("hi")
        finally:
            await session.close()

    async def test_quota_exceeded_propagates(self, tmp_path):
        session = await _build_session(tmp_path, scenarios.quota_exceeded(60))
        try:
            with pytest.raises(QuotaExceededError) as ei:
                await session.send("hi")
            assert ei.value.resets_in_seconds == 60
        finally:
            await session.close()


class TestEmptyResponse:
    async def test_empty_text_does_not_crash(self, tmp_path):
        session = await _build_session(tmp_path, scenarios.empty_response())
        try:
            result = await session.send("hi")
            assert result.text == ""
        finally:
            await session.close()


class TestReasoning:
    async def test_reasoning_deltas_fire(self, tmp_path):
        thoughts: list[str] = []
        provider = scenarios.with_reasoning("hmm let me think", "Result.")
        session = await _build_session(tmp_path, provider)
        try:
            session._loop._on_reasoning_delta = lambda d: thoughts.append(d)
            result = await session.send("hi")
            assert result.text == "Result."
            assert "".join(thoughts) == "hmm let me think"
        finally:
            await session.close()
