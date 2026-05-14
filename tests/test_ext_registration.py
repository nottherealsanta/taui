"""Tests for extension registration of variants, context strategies, and providers."""

from __future__ import annotations

from taui.agent.context_strategy import (
    ContextStrategyRegistry,
    DropOldestStrategy,
)
from taui.agent.variants import AgentVariant, AgentVariantRegistry
from taui.extensions import ExtensionContext
from taui.llm_provider.ext_registry import ProviderRegistrationProxy


class TestExtensionContextFields:
    def test_context_has_agents_field(self):
        reg = AgentVariantRegistry()
        ctx = ExtensionContext(
            tools=None, commands=None, hooks=None, agents=reg
        )
        assert ctx.agents is reg

    def test_context_has_context_field(self):
        reg = ContextStrategyRegistry()
        ctx = ExtensionContext(
            tools=None, commands=None, hooks=None, context=reg
        )
        assert ctx.context is reg

    def test_context_has_providers_field(self):
        proxy = ProviderRegistrationProxy()
        ctx = ExtensionContext(
            tools=None, commands=None, hooks=None, providers=proxy
        )
        assert ctx.providers is proxy


class TestContextStrategyRegistry:
    def test_default_has_drop_oldest(self):
        reg = ContextStrategyRegistry()
        assert "drop_oldest" in reg.names()

    def test_register_custom(self):
        from dataclasses import dataclass

        @dataclass(slots=True)
        class Custom:
            name: str = "custom"

            def prepare(self, messages, max_tokens):
                return messages

            def on_turn_result(self, usage):
                pass

        reg = ContextStrategyRegistry()
        reg.register(Custom())
        assert reg.get("custom") is not None
        assert "custom" in reg.names()

    def test_unregister(self):
        reg = ContextStrategyRegistry()
        reg.unregister("drop_oldest")
        assert reg.get("drop_oldest") is None


class TestVariantRegistrationViaExtension:
    def test_extension_can_register_variant(self):
        reg = AgentVariantRegistry()
        ctx = ExtensionContext(
            tools=None, commands=None, hooks=None, agents=reg
        )
        ctx.agents.register(AgentVariant(
            name="review",
            description="Code review agent",
            read_only=True,
        ))
        assert reg.get("review") is not None
        assert reg.get("review").read_only is True


class TestDropOldestStrategy:
    def test_prepare_returns_messages(self):
        from taui.agent.types import Message

        strategy = DropOldestStrategy()
        msgs = [
            Message(role="system", content="sys"),
            Message(role="user", content="hello"),
        ]
        result = strategy.prepare(msgs, max_tokens=100_000)
        assert len(result) >= 1

    def test_on_turn_result_is_noop(self):
        strategy = DropOldestStrategy()
        strategy.on_turn_result({"input_tokens": 100})
