"""Regression tests for tool-call / tool-result ordering in replay and provider send.

Providers (Anthropic, Copilot Claude proxy) require every assistant tool_calls
message to be immediately followed by the corresponding tool result messages.
These tests verify that replay normalization and the build-time validator
enforce that invariant.
"""

from __future__ import annotations

import time

from taui.agent.loop import _assert_tool_call_groups
from taui.agent.types import Message
from taui.llm_provider.types import ProviderToolCall
from taui.session_replay import ReplayTranscript, _normalize_tool_call_groups, replay_events
from taui.store.events import Event, EventType


def _event(
    etype: EventType,
    data: dict,
    *,
    offset: int = 0,
    stream_id: str = "test",
) -> Event:
    return Event(stream_id=stream_id, offset=offset, type=etype, data=data, created_at=time.time())


# ── _normalize_tool_call_groups unit tests ─────────────────────────────


class TestNormalizeToolCallGroups:
    def test_already_ordered(self):
        """Messages already in correct order are preserved."""
        messages = [
            Message(role="user", content="hi"),
            Message(
                role="assistant",
                content=None,
                tool_calls=[ProviderToolCall(call_id="c1", name="echo", arguments={})],
            ),
            Message(role="tool", content="result", tool_call_id="c1", name="echo"),
            Message(role="assistant", content="done"),
        ]
        result = _normalize_tool_call_groups(messages)
        roles = [(m.role, m.tool_call_id) for m in result]
        assert roles == [
            ("user", None),
            ("assistant", None),
            ("tool", "c1"),
            ("assistant", None),
        ]

    def test_delayed_tool_result_moved_up(self):
        """Tool result separated by an intervening message gets moved up."""
        messages = [
            Message(role="user", content="hi"),
            Message(
                role="assistant",
                content=None,
                tool_calls=[ProviderToolCall(call_id="c1", name="echo", arguments={})],
            ),
            # Intervening message (e.g., from another event)
            Message(role="user", content="extra"),
            Message(role="tool", content="result", tool_call_id="c1", name="echo"),
            Message(role="assistant", content="done"),
        ]
        result = _normalize_tool_call_groups(messages)
        roles = [(m.role, m.tool_call_id) for m in result]
        assert roles == [
            ("user", None),
            ("assistant", None),
            ("tool", "c1"),
            ("user", None),
            ("assistant", None),
        ]

    def test_missing_tool_result_synthesized(self):
        """Missing tool result gets a synthetic placeholder."""
        messages = [
            Message(role="user", content="hi"),
            Message(
                role="assistant",
                content=None,
                tool_calls=[ProviderToolCall(call_id="c1", name="echo", arguments={})],
            ),
            Message(role="assistant", content="done"),
        ]
        result = _normalize_tool_call_groups(messages)
        assert len(result) == 4
        tool_msg = result[2]
        assert tool_msg.role == "tool"
        assert tool_msg.tool_call_id == "c1"
        assert "not recorded" in tool_msg.content

    def test_multiple_parallel_tool_calls(self):
        """Multiple parallel tool calls maintain order aligned to assistant."""
        messages = [
            Message(role="user", content="hi"),
            Message(
                role="assistant",
                content=None,
                tool_calls=[
                    ProviderToolCall(call_id="c1", name="read", arguments={}),
                    ProviderToolCall(call_id="c2", name="grep", arguments={}),
                ],
            ),
            # Results in reverse order
            Message(role="tool", content="grep result", tool_call_id="c2", name="grep"),
            Message(role="tool", content="read result", tool_call_id="c1", name="read"),
            Message(role="assistant", content="done"),
        ]
        result = _normalize_tool_call_groups(messages)
        roles = [(m.role, m.tool_call_id) for m in result]
        # Results should follow assistant in call order (c1 then c2)
        assert roles == [
            ("user", None),
            ("assistant", None),
            ("tool", "c1"),
            ("tool", "c2"),
            ("assistant", None),
        ]

    def test_mixed_parallel_calls_one_missing(self):
        """One of multiple parallel results missing gets synthesized."""
        messages = [
            Message(role="user", content="hi"),
            Message(
                role="assistant",
                content=None,
                tool_calls=[
                    ProviderToolCall(call_id="c1", name="read", arguments={}),
                    ProviderToolCall(call_id="c2", name="grep", arguments={}),
                ],
            ),
            # Only c1 has a result
            Message(role="tool", content="read result", tool_call_id="c1", name="read"),
            Message(role="assistant", content="done"),
        ]
        result = _normalize_tool_call_groups(messages)
        assert result[2].role == "tool"
        assert result[2].tool_call_id == "c1"
        assert result[3].role == "tool"
        assert result[3].tool_call_id == "c2"
        assert "not recorded" in result[3].content

    def test_no_tool_calls_passthrough(self):
        """Messages without tool calls pass through unchanged."""
        messages = [
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
        ]
        result = _normalize_tool_call_groups(messages)
        assert result == messages

    def test_multiple_tool_call_groups(self):
        """Multiple sequential tool-call groups are each normalized."""
        messages = [
            Message(role="user", content="hi"),
            Message(
                role="assistant",
                content=None,
                tool_calls=[ProviderToolCall(call_id="c1", name="read", arguments={})],
            ),
            Message(role="tool", content="result1", tool_call_id="c1", name="read"),
            Message(role="user", content="next"),
            Message(
                role="assistant",
                content=None,
                tool_calls=[ProviderToolCall(call_id="c2", name="grep", arguments={})],
            ),
            # Result for c2 is separated by an error message
            Message(role="user", content="oops"),
            Message(role="tool", content="result2", tool_call_id="c2", name="grep"),
            Message(role="assistant", content="done"),
        ]
        result = _normalize_tool_call_groups(messages)
        roles = [(m.role, m.tool_call_id) for m in result]
        assert roles == [
            ("user", None),
            ("assistant", None),
            ("tool", "c1"),
            ("user", None),
            ("assistant", None),
            ("tool", "c2"),
            ("user", None),
            ("assistant", None),
        ]


# ── replay_events integration tests ──────────────────────────────────


class TestReplayEventsToolOrdering:
    def test_modern_stream_correct_order(self):
        """Modern stream with ASSISTANT_MESSAGE.tool_calls and immediate results."""
        events = [
            _event(EventType.USER_MESSAGE, {"text": "hi"}, offset=0),
            _event(
                EventType.ASSISTANT_MESSAGE,
                {
                    "text": "",
                    "tool_calls": [
                        {"call_id": "c1", "name": "echo", "arguments": {"text": "hello"}},
                    ],
                },
                offset=1,
            ),
            _event(EventType.TOOL_CALL, {"call_id": "c1", "name": "echo", "arguments": {"text": "hello"}}, offset=2),
            _event(EventType.TOOL_RESULT, {"call_id": "c1", "name": "echo", "content": "hello", "error": False}, offset=3),
            _event(EventType.ASSISTANT_MESSAGE, {"text": "done", "tool_calls": []}, offset=4),
        ]
        transcript = replay_events(events)
        roles = [(m.role, m.tool_call_id) for m in transcript.messages]
        assert roles == [
            ("user", None),
            ("assistant", None),
            ("tool", "c1"),
            ("assistant", None),
        ]

    def test_legacy_stream_tool_call_result_pairs(self):
        """Legacy stream with only TOOL_CALL/TOOL_RESULT pairs."""
        events = [
            _event(EventType.USER_MESSAGE, {"text": "hi"}, offset=0),
            _event(EventType.TOOL_CALL, {"call_id": "c1", "name": "echo", "arguments": {}}, offset=1),
            _event(EventType.TOOL_RESULT, {"call_id": "c1", "name": "echo", "content": "hello"}, offset=2),
            _event(EventType.ASSISTANT_MESSAGE, {"text": "done", "tool_calls": []}, offset=3),
        ]
        transcript = replay_events(events)
        roles = [(m.role, m.tool_call_id) for m in transcript.messages]
        assert roles == [
            ("user", None),
            ("assistant", None),  # synthesized from TOOL_CALL
            ("tool", "c1"),
            ("assistant", None),
        ]

    def test_delayed_result_in_stream(self):
        """Tool result delayed by intervening events gets moved to correct position."""
        events = [
            _event(EventType.USER_MESSAGE, {"text": "hi"}, offset=0),
            _event(
                EventType.ASSISTANT_MESSAGE,
                {
                    "text": "",
                    "tool_calls": [
                        {"call_id": "c1", "name": "echo", "arguments": {}},
                    ],
                },
                offset=1,
            ),
            _event(EventType.TOOL_CALL, {"call_id": "c1", "name": "echo", "arguments": {}}, offset=2),
            # Intervening usage/error event causes an extra message between
            _event(EventType.USAGE, {"input_tokens": 100, "output_tokens": 50}, offset=3),
            # Imagine the tool result comes after some other event...
            _event(EventType.TOOL_RESULT, {"call_id": "c1", "name": "echo", "content": "hello"}, offset=4),
            _event(EventType.ASSISTANT_MESSAGE, {"text": "done", "tool_calls": []}, offset=5),
        ]
        transcript = replay_events(events)
        msgs = transcript.messages
        # Find the assistant with tool_calls
        tc_idx = next(i for i, m in enumerate(msgs) if m.role == "assistant" and m.tool_calls)
        # The very next message must be the tool result
        assert msgs[tc_idx + 1].role == "tool"
        assert msgs[tc_idx + 1].tool_call_id == "c1"

    def test_missing_result_in_stream(self):
        """Stream with tool call but no result gets a synthetic result."""
        events = [
            _event(EventType.USER_MESSAGE, {"text": "hi"}, offset=0),
            _event(
                EventType.ASSISTANT_MESSAGE,
                {
                    "text": "",
                    "tool_calls": [
                        {"call_id": "c1", "name": "echo", "arguments": {}},
                    ],
                },
                offset=1,
            ),
            _event(EventType.TOOL_CALL, {"call_id": "c1", "name": "echo", "arguments": {}}, offset=2),
            # No TOOL_RESULT at all
            _event(EventType.ASSISTANT_MESSAGE, {"text": "error happened", "tool_calls": []}, offset=3),
        ]
        transcript = replay_events(events)
        msgs = transcript.messages
        tc_idx = next(i for i, m in enumerate(msgs) if m.role == "assistant" and m.tool_calls)
        assert msgs[tc_idx + 1].role == "tool"
        assert msgs[tc_idx + 1].tool_call_id == "c1"
        assert "not recorded" in msgs[tc_idx + 1].content

    def test_items_preserve_stream_order(self):
        """ReplayItems preserve original stream event order for TUI rendering."""
        events = [
            _event(EventType.USER_MESSAGE, {"text": "hi"}, offset=0),
            _event(
                EventType.ASSISTANT_MESSAGE,
                {
                    "text": "",
                    "tool_calls": [
                        {"call_id": "c1", "name": "echo", "arguments": {}},
                    ],
                },
                offset=1,
            ),
            _event(EventType.TOOL_CALL, {"call_id": "c1", "name": "echo", "arguments": {}}, offset=2),
            _event(EventType.USAGE, {"input_tokens": 100, "output_tokens": 50}, offset=3),
            _event(EventType.TOOL_RESULT, {"call_id": "c1", "name": "echo", "content": "hello"}, offset=4),
            _event(EventType.ASSISTANT_MESSAGE, {"text": "done", "tool_calls": []}, offset=5),
        ]
        transcript = replay_events(events)
        kinds = [item.kind for item in transcript.items]
        # Items are in stream order (not normalized)
        assert kinds == ["user", "tool_call", "usage", "tool_result", "assistant"]


# ── _assert_tool_call_groups (loop-level validator) ────────────────────


class TestAssertToolCallGroups:
    def test_already_valid(self):
        """Valid ordering passes through unchanged."""
        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "echo", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
            {"role": "assistant", "content": "done"},
        ]
        result = _assert_tool_call_groups(messages)
        assert [m["role"] for m in result] == ["user", "assistant", "tool", "assistant"]

    def test_separated_result_repaired(self):
        """Tool result separated by user message gets moved."""
        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "echo", "arguments": "{}"}},
                ],
            },
            {"role": "user", "content": "extra"},
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
            {"role": "assistant", "content": "done"},
        ]
        result = _assert_tool_call_groups(messages)
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert result[2]["role"] == "tool"
        assert result[2]["tool_call_id"] == "c1"
        assert result[3]["role"] == "user"

    def test_missing_result_synthesized(self):
        """Missing tool result gets a synthetic placeholder at build time."""
        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "echo", "arguments": "{}"}},
                ],
            },
            {"role": "assistant", "content": "done"},
        ]
        result = _assert_tool_call_groups(messages)
        assert result[2]["role"] == "tool"
        assert result[2]["tool_call_id"] == "c1"
        assert "not recorded" in result[2]["content"]

    def test_no_tool_calls_fast_path(self):
        """Messages without tool calls pass through without modification."""
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = _assert_tool_call_groups(messages)
        assert result is messages  # same object (fast path)


# ── Session-level integration test ────────────────────────────────────


class TestResumeToolCallOrdering:
    async def test_resumed_messages_have_correct_tool_ordering(self, tmp_path):
        """After resume with malformed stream, loop messages are provider-safe."""
        from taui.agent.loop import AgentLoop
        from taui.config import Config
        from taui.llm_provider.types import ProviderTurnResult, Usage
        from taui.session import Session
        from taui.store.store import Store
        from taui.store.stream import StreamClient
        from taui.tools.builtins import register_builtins
        from taui.tools.executor import ToolExecutor, ToolPolicy
        from taui.tools.registry import ToolRegistry

        class RecordingProvider:
            """Mock that records exactly what messages were sent."""

            sent_messages: list[list[dict]] = []

            async def create_turn(self, messages, model=None, tools=None, **kw):
                self.sent_messages.append(list(messages))
                return ProviderTurnResult(
                    response_id=None,
                    text="ok",
                    tool_calls=[],
                    usage=Usage(input_tokens=10, output_tokens=5),
                )

        config = Config(working_dir=tmp_path)
        provider = RecordingProvider()
        registry = ToolRegistry()
        register_builtins(registry)
        executor = ToolExecutor(registry=registry, policy=ToolPolicy())
        store = Store(tmp_path)
        await store.connect()
        stream = StreamClient(store)

        # Build a malformed stream: tool result separated by a usage event
        await store.create_stream("agents/ses-bad")
        await store.create_session("ses-bad", stream_id="agents/ses-bad")
        await store.append("agents/ses-bad", EventType.USER_MESSAGE, {"text": "find files"})
        await store.append(
            "agents/ses-bad",
            EventType.ASSISTANT_MESSAGE,
            {
                "text": "",
                "tool_calls": [
                    {"call_id": "c1", "name": "glob", "arguments": {"pattern": "*.py"}},
                    {"call_id": "c2", "name": "read", "arguments": {"path": "foo.py"}},
                ],
            },
        )
        await store.append(
            "agents/ses-bad",
            EventType.TOOL_CALL,
            {"call_id": "c1", "name": "glob", "arguments": {"pattern": "*.py"}},
        )
        await store.append(
            "agents/ses-bad",
            EventType.TOOL_CALL,
            {"call_id": "c2", "name": "read", "arguments": {"path": "foo.py"}},
        )
        # Intervening usage event
        await store.append(
            "agents/ses-bad",
            EventType.USAGE,
            {"input_tokens": 100, "output_tokens": 50},
        )
        # Results come after usage
        await store.append(
            "agents/ses-bad",
            EventType.TOOL_RESULT,
            {"call_id": "c2", "name": "read", "content": "file content", "error": False},
        )
        await store.append(
            "agents/ses-bad",
            EventType.TOOL_RESULT,
            {"call_id": "c1", "name": "glob", "content": "foo.py\nbar.py", "error": False},
        )
        await store.append(
            "agents/ses-bad",
            EventType.ASSISTANT_MESSAGE,
            {"text": "Found the files.", "tool_calls": []},
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

        assert await session.resume_session("ses-bad") is True

        # Verify internal messages are normalized
        msgs = session._loop.messages
        for i, msg in enumerate(msgs):
            if msg.role == "assistant" and msg.tool_calls:
                # Every tool_call_id must appear immediately after
                for j, tc in enumerate(msg.tool_calls):
                    next_msg = msgs[i + 1 + j]
                    assert next_msg.role == "tool", (
                        f"Expected tool at index {i + 1 + j}, got {next_msg.role}"
                    )
                    assert next_msg.tool_call_id == tc.call_id, (
                        f"Expected tool_call_id={tc.call_id}, got {next_msg.tool_call_id}"
                    )

        # Send a message and verify the provider sees correct ordering
        await session.send("continue")
        assert len(provider.sent_messages) == 1
        sent = provider.sent_messages[0]
        for i, msg in enumerate(sent):
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for j, tc in enumerate(msg["tool_calls"]):
                    call_id = tc.get("id") or ""
                    next_msg = sent[i + 1 + j]
                    assert next_msg["role"] == "tool", (
                        f"Provider saw non-tool at index {i + 1 + j}: {next_msg}"
                    )
                    assert next_msg.get("tool_call_id") == call_id

        await session.close()

    async def test_resumed_missing_result_does_not_crash(self, tmp_path):
        """Resume with a tool call that never received a result doesn't crash."""
        from taui.agent.loop import AgentLoop
        from taui.config import Config
        from taui.llm_provider.types import ProviderTurnResult, Usage
        from taui.session import Session
        from taui.store.store import Store
        from taui.store.stream import StreamClient
        from taui.tools.builtins import register_builtins
        from taui.tools.executor import ToolExecutor, ToolPolicy
        from taui.tools.registry import ToolRegistry

        class SimpleProvider:
            async def create_turn(self, messages, model=None, tools=None, **kw):
                return ProviderTurnResult(
                    response_id=None,
                    text="recovered",
                    tool_calls=[],
                    usage=Usage(input_tokens=10, output_tokens=5),
                )

        config = Config(working_dir=tmp_path)
        provider = SimpleProvider()
        registry = ToolRegistry()
        register_builtins(registry)
        executor = ToolExecutor(registry=registry, policy=ToolPolicy())
        store = Store(tmp_path)
        await store.connect()
        stream = StreamClient(store)

        # Stream where tool result is completely missing
        await store.create_stream("agents/ses-missing")
        await store.create_session("ses-missing", stream_id="agents/ses-missing")
        await store.append("agents/ses-missing", EventType.USER_MESSAGE, {"text": "do something"})
        await store.append(
            "agents/ses-missing",
            EventType.ASSISTANT_MESSAGE,
            {
                "text": "",
                "tool_calls": [
                    {"call_id": "c1", "name": "read", "arguments": {"path": "x.py"}},
                ],
            },
        )
        await store.append(
            "agents/ses-missing",
            EventType.TOOL_CALL,
            {"call_id": "c1", "name": "read", "arguments": {"path": "x.py"}},
        )
        # No TOOL_RESULT -- session was interrupted
        # But there's a final assistant message from a later replay or partial stream
        await store.append(
            "agents/ses-missing",
            EventType.ASSISTANT_MESSAGE,
            {"text": "I was interrupted", "tool_calls": []},
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

        assert await session.resume_session("ses-missing") is True

        # Verify synthetic result was injected
        msgs = session._loop.messages
        tc_idx = next(i for i, m in enumerate(msgs) if m.role == "assistant" and m.tool_calls)
        assert msgs[tc_idx + 1].role == "tool"
        assert msgs[tc_idx + 1].tool_call_id == "c1"
        assert "not recorded" in msgs[tc_idx + 1].content

        # Sending should succeed without provider errors
        result = await session.send("continue")
        assert result.text == "recovered"

        await session.close()
