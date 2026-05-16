"""Visual snapshot tests for the Textual TUI.

These tests render `TauiApp` at representative moments and store the SVG under
``tests/__snapshots__/``. A coding agent (or human) updating the TUI can:

1. Run ``uv run python -m pytest tests/test_tui_visual.py``.
2. Inspect the diff in the snapshot report (pytest-textual-snapshot writes an
   HTML report on failure).
3. If the change is intentional, re-run with ``--snapshot-update`` to refresh
   the baseline.

The harness drives `TauiApp` with a `ScriptedProvider` so behavior is
deterministic and free of network/auth dependencies.

Each test uses ``run_before`` to wait for the session to fully initialize
before the snapshot is taken; otherwise the bottom chat input is still
hidden behind the activity progress bar.
"""

from __future__ import annotations

import asyncio

import pytest
from textual.pilot import Pilot

from tests.scenarios import ScriptedProvider, ScriptedToolCall, Turn, scenarios
from tests.scenarios.tui_harness import use_scripted_provider


async def _wait_until_ready(pilot: Pilot, *, timeout: float = 2.0) -> None:
    """Wait for the session worker to finish initializing the app."""
    app = pilot.app
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        await pilot.pause()
        ready = (
            not getattr(app, "_session_initializing", True)
            and getattr(app, "_session", None) is not None
        )
        if ready:
            await pilot.pause()
            return
    raise TimeoutError("Session never finished initializing")


async def _type_and_send(pilot: Pilot, text: str) -> None:
    """Type into the chat input and press enter."""
    from taui.tui.widgets.chat_input import ChatInput

    chat_input = pilot.app.query_one("#chat-input", ChatInput)
    chat_input.text = text
    chat_input.focus()
    await pilot.press("enter")


async def _wait_idle(pilot: Pilot, *, timeout: float = 2.0) -> None:
    """Wait for the app to stop processing (agent reply complete)."""
    app = pilot.app
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        await pilot.pause()
        if not getattr(app, "_is_processing", False):
            await pilot.pause()
            return
    raise TimeoutError("App stayed busy past timeout")


async def _close_cleanly(pilot: Pilot) -> None:
    """Close the underlying Session so aiosqlite/workers exit before snapshot.

    Without this, the python process tends to linger after the asyncio loop
    closes because the Session's store/stream/agent-loop workers are not
    cancelled. The snapshot itself is captured AFTER run_before returns, so
    closing the session here is safe — the rendered DOM is already in place.
    """
    app = pilot.app
    session = getattr(app, "_session", None)
    if session is not None:
        try:
            await session.close()
        except Exception:
            pass
        app._session = None


# ── Snapshot scenarios ──────────────────────────────────────────────────


def test_idle_after_startup(snap_compare, tmp_path, monkeypatch):
    """App immediately after the session finishes initializing."""
    provider = scenarios.happy_path("(unused)")
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        await _wait_until_ready(pilot)
        await _close_cleanly(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(100, 30))


def test_after_streamed_reply(snap_compare, tmp_path, monkeypatch):
    """User sent a message and got a streamed reply."""
    provider = scenarios.streamed_reply("Hello from the scripted provider.", chunk_size=8)
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        await _wait_until_ready(pilot)
        await _type_and_send(pilot, "hi there")
        await _wait_idle(pilot)
        await _close_cleanly(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(100, 30))


def test_after_empty_response(snap_compare, tmp_path, monkeypatch):
    """Provider returned an empty string — UI should remain stable."""
    provider = scenarios.empty_response()
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        await _wait_until_ready(pilot)
        await _type_and_send(pilot, "say nothing")
        await _wait_idle(pilot)
        await _close_cleanly(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(100, 30))


_REASONING = lambda: scenarios.with_reasoning("Considering it...", "Result text.")  # noqa: E731
_FINAL_TEXT = lambda: scenarios.happy_path("Final answer.")  # noqa: E731


@pytest.mark.parametrize(
    "scenario_factory,prompt,name",
    [
        (_REASONING, "think", "reasoning"),
        (_FINAL_TEXT, "answer me", "final_text"),
    ],
    ids=["reasoning", "final_text"],
)
def test_response_variants(snap_compare, tmp_path, monkeypatch, scenario_factory, prompt, name):
    """One parametrized place to grow visual coverage of response shapes."""
    provider = scenario_factory()
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        await _wait_until_ready(pilot)
        await _type_and_send(pilot, prompt)
        await _wait_idle(pilot)
        await _close_cleanly(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(100, 30))


# ── Richer UI states ────────────────────────────────────────────────────


def test_input_drafted_not_sent(snap_compare, tmp_path, monkeypatch):
    """Text typed into the input but not submitted — verifies draft rendering."""
    provider = scenarios.happy_path("(unused)")
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        from taui.tui.widgets.chat_input import ChatInput

        await _wait_until_ready(pilot)
        chat_input = pilot.app.query_one("#chat-input", ChatInput)
        chat_input.text = "this is a drafted message"
        chat_input.focus()
        await pilot.pause()
        await _close_cleanly(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(100, 30))


def test_sidebar_visible(snap_compare, tmp_path, monkeypatch):
    """Ctrl+B should toggle the sidebar into view."""
    provider = scenarios.happy_path("(unused)")
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        await _wait_until_ready(pilot)
        await pilot.press("ctrl+b")
        await pilot.pause()
        await _close_cleanly(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(100, 30))


def test_multi_turn_conversation(snap_compare, tmp_path, monkeypatch):
    """Two user/assistant exchanges should both appear in the chat log."""
    provider = ScriptedProvider(
        [
            Turn(text="First reply.", text_deltas=["First reply."]),
            Turn(text="Second reply.", text_deltas=["Second reply."]),
        ]
    )
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        await _wait_until_ready(pilot)
        await _type_and_send(pilot, "first message")
        await _wait_idle(pilot)
        await _type_and_send(pilot, "second message")
        await _wait_idle(pilot)
        await _close_cleanly(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(100, 30))


def test_tool_call_visible(snap_compare, tmp_path, monkeypatch):
    """A scripted `read` tool call should show a tool-status widget in the chat log."""
    target = tmp_path / "note.txt"
    target.write_text("read me")
    provider = ScriptedProvider(
        [
            Turn(
                tool_calls=[ScriptedToolCall(name="read", arguments={"path": "note.txt"})],
                stop_reason="tool_use",
            ),
            Turn(text="Read it.", text_deltas=["Read it."]),
        ]
    )
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        await _wait_until_ready(pilot)
        await _type_and_send(pilot, "read note.txt")
        await _wait_idle(pilot, timeout=4.0)
        await _close_cleanly(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(100, 30))


def test_long_markdown_reply(snap_compare, tmp_path, monkeypatch):
    """Markdown reply with a code block and list — exercises richer rendering."""
    reply = (
        "Here's a summary:\n\n"
        "- alpha\n"
        "- beta\n\n"
        "```python\n"
        "def hello() -> str:\n"
        "    return 'world'\n"
        "```\n"
    )
    provider = scenarios.streamed_reply(reply, chunk_size=24)
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        await _wait_until_ready(pilot)
        await _type_and_send(pilot, "show markdown")
        await _wait_idle(pilot)
        await _close_cleanly(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(100, 30))
