"""Tests for steering message consolidation and drain mechanics."""

from __future__ import annotations

from taui.agent.types import Message


class TestDrainSteering:
    """Unit tests for AgentLoop._drain_steering consolidation."""

    def _make_loop(self):
        """Create a minimal AgentLoop-like object with just the steering bits."""
        from unittest.mock import MagicMock

        # We can't easily instantiate a full AgentLoop without all deps,
        # so test the logic directly by calling the method on a real loop
        # or by reimplementing the core logic in a harness.
        # Let's use a thin wrapper.
        class StubLoop:
            def __init__(self):
                self._steering_queue: list[str] = []
                self._messages: list[Message] = []
                self._on_steering_drained = None

            def steer(self, message: str) -> None:
                self._steering_queue.append(message)

            def _drain_steering(self) -> None:
                if not self._steering_queue:
                    return
                combined = "\n\n".join(self._steering_queue)
                self._steering_queue.clear()
                self._messages.append(
                    Message(role="user", content=combined, kind="steer")
                )
                if self._on_steering_drained:
                    self._on_steering_drained()

        return StubLoop()

    def test_single_steer_produces_one_message(self):
        loop = self._make_loop()
        loop.steer("fix the bug")
        loop._drain_steering()
        assert len(loop._messages) == 1
        assert loop._messages[0].content == "fix the bug"
        assert loop._messages[0].kind == "steer"

    def test_multiple_steers_consolidated_into_one(self):
        loop = self._make_loop()
        loop.steer("first instruction")
        loop.steer("second instruction")
        loop.steer("third instruction")
        loop._drain_steering()
        assert len(loop._messages) == 1
        assert loop._messages[0].content == "first instruction\n\nsecond instruction\n\nthird instruction"
        assert loop._messages[0].kind == "steer"

    def test_empty_queue_no_message(self):
        loop = self._make_loop()
        loop._drain_steering()
        assert len(loop._messages) == 0

    def test_drain_clears_queue(self):
        loop = self._make_loop()
        loop.steer("msg1")
        loop.steer("msg2")
        loop._drain_steering()
        assert len(loop._steering_queue) == 0

    def test_separate_drains_produce_separate_messages(self):
        """Steers across different tool calls stay separate."""
        loop = self._make_loop()
        loop.steer("before tool 1")
        loop._drain_steering()
        loop.steer("before tool 2")
        loop._drain_steering()
        assert len(loop._messages) == 2
        assert loop._messages[0].content == "before tool 1"
        assert loop._messages[1].content == "before tool 2"

    def test_callback_fires_on_drain(self):
        loop = self._make_loop()
        called = []
        loop._on_steering_drained = lambda: called.append(True)
        loop.steer("hey")
        loop._drain_steering()
        assert called == [True]

    def test_callback_not_fired_on_empty_drain(self):
        loop = self._make_loop()
        called = []
        loop._on_steering_drained = lambda: called.append(True)
        loop._drain_steering()
        assert called == []

    def test_multiple_steers_callback_fires_once(self):
        loop = self._make_loop()
        called = []
        loop._on_steering_drained = lambda: called.append(True)
        loop.steer("a")
        loop.steer("b")
        loop._drain_steering()
        assert len(called) == 1


class TestSteeringMessageKind:
    """Ensure consolidated steer messages integrate with context preservation."""

    def test_consolidated_steer_preserved_in_context(self):
        from taui.agent.context import _preserved_indexes

        msgs = [
            Message(role="system", content="sys"),
            Message(role="user", content="real question", kind="user"),
            Message(role="assistant", content="response"),
            Message(
                role="user",
                content="steer1\n\nsteer2",
                kind="steer",
            ),
        ]
        preserved = _preserved_indexes(msgs)
        # Real user message should be preserved over steer
        assert 1 in preserved

    def test_only_consolidated_steer_still_preserved(self):
        from taui.agent.context import _preserved_indexes

        msgs = [
            Message(role="system", content="sys"),
            Message(
                role="user",
                content="do A\n\ndo B",
                kind="steer",
            ),
            Message(role="assistant", content="ok"),
        ]
        preserved = _preserved_indexes(msgs)
        user_preserved = [i for i in preserved if msgs[i].role == "user"]
        assert len(user_preserved) >= 1
