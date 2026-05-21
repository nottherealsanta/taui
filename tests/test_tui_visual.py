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
import subprocess

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


def _init_git_repo(path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tester"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    (path / "hello.py").write_text("print('hello')\n")
    subprocess.run(["git", "add", "hello.py"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=path,
        check=True,
        capture_output=True,
    )


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
        # Replace the runtime session list with a deterministic fixture so the
        # snapshot does not change every run (real session IDs are uuid-random
        # and last_active is wall-clock time).
        async def _stub_list():
            return [
                {
                    "session_id": "sess-aaaa",
                    "description": "first session",
                    "message_count": 12,
                    "last_active": 0.0,
                    "created_at": 0.0,
                    "mode": "normal",
                },
                {
                    "session_id": "sess-bbbb",
                    "description": "older work",
                    "message_count": 3,
                    "last_active": 0.0,
                    "created_at": 0.0,
                    "mode": "normal",
                },
            ]

        if app._session is not None:
            app._session.list_sessions = _stub_list  # type: ignore[assignment]
            app._session.session_id = "sess-aaaa"
        await pilot.press("ctrl+b")
        await pilot.pause()
        # Workers run asynchronously; pause again so refresh has settled.
        for _ in range(3):
            await pilot.pause()
        await _close_cleanly(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(100, 30))


def test_command_palette_model_search_visible(snap_compare, tmp_path, monkeypatch):
    """Ctrl+P opens Taui's command palette with model actions."""
    monkeypatch.setattr(
        "taui.llm_provider.models.list_models",
        lambda provider, **kwargs: [
            {"id": "claude-haiku-4.5", "context": 200000, "reasoning": False},
            {"id": "gpt-5.5", "context": 400000, "reasoning": True},
        ],
    )
    provider = scenarios.happy_path("(unused)")
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        await _wait_until_ready(pilot)
        await pilot.press("ctrl+p")
        await pilot.press("m", "o", "d", "e", "l")
        for _ in range(4):
            await pilot.pause()
        await _close_cleanly(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(100, 30))


def test_diff_command_modal_visible(snap_compare, tmp_path, monkeypatch):
    """The /diff command should open the git diff modal."""
    _init_git_repo(tmp_path)
    (tmp_path / "hello.py").write_text("print('hello')\nprint('taui')\n")
    provider = scenarios.happy_path("(unused)")
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        await _wait_until_ready(pilot)
        await _type_and_send(pilot, "/diff")
        for _ in range(3):
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


def test_approval_prompt_visible(snap_compare, tmp_path, monkeypatch):
    """A bash tool call should pause at the approval prompt; capture that state."""
    from taui.tui.widgets.info2 import Info2, Info2Mode

    provider = ScriptedProvider(
        [
            Turn(
                tool_calls=[ScriptedToolCall(name="bash", arguments={"command": "echo hi"})],
                stop_reason="tool_use",
            ),
            Turn(text="done"),
        ]
    )
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        from taui.tui.widgets.spinner import ActivityProgress

        await _wait_until_ready(pilot)
        await _type_and_send(pilot, "run a bash command")
        info2 = pilot.app.query_one("#info2", Info2)
        deadline = asyncio.get_event_loop().time() + 3.0
        while asyncio.get_event_loop().time() < deadline:
            if info2.mode == Info2Mode.APPROVAL:
                break
            await pilot.pause()
        # Freeze the breathing-progress timer so the snapshot is byte-stable
        # across runs — the bar's animated offset is wall-clock-dependent.
        for progress in pilot.app.query(ActivityProgress):
            progress.stop()
        # Leave Info2 in APPROVAL mode for the snapshot, then close the session
        # so pytest exits cleanly (the pending future is cancelled by close).
        try:
            await pilot.app._session.close()
        except Exception:
            pass
        pilot.app._session = None

    assert snap_compare(app, run_before=setup, terminal_size=(100, 30))


def test_error_rendered_on_provider_failure(snap_compare, tmp_path, monkeypatch):
    """When the provider raises (e.g., auth expired), the chat should show the error."""
    provider = scenarios.auth_expired()
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        await _wait_until_ready(pilot)
        await _type_and_send(pilot, "hi")
        await _wait_idle(pilot)
        await _close_cleanly(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(100, 30))


def test_help_command_help_visible(snap_compare, tmp_path, monkeypatch):
    """Typing `/` should reveal the slash-command completion dropdown."""
    provider = scenarios.happy_path("(unused)")
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        from taui.tui.widgets.chat_input import ChatInput

        await _wait_until_ready(pilot)
        chat_input = pilot.app.query_one("#chat-input", ChatInput)
        chat_input.text = "/"
        chat_input.focus()
        # Nudge the dropdown via the same text-changed path the user would trigger.
        chat_input.on_text_area_changed(object())
        await pilot.pause()
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


def test_three_turns_oldest_collapsed(snap_compare, tmp_path, monkeypatch):
    """With three sequential exchanges, the oldest should auto-collapse."""
    provider = ScriptedProvider(
        [
            Turn(text="First reply.", text_deltas=["First reply."]),
            Turn(text="Second reply.", text_deltas=["Second reply."]),
            Turn(text="Third reply.", text_deltas=["Third reply."]),
        ]
    )
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        await _wait_until_ready(pilot)
        await _type_and_send(pilot, "first message")
        await _wait_idle(pilot)
        await _type_and_send(pilot, "second message")
        await _wait_idle(pilot)
        await _type_and_send(pilot, "third message")
        await _wait_idle(pilot)
        await _close_cleanly(pilot)

    # Larger terminal so all three turn headers fit on screen and we can
    # actually verify the collapsed/expanded state visually.
    assert snap_compare(app, run_before=setup, terminal_size=(140, 50))


# ── Session resume ──────────────────────────────────────────────────────


def test_resumed_session_uses_turn_widgets(snap_compare, tmp_path, monkeypatch):
    """After a session is resumed, the chat log should render with the
    new TurnContainer widget — old turns collapse with a gray summary."""
    from taui.session_replay import ReplayItem

    provider = scenarios.happy_path("(unused)")
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    fake_items = [
        ReplayItem(kind="user", text="first message"),
        ReplayItem(kind="assistant", text="First reply.", agent_id="DEF", model="m"),
        ReplayItem(kind="usage", input_tokens=20, output_tokens=10),
        ReplayItem(kind="user", text="second message"),
        ReplayItem(
            kind="tool_call",
            name="read",
            call_id="t1",
            arguments={"path": "x.py"},
            agent_id="DEF",
            model="m",
        ),
        ReplayItem(kind="tool_result", call_id="t1", text="ok", name="read"),
        ReplayItem(kind="assistant", text="Second reply.", agent_id="DEF", model="m"),
        ReplayItem(kind="usage", input_tokens=40, output_tokens=15),
        ReplayItem(kind="user", text="third message"),
        ReplayItem(kind="assistant", text="Third reply.", agent_id="DEF", model="m"),
        ReplayItem(kind="usage", input_tokens=80, output_tokens=20),
    ]

    async def setup(pilot: Pilot) -> None:
        await _wait_until_ready(pilot)
        # Inject fake replay items at the instance level (avoid mutating the class).
        pilot.app._session._last_replay_items = fake_items
        await pilot.app._render_replay()
        for _ in range(8):
            await pilot.pause()
        await _close_cleanly(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(140, 50))


def test_resumed_session_real_store(snap_compare, tmp_path, monkeypatch):
    """End-to-end: write events (incl. USAGE) to a real store, then resume.

    This exercises the full pipeline: `replay_events` over real persisted
    events → `Session.replay_items` → `_render_replay` → TurnContainer with
    summary populated from the actual store.
    """
    import asyncio

    from taui.store import Store
    from taui.store.events import EventType
    from taui.store.stream import StreamClient

    stream_id = "stream-resume-test"
    session_id = "sess-resume-test"

    async def _seed_store() -> None:
        store = Store(tmp_path)
        await store.connect()
        try:
            stream = StreamClient(store)
            await stream.ensure_stream(stream_id)
            await store.create_session(session_id, stream_id=stream_id)
            # Turn 1
            await store.append(stream_id, EventType.STREAM_START, {"agent_id": "DEF", "model": "m"})
            await store.append(stream_id, EventType.USER_MESSAGE, {"text": "first message"})
            await store.append(
                stream_id, EventType.ASSISTANT_MESSAGE, {"text": "First reply.", "agent_id": "DEF", "model": "m"},
            )
            await store.append(
                stream_id, EventType.USAGE, {"input_tokens": 20, "output_tokens": 10},
            )
            # Turn 2
            await store.append(stream_id, EventType.USER_MESSAGE, {"text": "second message"})
            await store.append(
                stream_id, EventType.ASSISTANT_MESSAGE, {"text": "Second reply.", "agent_id": "DEF", "model": "m"},
            )
            await store.append(
                stream_id, EventType.USAGE, {"input_tokens": 40, "output_tokens": 15},
            )
            # Turn 3
            await store.append(stream_id, EventType.USER_MESSAGE, {"text": "third message"})
            await store.append(
                stream_id, EventType.ASSISTANT_MESSAGE, {"text": "Third reply.", "agent_id": "DEF", "model": "m"},
            )
            await store.append(
                stream_id, EventType.USAGE, {"input_tokens": 80, "output_tokens": 20},
            )
        finally:
            await store.close()

    asyncio.run(_seed_store())

    provider = scenarios.happy_path("(unused)")
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        await _wait_until_ready(pilot)
        ok = await pilot.app._resume_session(session_id)
        assert ok, f"resume failed: {getattr(pilot.app._session, 'last_resume_error', '')}"
        for _ in range(8):
            await pilot.pause()
        await _close_cleanly(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(140, 50))


# ── Parallel sessions ──────────────────────────────────────────────────


def test_parallel_sessions_two_tabs(snap_compare, tmp_path, monkeypatch):
    """Two session tabs visible — first has a reply, second is new."""
    provider = ScriptedProvider(
        [
            Turn(text="Reply in tab one.", text_deltas=["Reply in tab one."]),
            Turn(text="Reply in tab two.", text_deltas=["Reply in tab two."]),
        ]
    )
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        await _wait_until_ready(pilot)
        # Send a message in the first session
        await _type_and_send(pilot, "hello from tab one")
        await _wait_idle(pilot)
        # Open a second session tab
        await pilot.app.action_new_chat()
        await _wait_until_ready(pilot)
        # Send a message in the second tab
        await _type_and_send(pilot, "hello from tab two")
        await _wait_idle(pilot)
        # Close all sessions cleanly
        for state in list(pilot.app._sessions._states.values()):
            try:
                await state.session.close()
            except Exception:
                pass
        pilot.app._session = None

    assert snap_compare(app, run_before=setup, terminal_size=(100, 30))


def test_attachment_pills_with_paste_and_image(snap_compare, tmp_path, monkeypatch):
    """Visual snapshot: attachments bar with a paste pill + an image pill.

    The chat input also holds the matching ``[1]`` and ``[2]`` markers — the
    snapshot captures both the pill styling (label + orange number) and the
    in-buffer orange tokens.
    """
    from textual.events import Paste

    from taui.tui.widgets.chat_input import ChatInput

    provider = scenarios.happy_path("(unused)")
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        await _wait_until_ready(pilot)
        chat_input = pilot.app.query_one("#chat-input", ChatInput)
        chat_input.focus()
        await pilot.pause()
        # Multi-line paste → pill
        chat_input.post_message(Paste("\n".join(f"line {i}" for i in range(10))))
        await pilot.pause()
        # Pre-stage a clipboard image attachment so the bar shows two pills.
        chat_input._pending_images.append("data:image/png;base64,iVBORw0K")
        chat_input.post_message(
            ChatInput.ImageAttached(1, "data:image/png;base64,iVBORw0K")
        )
        await pilot.pause()
        await pilot.pause()
        # Type some plain text between the markers so the [1] / [2] tokens
        # appear with surrounding context.
        chat_input.insert(" look at ", location=(0, 3))
        await pilot.pause()
        await _close_cleanly(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(100, 30))


def test_self_edit_general_tab(snap_compare, tmp_path, monkeypatch):
    provider = scenarios.happy_path("(unused)")
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        await _wait_until_ready(pilot)
        # Open self-edit modal
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.pause()
        # Navigate to General tab (last category) — press left to wrap
        await pilot.press("left")
        await pilot.pause()
        await pilot.pause()
        await _close_cleanly(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(100, 30))
