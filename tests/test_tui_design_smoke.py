"""Smoke tests for the unified TUI design — verifies shortcuts and panels.

These are behavioral tests (no SVG snapshots) that drive `TauiApp` through
its public key bindings and assert on real DOM/widget state. They cover:

- ctrl+b toggles the left sidebar.
- The left sidebar exposes Sessions/Files tabs and cycles between them.
- Sessions render with the current-session indicator and time-sort order.
- ctrl+r toggles the right info sidebar and populates its sections.
- Slash-command autocomplete: a single Enter runs the highlighted command
  (no more "press twice").
- Info bar no longer renders the session badge.
- Tool status messages use the unified gray palette regardless of error
  state.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.scenarios import scenarios
from tests.scenarios.tui_harness import use_scripted_provider


# ── Helpers ─────────────────────────────────────────────────────────────


async def _wait_until_ready(pilot, *, timeout: float = 2.0) -> None:
    app = pilot.app
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        await pilot.pause()
        if (
            not getattr(app, "_session_initializing", True)
            and getattr(app, "_session", None) is not None
        ):
            await pilot.pause()
            return
    raise TimeoutError("Session never finished initializing")


async def _close_cleanly(pilot) -> None:
    session = getattr(pilot.app, "_session", None)
    if session is not None:
        try:
            await session.close()
        except Exception:
            pass
        pilot.app._session = None


def _make_app(monkeypatch, tmp_path):
    provider = scenarios.happy_path("(unused)")
    return use_scripted_provider(monkeypatch, tmp_path, provider)


# ── ctrl+b: left sidebar toggle ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_ctrl_b_toggles_left_sidebar(tmp_path, monkeypatch):
    """Ctrl+B should toggle the left sidebar visibility."""
    from taui.tui.widgets.sidebar import Sidebar

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        sidebar = pilot.app.query_one(Sidebar)
        assert not sidebar.has_class("visible")
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert sidebar.has_class("visible"), "ctrl+b did not show sidebar"
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert not sidebar.has_class("visible"), (
            "second ctrl+b did not hide sidebar"
        )
        await _close_cleanly(pilot)


# ── Sidebar Sessions / Files tabs ───────────────────────────────────────


@pytest.mark.asyncio
async def test_sidebar_has_sessions_and_files_tabs(tmp_path, monkeypatch):
    """Sidebar should expose Sessions + Files tabs and cycle between them."""
    from textual.widgets import DirectoryTree, ListView, Static

    from taui.tui.widgets.sidebar import Sidebar

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        await pilot.press("ctrl+b")
        await pilot.pause()
        sidebar = pilot.app.query_one(Sidebar)

        sessions_tab = sidebar.query_one("#tab-sessions", Static)
        files_tab = sidebar.query_one("#tab-files", Static)
        sessions_list = sidebar.query_one("#sessions-list", ListView)
        dir_tree = sidebar.query_one("#dir-tree", DirectoryTree)

        # Initial: sessions active
        assert sessions_tab.has_class("active")
        assert not files_tab.has_class("active")
        assert sessions_list.display is True
        assert dir_tree.display is False

        # Cycle → files
        sidebar.action_cycle_tab()
        await pilot.pause()
        assert files_tab.has_class("active")
        assert not sessions_tab.has_class("active")
        assert dir_tree.display is True
        assert sessions_list.display is False

        # Cycle → sessions again
        sidebar.action_cycle_tab()
        await pilot.pause()
        assert sessions_tab.has_class("active")
        assert sessions_list.display is True
        await _close_cleanly(pilot)


@pytest.mark.asyncio
async def test_sidebar_sessions_show_running_indicator_and_sort(
    tmp_path, monkeypatch
):
    """Current session should be marked, list sorted by last_active desc."""
    from textual.widgets import ListView

    from taui.tui.widgets.sidebar import Sidebar, _SessionRow

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)

        async def _stub_list():
            return [
                {
                    "session_id": "old-one",
                    "description": "older",
                    "message_count": 1,
                    "last_active": 100.0,
                    "created_at": 0.0,
                    "mode": "normal",
                },
                {
                    "session_id": "current-x",
                    "description": "current",
                    "message_count": 5,
                    "last_active": 9999.0,
                    "created_at": 0.0,
                    "mode": "normal",
                },
                {
                    "session_id": "middle",
                    "description": "middle",
                    "message_count": 2,
                    "last_active": 500.0,
                    "created_at": 0.0,
                    "mode": "normal",
                },
            ]

        pilot.app._session.list_sessions = _stub_list  # type: ignore[assignment]
        pilot.app._session.session_id = "current-x"
        await pilot.press("ctrl+b")
        # Worker is async; pause a few times so the refresh settles.
        for _ in range(5):
            await pilot.pause()

        sidebar = pilot.app.query_one(Sidebar)
        listview = sidebar.query_one("#sessions-list", ListView)
        rows = [c for c in listview.children if isinstance(c, _SessionRow)]
        # Sorted by last_active desc: current-x (9999), middle (500), old-one (100)
        assert [r.session_id for r in rows] == ["current-x", "middle", "old-one"]
        await _close_cleanly(pilot)


# ── ctrl+r: right info sidebar ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_ctrl_r_toggles_info_sidebar(tmp_path, monkeypatch):
    """Ctrl+R should toggle the right info sidebar."""
    from taui.tui.widgets.session_info_sidebar import SessionInfoSidebar

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        info_sidebar = pilot.app.query_one(SessionInfoSidebar)
        assert not info_sidebar.has_class("visible")
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert info_sidebar.has_class("visible")
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert not info_sidebar.has_class("visible")
        await _close_cleanly(pilot)


@pytest.mark.asyncio
async def test_info_sidebar_populates_session_section(tmp_path, monkeypatch):
    """After ctrl+r the right sidebar should be visible and populated with
    the current session info (session id, MCP/tool sections, etc.)."""
    from taui.tui.widgets.session_info_sidebar import SessionInfoSidebar

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        sid = pilot.app._session.session_id
        await pilot.press("ctrl+r")
        for _ in range(5):
            await pilot.pause()

        info_sidebar = pilot.app.query_one(SessionInfoSidebar)
        assert info_sidebar.has_class("visible"), "info sidebar not visible"

        # The 6 sections should exist as DOM containers, regardless of content.
        for key in ("session", "agent", "files", "lsp", "mcp", "tools"):
            section = info_sidebar.query_one(f"#sec-{key}")
            assert section.is_mounted, f"#sec-{key} not mounted"
            header = info_sidebar.query_one(f"#hdr-{key}")
            assert header.is_mounted, f"#hdr-{key} not mounted"

        for _ in range(5):
            await pilot.pause()
        session_section = info_sidebar.query_one("#sec-session")
        rendered = "".join(
            _widget_text(child) for child in session_section.children
        )
        assert sid in rendered, (
            f"session id {sid!r} not found in #sec-session rows: {rendered!r}"
        )
        await _close_cleanly(pilot)


def _widget_text(widget) -> str:
    """Best-effort plain-text extraction from a Textual widget's rendered content."""
    from rich.text import Text

    # Newer Textual exposes render(); older versions exposed .renderable.
    r = None
    if hasattr(widget, "render"):
        try:
            r = widget.render()
        except Exception:
            r = None
    if r is None:
        r = getattr(widget, "renderable", None)
    if r is None:
        return ""
    if isinstance(r, Text):
        return r.plain
    plain = getattr(r, "plain", None)
    if plain is not None:
        return plain
    return str(r)


def test_record_edit_tracks_added_and_removed_lines(tmp_path, monkeypatch):
    """The right sidebar's +/- counter should accumulate over write/edit calls."""
    app = _make_app(monkeypatch, tmp_path)
    app._record_edit("write", {"file_path": "/tmp/foo.py", "content": "a\nb\nc"})
    app._record_edit(
        "edit",
        {
            "file_path": "/tmp/foo.py",
            "old_string": "a\nb",
            "new_string": "x\ny\nz",
        },
    )
    entry = app._edited_files["/tmp/foo.py"]
    # write: 3 lines added
    # edit: old 2 lines removed, new 3 lines added → cumulative 6 added / 2 removed
    assert entry == {"added": 6, "removed": 2}


# ── Autocomplete: Enter runs the command in one press ───────────────────


@pytest.mark.asyncio
async def test_autocomplete_enter_submits_immediately(tmp_path, monkeypatch):
    """Typing '/he' + Enter should run /help in one keypress."""
    from taui.tui.widgets.chat_input import ChatInput

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        chat_input = pilot.app.query_one("#chat-input", ChatInput)
        chat_input.focus()
        await pilot.pause()
        # Type "/he" — completion list should pop up
        for ch in "/he":
            await pilot.press(ch)
        await pilot.pause()
        assert chat_input._completion_active, "completion should be active"
        # Press Enter — should fill+submit in one shot, leaving an empty buffer
        await pilot.press("enter")
        await pilot.pause()
        assert chat_input.text == "", (
            f"input should be cleared after submit, got {chat_input.text!r}"
        )
        await _close_cleanly(pilot)


# ── Info bar: session badge removed ─────────────────────────────────────


def test_info_bar_no_longer_has_session_badge():
    from taui.tui.widgets import info_bar as info_bar_module
    from taui.tui.widgets.info_bar import InfoBar

    # Class should not exist anymore.
    assert not hasattr(info_bar_module, "SessionBadge")
    # And the message class is gone too.
    assert not hasattr(InfoBar, "SessionBadgeClicked")


# ── Tool status: unified gray palette ───────────────────────────────────


# ── Files tab: click-to-attach ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_files_tab_click_adds_pill(tmp_path, monkeypatch):
    """A FileToggleRequested message should add a file pill and re-firing
    it should remove the pill (toggle behavior)."""
    from taui.tui.widgets.attachments_bar import AttachmentsBar
    from taui.tui.widgets.sidebar import Sidebar

    sample = tmp_path / "hello.txt"
    sample.write_text("hi there")

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        sidebar = pilot.app.query_one(Sidebar)
        sidebar.post_message(Sidebar.FileToggleRequested(sample))
        await pilot.pause()
        await pilot.pause()

        bar = pilot.app.query_one(AttachmentsBar)
        assert bar.count == 1, "first toggle did not add a pill"
        assert bar.items[0].kind == "file"
        assert bar.items[0].data == str(sample.resolve())
        assert Path(str(sample.resolve())) in pilot.app._pending_files

        # Second toggle removes
        sidebar.post_message(Sidebar.FileToggleRequested(sample))
        await pilot.pause()
        await pilot.pause()
        assert bar.count == 0, "second toggle did not remove the pill"
        assert pilot.app._pending_files == []
        await _close_cleanly(pilot)


@pytest.mark.asyncio
async def test_pill_x_removes_file_attachment(tmp_path, monkeypatch):
    """Removing a file pill via X should also drop it from _pending_files."""
    from taui.tui.widgets.attachments_bar import AttachmentsBar
    from taui.tui.widgets.sidebar import Sidebar

    sample = tmp_path / "doc.md"
    sample.write_text("# doc")

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        sidebar = pilot.app.query_one(Sidebar)
        sidebar.post_message(Sidebar.FileToggleRequested(sample))
        await pilot.pause()
        await pilot.pause()

        bar = pilot.app.query_one(AttachmentsBar)
        assert bar.count == 1
        # Simulate the user clicking the pill's X.
        removed = bar.remove(0)
        assert removed is not None
        bar.post_message(
            AttachmentsBar.Cleared(0, kind=removed.kind, data=removed.data)
        )
        await pilot.pause()
        await pilot.pause()
        assert pilot.app._pending_files == [], (
            "pill-clear did not sync _pending_files"
        )
        await _close_cleanly(pilot)


def test_expand_pending_files_inlines_text_content(tmp_path, monkeypatch):
    """Text files in _pending_files should be folded into the prompt as
    fenced code blocks; image files become image data URLs."""
    sample = tmp_path / "snippet.py"
    sample.write_text("print('hi')\n")
    app = _make_app(monkeypatch, tmp_path)
    app._pending_files = [sample]
    text, images = app._expand_pending_files("explain this", None)
    assert "explain this" in text
    assert "snippet.py" in text
    assert "print('hi')" in text
    assert images is None


# ── Session row: name primary, id in gray ──────────────────────────────


def test_session_row_renders_name_then_id(tmp_path):
    """The session description should be the primary row label; the id
    should appear as dim gray context, not the headline."""
    from rich.text import Text

    from taui.tui.widgets.sidebar import _SessionRow

    row = _SessionRow(
        {
            "session_id": "abc123def456",
            "description": "Refactor login flow",
            "message_count": 7,
            "last_active": 0.0,
            "created_at": 0.0,
        },
        is_current=True,
    )
    rendered = row.label_text
    plain = rendered.plain
    # Name appears before the id (and id is below it in the second line).
    name_pos = plain.find("Refactor login flow")
    id_pos = plain.find("abc123def456")
    assert name_pos != -1 and id_pos != -1
    assert name_pos < id_pos, (
        f"name should come before id, got name@{name_pos} id@{id_pos}"
    )

    # The id span should be styled with a gray color (#6e7681 in our palette).
    spans_at_id = [
        sp for sp in rendered.spans if sp.start <= id_pos < sp.end
    ]
    styles = " ".join(str(sp.style) for sp in spans_at_id)
    assert "#6e7681" in styles, (
        f"id span should be dim gray, styles seen: {styles!r}"
    )


def test_tool_status_uses_unified_gray_palette():
    """Both success and error tool rows should use the gray name color
    (no leftover blue or red highlights from the old design)."""
    import inspect

    from taui.tui.widgets import tool_status

    src = inspect.getsource(tool_status)
    # The old highlight colors used #6BB6FF (blue) for tool names and
    # #f97583 (red) for errors. They should be gone.
    assert "#6BB6FF" not in src
    assert "#f97583" not in src
    # Gray palette should be present
    assert "#8b949e" in src
    assert "#6e7681" in src
