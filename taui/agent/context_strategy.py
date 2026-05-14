"""Pluggable context compaction strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from taui.agent.types import Message


class ContextStrategy(Protocol):
    """Interface for context compaction strategies."""

    name: str

    def prepare(self, messages: list[Message], max_tokens: int) -> list[Message]:
        """Compact messages before an LLM call. May modify in place."""
        ...

    def on_turn_result(self, usage: dict[str, Any]) -> None:
        """Callback after each LLM turn with usage stats."""
        ...


@dataclass(slots=True)
class DropOldestStrategy:
    """Drop-oldest compaction (current default behavior)."""

    name: str = "drop_oldest"

    def prepare(self, messages: list[Message], max_tokens: int) -> list[Message]:
        from taui.agent.context import compact_messages

        compact_messages(messages, max_input_tokens=max_tokens)
        return messages

    def on_turn_result(self, usage: dict[str, Any]) -> None:
        pass


class ContextStrategyRegistry:
    """Registry of named context compaction strategies."""

    def __init__(self) -> None:
        self._strategies: dict[str, ContextStrategy] = {}
        self.register(DropOldestStrategy())

    def register(self, strategy: ContextStrategy) -> None:
        self._strategies[strategy.name] = strategy

    def get(self, name: str) -> ContextStrategy | None:
        return self._strategies.get(name)

    def names(self) -> list[str]:
        return sorted(self._strategies.keys())

    def unregister(self, name: str) -> None:
        self._strategies.pop(name, None)
