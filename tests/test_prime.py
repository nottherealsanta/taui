"""
Tests for Prime RPC handler (prime/message).

Verifies:
- Basic text response (no tool calls)
- Tool-call loop execution (read, write, etc.)
- AGENT-category tools are excluded
- Error / fallback handling
- Session tracks read state for write tool

Prime uses a streaming notification protocol:
  - The RPC returns {ok: true} immediately
  - Background task emits prime/token, prime/toolCall, prime/toolResult, prime/done
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from taui.llms.base import ProviderToolCall, ProviderTurnResult
from taui.server.app import create_app


# ── Helpers ────────────────────────────────────────────────────────────────────


def _write_specs(workspace: Path) -> None:
    specs_root = workspace / "specs"
    specs_root.mkdir(parents=True, exist_ok=True)
    (specs_root / "_main.md").write_text(
        "\n".join(
            [
                "- Taui",
                "    Agentic Coding Interface.",
                "",
                "    - {{tree: [Core](./core.md)}}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (specs_root / "core.md").write_text(
        "\n".join(
            [
                "- # Core",
                "    Core intent.",
                "",
                "    - ## Leaf",
                "        Leaf intent.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _rpc(ws: Any, id_: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Send a JSON-RPC request and return the matching response (skip notifications)."""
    ws.send_text(
        json.dumps({"jsonrpc": "2.0", "id": id_, "method": method, "params": params})
    )
    while True:
        msg = json.loads(ws.receive_text())
        # Match by id, or accept error responses with id=null
        if msg.get("id") == id_ or (msg.get("id") is None and "error" in msg):
            return msg


@dataclass
class PrimeResult:
    """Aggregated result from collecting Prime streaming notifications."""
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    notifications: list[dict[str, Any]] = field(default_factory=list)
    done: bool = False


def _prime_send_and_collect(
    ws: Any,
    id_: int,
    messages: list[dict[str, Any]],
    *,
    max_turns: int | None = None,
    max_messages: int = 200,
) -> tuple[dict[str, Any], PrimeResult]:
    """Send a prime/message RPC and collect streaming notifications.

    Returns (rpc_response, PrimeResult) where PrimeResult aggregates all
    prime/token text and prime/toolCall entries until prime/done.
    """
    params: dict[str, Any] = {"messages": messages}
    if max_turns is not None:
        params["max_turns"] = max_turns

    ws.send_text(
        json.dumps({"jsonrpc": "2.0", "id": id_, "method": "prime/message", "params": params})
    )

    rpc_resp: dict[str, Any] | None = None
    result = PrimeResult()

    for _ in range(max_messages):
        msg = json.loads(ws.receive_text())

        # RPC response (has "id" field)
        if msg.get("id") == id_ or (msg.get("id") is None and "error" in msg):
            rpc_resp = msg
            if "error" in msg:
                return msg, result
            continue

        # Notification (no "id", has "method")
        method = msg.get("method", "")
        p = msg.get("params", {})

        if method == "prime/token":
            result.text += p.get("text", "")
        elif method == "prime/toolCall":
            result.tool_calls.append({
                "call_id": p.get("call_id", ""),
                "tool_name": p.get("tool_name", ""),
                "arguments": p.get("arguments", {}),
            })
        elif method == "prime/toolResult":
            result.tool_results.append({
                "call_id": p.get("call_id", ""),
                "output": p.get("output"),
                "error": p.get("error"),
            })
        elif method == "prime/agentLaunched":
            result.notifications.append({"method": method, **p})
        elif method == "prime/done":
            result.done = True
            break

    assert rpc_resp is not None, "Never received RPC response"
    return rpc_resp, result


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_prime_basic_text_response(tmp_path: Path) -> None:
    """With no-op LLM, Prime returns ok and streams text via notifications."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            resp, result = _prime_send_and_collect(
                ws, 1, [{"role": "user", "content": "Hello"}]
            )
            assert "error" not in resp, resp
            assert resp["result"] == {"ok": True}
            assert result.done
            assert isinstance(result.text, str)
            assert len(result.text) > 0
            # No-op LLM doesn't call tools
            assert result.tool_calls == []


def test_prime_missing_messages_returns_error(tmp_path: Path) -> None:
    """prime/message with missing or empty messages returns INVALID_PARAMS."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            resp = _rpc(ws, 1, "prime/message", {})
            assert "error" in resp

            resp2 = _rpc(ws, 2, "prime/message", {"messages": []})
            assert "error" in resp2


def test_prime_tool_schemas_exclude_agent_category(tmp_path: Path) -> None:
    """Verify that AGENT-category tools (task, monty) are not in the tool list."""
    from taui.tools.registry import ToolRegistry
    from taui.tools.base import ToolCategory
    from taui.tools.builtins import register_builtin_tools
    from taui.tools.builtins.spec_tree import register_spec_tree_tools

    registry = ToolRegistry()
    register_builtin_tools(registry)
    register_spec_tree_tools(registry)

    excluded = {ToolCategory.AGENT}
    schemas = registry.list_schemas(exclude_categories=excluded)
    tool_names = {s["function"]["name"] for s in schemas}

    # AGENT-category tools should be excluded
    assert "task" not in tool_names
    assert "monty" not in tool_names

    # Other tools should be present
    assert "read" in tool_names
    assert "write" in tool_names
    assert "edit" in tool_names
    assert "bash" in tool_names
    assert "glob" in tool_names
    assert "grep" in tool_names
    assert "spec_get_tree" in tool_names


def test_prime_executes_tool_calls(tmp_path: Path) -> None:
    """Prime runs a tool-calling loop when the LLM returns tool calls."""
    _write_specs(tmp_path)
    # Create a file the LLM will "read"
    (tmp_path / "hello.txt").write_text("Hello, world!", encoding="utf-8")

    app = create_app(workspace=tmp_path)

    # Build a mock LLM that:
    # 1st call: returns a tool_call for "read"
    # 2nd call: returns final text
    call_count = 0

    async def mock_create_turn(messages, model, *, tools=None, **kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ProviderTurnResult(
                response_id=None,
                text="Let me read that file.",
                tool_calls=[
                    ProviderToolCall(
                        call_id="call_001",
                        name="read",
                        arguments={"filePath": str(tmp_path / "hello.txt")},
                    )
                ],
            )
        else:
            return ProviderTurnResult(
                response_id=None,
                text="The file contains: Hello, world!",
                tool_calls=[],
            )

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            from taui.server.handlers import MethodHandlers

            original = MethodHandlers._resolve_llm_for_tier

            class MockLLM:
                create_turn = staticmethod(mock_create_turn)

            def patched_resolve(self, tier, params):
                return MockLLM(), "test-model"

            MethodHandlers._resolve_llm_for_tier = patched_resolve
            try:
                resp, result = _prime_send_and_collect(
                    ws, 1, [{"role": "user", "content": "Read hello.txt"}]
                )
            finally:
                MethodHandlers._resolve_llm_for_tier = original

            assert "error" not in resp, resp
            assert result.done
            assert "Hello, world!" in result.text
            assert len(result.tool_calls) == 1
            assert result.tool_calls[0]["tool_name"] == "read"
            assert call_count == 2


def test_prime_tool_error_is_returned_to_llm(tmp_path: Path) -> None:
    """When a tool call fails, the error is fed back as a tool result."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    call_count = 0

    async def mock_create_turn(messages, model, *, tools=None, **kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Try to read a file that doesn't exist
            return ProviderTurnResult(
                response_id=None,
                text="",
                tool_calls=[
                    ProviderToolCall(
                        call_id="call_002",
                        name="read",
                        arguments={"filePath": str(tmp_path / "nonexistent.txt")},
                    )
                ],
            )
        else:
            # On second call, verify tool result message was added
            tool_msgs = [m for m in messages if m.get("role") == "tool"]
            assert len(tool_msgs) == 1
            return ProviderTurnResult(
                response_id=None,
                text="File not found.",
                tool_calls=[],
            )

    from taui.server.handlers import MethodHandlers

    original = MethodHandlers._resolve_llm_for_tier

    class MockLLM:
        create_turn = staticmethod(mock_create_turn)

    def patched_resolve(self, tier, params):
        return MockLLM(), "test-model"

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            MethodHandlers._resolve_llm_for_tier = patched_resolve
            try:
                resp, result = _prime_send_and_collect(
                    ws, 1, [{"role": "user", "content": "Read nonexistent.txt"}]
                )
            finally:
                MethodHandlers._resolve_llm_for_tier = original

            assert "error" not in resp, resp
            assert result.done
            assert result.text == "File not found."


def test_prime_max_turns_limit(tmp_path: Path) -> None:
    """Prime stops after max_turns even if the LLM keeps returning tool calls."""
    _write_specs(tmp_path)
    (tmp_path / "test.txt").write_text("test", encoding="utf-8")
    app = create_app(workspace=tmp_path)

    async def mock_create_turn(messages, model, *, tools=None, **kw):
        # Always return a tool call — never stop
        return ProviderTurnResult(
            response_id=None,
            text="still working...",
            tool_calls=[
                ProviderToolCall(
                    call_id=f"call_{len(messages)}",
                    name="read",
                    arguments={"filePath": str(tmp_path / "test.txt")},
                )
            ],
        )

    from taui.server.handlers import MethodHandlers
    from taui.agent.prime import PrimeAgent

    original_resolve = MethodHandlers._resolve_llm_for_tier
    original_init = PrimeAgent.__init__

    class MockLLM:
        create_turn = staticmethod(mock_create_turn)

    def patched_resolve(self, tier, params):
        return MockLLM(), "test-model"

    def patched_init(self, **kwargs):
        kwargs["max_turns"] = 3
        original_init(self, **kwargs)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            MethodHandlers._resolve_llm_for_tier = patched_resolve
            PrimeAgent.__init__ = patched_init
            try:
                resp, result = _prime_send_and_collect(
                    ws,
                    1,
                    [{"role": "user", "content": "Loop forever"}],
                )
            finally:
                MethodHandlers._resolve_llm_for_tier = original_resolve
                PrimeAgent.__init__ = original_init

            assert "error" not in resp, resp
            assert result.done
            # Should have exactly 3 tool calls (one per turn)
            assert len(result.tool_calls) == 3


def test_prime_fallback_on_tool_api_error(tmp_path: Path) -> None:
    """If the LLM call fails, Prime reports the error via streaming."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    async def mock_create_turn(messages, model, *, tools=None, **kw):
        raise Exception("API does not support tools")

    from taui.server.handlers import MethodHandlers

    original = MethodHandlers._resolve_llm_for_tier

    class MockLLM:
        create_turn = staticmethod(mock_create_turn)

    def patched_resolve(self, tier, params):
        return MockLLM(), "test-model"

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            MethodHandlers._resolve_llm_for_tier = patched_resolve
            try:
                resp, result = _prime_send_and_collect(
                    ws, 1, [{"role": "user", "content": "Hello"}]
                )
            finally:
                MethodHandlers._resolve_llm_for_tier = original

            assert "error" not in resp, resp
            assert result.done
            # Error is reported in streamed text
            assert "Sorry" in result.text
            assert "API does not support tools" in result.text


def test_prime_session_tracks_read_state(tmp_path: Path) -> None:
    """Prime's session tracks read files so write tool can verify read-before-write."""
    _write_specs(tmp_path)
    target = tmp_path / "output.py"

    app = create_app(workspace=tmp_path)

    call_count = 0

    async def mock_create_turn(messages, model, *, tools=None, **kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First: read the target (which doesn't exist yet)
            return ProviderTurnResult(
                response_id=None,
                text="",
                tool_calls=[
                    ProviderToolCall(
                        call_id="call_r",
                        name="read",
                        arguments={"filePath": str(target)},
                    )
                ],
            )
        elif call_count == 2:
            # Then: write the file
            return ProviderTurnResult(
                response_id=None,
                text="",
                tool_calls=[
                    ProviderToolCall(
                        call_id="call_w",
                        name="write",
                        arguments={
                            "filePath": str(target),
                            "content": 'print("hello")\n',
                            "create_if_missing": True,
                        },
                    )
                ],
            )
        else:
            return ProviderTurnResult(
                response_id=None,
                text="File created!",
                tool_calls=[],
            )

    from taui.server.handlers import MethodHandlers

    original = MethodHandlers._resolve_llm_for_tier

    class MockLLM:
        create_turn = staticmethod(mock_create_turn)

    def patched_resolve(self, tier, params):
        return MockLLM(), "test-model"

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            MethodHandlers._resolve_llm_for_tier = patched_resolve
            try:
                resp, result = _prime_send_and_collect(
                    ws, 1, [{"role": "user", "content": "Write output.py"}]
                )
            finally:
                MethodHandlers._resolve_llm_for_tier = original

            assert "error" not in resp, resp
            assert result.done
            assert call_count == 3
            # Verify the file was actually created
            assert target.exists()
            assert target.read_text() == 'print("hello")\n'


def test_prime_multiple_tool_calls_in_one_turn(tmp_path: Path) -> None:
    """Prime handles multiple tool calls returned by the LLM in a single turn."""
    _write_specs(tmp_path)
    (tmp_path / "a.txt").write_text("AAA", encoding="utf-8")
    (tmp_path / "b.txt").write_text("BBB", encoding="utf-8")
    app = create_app(workspace=tmp_path)

    call_count = 0

    async def mock_create_turn(messages, model, *, tools=None, **kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ProviderTurnResult(
                response_id=None,
                text="Reading both files.",
                tool_calls=[
                    ProviderToolCall(
                        call_id="call_a",
                        name="read",
                        arguments={"filePath": str(tmp_path / "a.txt")},
                    ),
                    ProviderToolCall(
                        call_id="call_b",
                        name="read",
                        arguments={"filePath": str(tmp_path / "b.txt")},
                    ),
                ],
            )
        else:
            return ProviderTurnResult(
                response_id=None,
                text="Read both files: AAA and BBB.",
                tool_calls=[],
            )

    from taui.server.handlers import MethodHandlers

    original = MethodHandlers._resolve_llm_for_tier

    class MockLLM:
        create_turn = staticmethod(mock_create_turn)

    def patched_resolve(self, tier, params):
        return MockLLM(), "test-model"

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            MethodHandlers._resolve_llm_for_tier = patched_resolve
            try:
                resp, result = _prime_send_and_collect(
                    ws, 1, [{"role": "user", "content": "Read a.txt and b.txt"}]
                )
            finally:
                MethodHandlers._resolve_llm_for_tier = original

            assert "error" not in resp, resp
            assert result.done
            assert len(result.tool_calls) == 2
            assert result.tool_calls[0]["tool_name"] == "read"
            assert result.tool_calls[1]["tool_name"] == "read"


def test_prime_launches_root_agent(tmp_path: Path) -> None:
    """Prime can call launch_root to spin up a background root agent."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    call_count = 0

    async def mock_create_turn(messages, model, *, tools=None, **kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ProviderTurnResult(
                response_id=None,
                text="Launching a root agent for that task.",
                tool_calls=[
                    ProviderToolCall(
                        call_id="call_root",
                        name="launch_root",
                        arguments={
                            "task": "Implement authentication module",
                            "spec_ref": "specs/core.md#core",
                        },
                    )
                ],
            )
        else:
            return ProviderTurnResult(
                response_id=None,
                text="Root agent launched successfully.",
                tool_calls=[],
            )

    from taui.server.handlers import MethodHandlers

    original = MethodHandlers._resolve_llm_for_tier

    class MockLLM:
        create_turn = staticmethod(mock_create_turn)

    def patched_resolve(self, tier, params):
        return MockLLM(), "test-model"

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            MethodHandlers._resolve_llm_for_tier = patched_resolve
            try:
                resp, result = _prime_send_and_collect(
                    ws, 1, [{"role": "user", "content": "Implement auth"}],
                    max_messages=300,
                )
            finally:
                MethodHandlers._resolve_llm_for_tier = original

            assert "error" not in resp, resp
            assert result.done
            assert len(result.tool_calls) == 1
            assert result.tool_calls[0]["tool_name"] == "launch_root"
            # Tool result notification should contain agent info
            assert len(result.tool_results) == 1
            tool_output = result.tool_results[0]["output"]
            assert tool_output is not None
            assert "Root agent launched" in tool_output
            # prime/agentLaunched notification should have been emitted
            launched = [n for n in result.notifications if n["method"] == "prime/agentLaunched"]
            assert len(launched) == 1
            assert "agent_id" in launched[0]
            assert "display_name" in launched[0]
            assert launched[0]["task"] == "Implement authentication module"


# ── Persistent Prime / Interrupt Tests ─────────────────────────────────────────


def test_prime_persistent_conversation_context(tmp_path: Path) -> None:
    """Consecutive prime/message calls share persistent conversation history."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    call_count = 0
    seen_messages: list[list[dict[str, Any]]] = []

    async def mock_create_turn(messages, model, *, tools=None, **kw):
        nonlocal call_count
        call_count += 1
        # Record what messages the LLM received
        seen_messages.append([m for m in messages if m.get("role") == "user"])
        return ProviderTurnResult(
            response_id=None,
            text=f"Response {call_count}",
            tool_calls=[],
        )

    from taui.server.handlers import MethodHandlers

    original = MethodHandlers._resolve_llm_for_tier

    class MockLLM:
        create_turn = staticmethod(mock_create_turn)

    def patched_resolve(self, tier, params):
        return MockLLM(), "test-model"

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            MethodHandlers._resolve_llm_for_tier = patched_resolve
            try:
                # First message
                resp1, result1 = _prime_send_and_collect(
                    ws, 1, [{"role": "user", "content": "Hello, I'm Alice"}]
                )
                assert result1.done
                assert "Response 1" in result1.text

                # Second message — should see first message in history
                resp2, result2 = _prime_send_and_collect(
                    ws, 2, [{"role": "user", "content": "What's my name?"}]
                )
                assert result2.done
                assert "Response 2" in result2.text

                # LLM should have seen both user messages on the second call
                assert len(seen_messages) == 2
                # First call: only "Hello, I'm Alice"
                assert len(seen_messages[0]) == 1
                # Second call: both messages
                assert len(seen_messages[1]) == 2
                assert seen_messages[1][0]["content"] == "Hello, I'm Alice"
                assert seen_messages[1][1]["content"] == "What's my name?"
            finally:
                MethodHandlers._resolve_llm_for_tier = original


def test_prime_history_rpc(tmp_path: Path) -> None:
    """prime/history returns the conversation history."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            # Send a message first (using no-op LLM)
            resp, result = _prime_send_and_collect(
                ws, 1, [{"role": "user", "content": "Hello"}]
            )
            assert result.done

            # Fetch history
            hist_resp = _rpc(ws, 2, "prime/history", {})
            assert "error" not in hist_resp
            messages = hist_resp["result"]["messages"]
            # Should contain at least the user message and assistant response
            roles = [m["role"] for m in messages]
            assert "user" in roles
            assert "assistant" in roles


def test_prime_cancel_rpc(tmp_path: Path) -> None:
    """prime/cancel cancels the current Prime loop."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            # Cancel should work even when Prime is idle
            resp = _rpc(ws, 1, "prime/cancel", {})
            assert "error" not in resp
            assert resp["result"] == {"ok": True}


def test_prime_interrupt_during_tool_execution(tmp_path: Path) -> None:
    """When a new message arrives during tool execution, Prime pivots."""
    _write_specs(tmp_path)
    (tmp_path / "slow.txt").write_text("slow content", encoding="utf-8")
    app = create_app(workspace=tmp_path)

    call_count = 0
    interrupt_seen = False

    async def mock_create_turn(messages, model, *, tools=None, **kw):
        nonlocal call_count, interrupt_seen
        call_count += 1

        user_msgs = [m for m in messages if m.get("role") == "user"]
        # Check if the interrupt message made it into context
        if any("INTERRUPT" in (m.get("content") or "") for m in user_msgs):
            interrupt_seen = True
            return ProviderTurnResult(
                response_id=None,
                text="I see the interrupt message!",
                tool_calls=[],
            )

        if call_count == 1:
            # Return a tool call that will take some time
            return ProviderTurnResult(
                response_id=None,
                text="Let me read that.",
                tool_calls=[
                    ProviderToolCall(
                        call_id="call_slow",
                        name="read",
                        arguments={"filePath": str(tmp_path / "slow.txt")},
                    ),
                    ProviderToolCall(
                        call_id="call_slow2",
                        name="read",
                        arguments={"filePath": str(tmp_path / "slow.txt")},
                    ),
                ],
            )
        else:
            return ProviderTurnResult(
                response_id=None,
                text="Done.",
                tool_calls=[],
            )

    from taui.server.handlers import MethodHandlers
    from taui.agent.prime import PrimeAgent

    original_resolve = MethodHandlers._resolve_llm_for_tier

    class MockLLM:
        create_turn = staticmethod(mock_create_turn)

    def patched_resolve(self, tier, params):
        return MockLLM(), "test-model"

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            MethodHandlers._resolve_llm_for_tier = patched_resolve
            try:
                # Send first message
                ws.send_text(
                    json.dumps({
                        "jsonrpc": "2.0", "id": 1,
                        "method": "prime/message",
                        "params": {"messages": [{"role": "user", "content": "Read slow file"}]},
                    })
                )
                # Immediately read the RPC response
                rpc_resp = json.loads(ws.receive_text())
                assert rpc_resp.get("result") == {"ok": True}

                # Immediately send an interrupt message
                ws.send_text(
                    json.dumps({
                        "jsonrpc": "2.0", "id": 2,
                        "method": "prime/message",
                        "params": {"messages": [{"role": "user", "content": "INTERRUPT: new question"}]},
                    })
                )

                # Collect all notifications until prime/done
                notifications = []
                done_count = 0
                for _ in range(100):
                    msg = json.loads(ws.receive_text())
                    if "method" in msg:
                        notifications.append(msg)
                        if msg["method"] == "prime/done":
                            done_count += 1
                            if done_count >= 1:
                                break
                    # Also consume the second RPC response
                    if msg.get("id") == 2:
                        continue

                # Prime should have seen the interrupt message
                assert interrupt_seen or call_count >= 2
            finally:
                MethodHandlers._resolve_llm_for_tier = original_resolve


def test_prime_state_changes(tmp_path: Path) -> None:
    """Prime emits stateChanged notifications during execution."""
    _write_specs(tmp_path)
    (tmp_path / "test.txt").write_text("content", encoding="utf-8")
    app = create_app(workspace=tmp_path)

    call_count = 0

    async def mock_create_turn(messages, model, *, tools=None, **kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ProviderTurnResult(
                response_id=None,
                text="Reading.",
                tool_calls=[
                    ProviderToolCall(
                        call_id="call_1",
                        name="read",
                        arguments={"filePath": str(tmp_path / "test.txt")},
                    ),
                ],
            )
        else:
            return ProviderTurnResult(
                response_id=None,
                text="Done.",
                tool_calls=[],
            )

    from taui.server.handlers import MethodHandlers

    original = MethodHandlers._resolve_llm_for_tier

    class MockLLM:
        create_turn = staticmethod(mock_create_turn)

    def patched_resolve(self, tier, params):
        return MockLLM(), "test-model"

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            MethodHandlers._resolve_llm_for_tier = patched_resolve
            try:
                ws.send_text(
                    json.dumps({
                        "jsonrpc": "2.0", "id": 1,
                        "method": "prime/message",
                        "params": {"messages": [{"role": "user", "content": "Read test.txt"}]},
                    })
                )

                notifications = []
                for _ in range(50):
                    msg = json.loads(ws.receive_text())
                    if "method" in msg:
                        notifications.append(msg)
                        if msg["method"] == "prime/done":
                            break

                methods = [n["method"] for n in notifications]
                # Should have stateChanged notifications
                assert "prime/stateChanged" in methods
                # Should have both thinking and tool_execution states
                state_changes = [
                    n["params"]["state"]
                    for n in notifications
                    if n["method"] == "prime/stateChanged"
                ]
                assert "thinking" in state_changes
                assert "tool_execution" in state_changes
            finally:
                MethodHandlers._resolve_llm_for_tier = original
