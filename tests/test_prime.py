"""
Tests for Prime RPC handler (prime/message).

Verifies:
- Basic text response (no tool calls)
- Tool-call loop execution (read, write, etc.)
- AGENT-category tools are excluded
- Error / fallback handling
- Session tracks read state for write tool
"""

from __future__ import annotations

import json
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


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_prime_basic_text_response(tmp_path: Path) -> None:
    """With no-op LLM, Prime returns a simple text response with no tool_calls."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            resp = _rpc(
                ws,
                1,
                "prime/message",
                {"messages": [{"role": "user", "content": "Hello"}]},
            )
            assert "error" not in resp, resp
            result = resp["result"]
            assert result["role"] == "assistant"
            assert isinstance(result["content"], str)
            assert len(result["content"]) > 0
            # No-op LLM doesn't call tools
            assert result["tool_calls"] == []


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
            # Patch _resolve_llm_for_tier to return our mock
            from taui.server.handlers import MethodHandlers

            original = MethodHandlers._resolve_llm_for_tier

            class MockLLM:
                create_turn = staticmethod(mock_create_turn)

            def patched_resolve(self, tier, params):
                return MockLLM(), "test-model"

            MethodHandlers._resolve_llm_for_tier = patched_resolve
            try:
                resp = _rpc(
                    ws,
                    1,
                    "prime/message",
                    {"messages": [{"role": "user", "content": "Read hello.txt"}]},
                )
            finally:
                MethodHandlers._resolve_llm_for_tier = original

            assert "error" not in resp, resp
            result = resp["result"]
            assert result["role"] == "assistant"
            assert "Hello, world!" in result["content"]
            # Should have recorded the tool call
            assert len(result["tool_calls"]) == 1
            assert result["tool_calls"][0]["tool_name"] == "read"
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
                resp = _rpc(
                    ws,
                    1,
                    "prime/message",
                    {"messages": [{"role": "user", "content": "Read nonexistent.txt"}]},
                )
            finally:
                MethodHandlers._resolve_llm_for_tier = original

            assert "error" not in resp, resp
            assert resp["result"]["content"] == "File not found."


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

    original = MethodHandlers._resolve_llm_for_tier

    class MockLLM:
        create_turn = staticmethod(mock_create_turn)

    def patched_resolve(self, tier, params):
        return MockLLM(), "test-model"

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            MethodHandlers._resolve_llm_for_tier = patched_resolve
            try:
                resp = _rpc(
                    ws,
                    1,
                    "prime/message",
                    {
                        "messages": [{"role": "user", "content": "Loop forever"}],
                        "max_turns": 3,
                    },
                )
            finally:
                MethodHandlers._resolve_llm_for_tier = original

            assert "error" not in resp, resp
            # Should have exactly 3 tool calls (one per turn)
            assert len(resp["result"]["tool_calls"]) == 3


def test_prime_fallback_on_tool_api_error(tmp_path: Path) -> None:
    """If the first tool-augmented call fails, Prime falls back to plain chat."""
    _write_specs(tmp_path)
    app = create_app(workspace=tmp_path)

    call_count = 0

    async def mock_create_turn(messages, model, *, tools=None, **kw):
        nonlocal call_count
        call_count += 1
        if tools:
            raise Exception("API does not support tools")
        # Fallback without tools
        return ProviderTurnResult(
            response_id=None,
            text="Fallback response without tools.",
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
                resp = _rpc(
                    ws,
                    1,
                    "prime/message",
                    {"messages": [{"role": "user", "content": "Hello"}]},
                )
            finally:
                MethodHandlers._resolve_llm_for_tier = original

            assert "error" not in resp, resp
            assert resp["result"]["content"] == "Fallback response without tools."


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
                resp = _rpc(
                    ws,
                    1,
                    "prime/message",
                    {"messages": [{"role": "user", "content": "Write output.py"}]},
                )
            finally:
                MethodHandlers._resolve_llm_for_tier = original

            assert "error" not in resp, resp
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
                resp = _rpc(
                    ws,
                    1,
                    "prime/message",
                    {"messages": [{"role": "user", "content": "Read a.txt and b.txt"}]},
                )
            finally:
                MethodHandlers._resolve_llm_for_tier = original

            assert "error" not in resp, resp
            result = resp["result"]
            assert len(result["tool_calls"]) == 2
            assert result["tool_calls"][0]["tool_name"] == "read"
            assert result["tool_calls"][1]["tool_name"] == "read"
