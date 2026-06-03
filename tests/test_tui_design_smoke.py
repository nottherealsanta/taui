"""Smoke tests for the unified TUI design — verifies shortcuts and panels.

These are behavioral tests (no SVG snapshots) that drive `TauiApp` through
its public key bindings and assert on real DOM/widget state. They cover:

- ctrl+b toggles the left sidebar.
- The left sidebar is a files-only attachment panel.
- Sessions open in a modal picker.
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


# ── Sidebar files panel / sessions modal ───────────────────────────────


@pytest.mark.asyncio
async def test_sidebar_is_files_only(tmp_path, monkeypatch):
    """Ctrl+B should open the files panel, not a sessions list."""
    from textual.css.query import NoMatches
    from textual.widgets import DirectoryTree

    from taui.tui.widgets.sidebar import Sidebar

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        await pilot.press("ctrl+b")
        await pilot.pause()
        sidebar = pilot.app.query_one(Sidebar)
        assert sidebar.has_class("visible")
        assert sidebar._active_tab == "files"
        assert sidebar.query_one("#dir-tree", DirectoryTree).display is True
        with pytest.raises(NoMatches):
            sidebar.query_one("#sessions-list")
        await _close_cleanly(pilot)


@pytest.mark.asyncio
async def test_sessions_open_modal_picker(tmp_path, monkeypatch):
    """The sessions picker should be a modal rather than a sidebar tab."""
    from taui.tui.screens.session_picker import SessionPickerScreen

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)

        async def _stub_list():
            return [
                {
                    "session_id": "sess-x",
                    "description": "demo",
                    "message_count": 1,
                    "last_active": 1.0,
                    "created_at": 0.0,
                    "mode": "normal",
                }
            ]

        pilot.app._session.list_sessions = _stub_list  # type: ignore[assignment]
        await pilot.app._load_and_show_sessions()
        await pilot.pause()
        assert isinstance(pilot.app.screen, SessionPickerScreen)
        await pilot.press("escape")
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


# ── Right info sidebar: end-to-end ─────────────────────────────────────


@pytest.mark.asyncio
async def test_info_sidebar_all_sections_mount(tmp_path, monkeypatch):
    """All six section headers + bodies should be present in the DOM
    regardless of whether they have content yet."""
    from taui.tui.widgets.session_info_sidebar import SessionInfoSidebar

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        await pilot.press("ctrl+r")
        for _ in range(5):
            await pilot.pause()
        info_sidebar = pilot.app.query_one(SessionInfoSidebar)
        for key, label in (
            ("session", "Session"),
            ("agent", "Agent"),
            ("files", "Files edited"),
            ("lsp", "LSP"),
            ("mcp", "MCP"),
            ("tools", "Tools"),
        ):
            header = info_sidebar.query_one(f"#hdr-{key}")
            section = info_sidebar.query_one(f"#sec-{key}")
            assert header.is_mounted, f"#hdr-{key} missing"
            assert section.is_mounted, f"#sec-{key} missing"
        await _close_cleanly(pilot)


@pytest.mark.asyncio
async def test_info_sidebar_files_section_shows_edits(tmp_path, monkeypatch):
    """After a tool call that edits a file, the Files edited section
    should list it with +/- line counts. Verify the rendered path is
    legible (basename, not a 28-char-truncated absolute path)."""
    from taui.tui.widgets.session_info_sidebar import SessionInfoSidebar

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        # Simulate an edit call landing through the tool pipeline.
        pilot.app._record_edit(
            "write",
            {
                "file_path": str(tmp_path / "src" / "main.py"),
                "content": "print('hi')\nprint('bye')\n",
            },
        )
        # Open the sidebar — _refresh_info_sidebar is called on toggle.
        await pilot.press("ctrl+r")
        for _ in range(5):
            await pilot.pause()

        info_sidebar = pilot.app.query_one(SessionInfoSidebar)
        files_section = info_sidebar.query_one("#sec-files")
        rendered = " ".join(
            _widget_text(child) for child in files_section.children
        )
        assert "main.py" in rendered, (
            f"expected basename 'main.py' to appear in Files section, got "
            f"{rendered!r}"
        )
        assert "+3" in rendered, f"expected '+3' line count in {rendered!r}"
        await _close_cleanly(pilot)


@pytest.mark.asyncio
async def test_info_sidebar_tools_section_lists_tools(tmp_path, monkeypatch):
    """The Tools section should list the registered tool names."""
    from taui.tui.widgets.session_info_sidebar import SessionInfoSidebar

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        await pilot.press("ctrl+r")
        for _ in range(5):
            await pilot.pause()
        info_sidebar = pilot.app.query_one(SessionInfoSidebar)
        tools_section = info_sidebar.query_one("#sec-tools")
        rendered = " ".join(
            _widget_text(child) for child in tools_section.children
        )
        # A real session has at least the core builtins — we don't pin to a
        # specific set; just assert the row isn't the empty placeholder.
        assert rendered.strip() not in ("", "—"), (
            f"Tools section should not be empty, got {rendered!r}"
        )
        await _close_cleanly(pilot)


@pytest.mark.asyncio
async def test_info_sidebar_mcp_section_with_servers(tmp_path, monkeypatch):
    """If the session has an MCP manager with servers, MCP section should
    render one row per server with an online/offline indicator."""
    from taui.tui.widgets.session_info_sidebar import SessionInfoSidebar

    class FakeManager:
        server_names = ["filesystem", "github"]
        connected_servers = ["filesystem"]

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        pilot.app._session._mcp_manager = FakeManager()
        await pilot.press("ctrl+r")
        for _ in range(5):
            await pilot.pause()
        info_sidebar = pilot.app.query_one(SessionInfoSidebar)
        mcp_section = info_sidebar.query_one("#sec-mcp")
        rendered = " ".join(
            _widget_text(child) for child in mcp_section.children
        )
        assert "filesystem" in rendered
        assert "github" in rendered
        # filesystem is connected (●), github isn't (○) — both glyphs present.
        assert "●" in rendered, f"expected connected glyph in {rendered!r}"
        assert "○" in rendered, f"expected disconnected glyph in {rendered!r}"
        await _close_cleanly(pilot)


@pytest.mark.asyncio
async def test_info_sidebar_refreshes_on_turn_complete(tmp_path, monkeypatch):
    """When the info sidebar is open and a turn completes (which calls
    _update_status), the file edits accumulated during that turn should
    show up without the user toggling the sidebar again."""
    from taui.tui.widgets.session_info_sidebar import SessionInfoSidebar

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        await pilot.press("ctrl+r")
        for _ in range(5):
            await pilot.pause()

        info_sidebar = pilot.app.query_one(SessionInfoSidebar)
        files_section = info_sidebar.query_one("#sec-files")
        # Initially empty (or the "—" placeholder).
        before = " ".join(_widget_text(c) for c in files_section.children)
        assert "newfile.py" not in before

        # Edit happens mid-turn — the bookkeeping is on the app, not the
        # sidebar — and then _update_status triggers a refresh.
        pilot.app._record_edit(
            "write",
            {
                "file_path": str(tmp_path / "newfile.py"),
                "content": "x = 1\n",
            },
        )
        pilot.app._update_status()
        for _ in range(5):
            await pilot.pause()

        after = " ".join(_widget_text(c) for c in files_section.children)
        assert "newfile.py" in after, (
            f"file should appear after _update_status refresh; got {after!r}"
        )
        await _close_cleanly(pilot)


@pytest.mark.asyncio
async def test_info_sidebar_session_shows_name_and_gray_id(
    tmp_path, monkeypatch
):
    """Session section should show the description as the headline and the
    id below it rendered in gray. Model row was dropped entirely."""
    from taui.tui.widgets.session_info_sidebar import SessionInfoSidebar

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        # Give the session a human description.
        pilot.app._session.description = "Refactor login flow"
        await pilot.press("ctrl+r")
        for _ in range(5):
            await pilot.pause()
        info_sidebar = pilot.app.query_one(SessionInfoSidebar)
        section = info_sidebar.query_one("#sec-session")
        children = list(section.children)
        # Expect exactly two rows: name then id. No model row.
        assert len(children) == 2, (
            f"expected 2 rows (name, id), got {len(children)}: "
            f"{[_widget_text(c) for c in children]!r}"
        )
        name_row = children[0]
        id_row = children[1]
        name_text = name_row.render()
        id_text = id_row.render()
        assert "Refactor login flow" in name_text.plain
        sid = pilot.app._session.session_id
        assert sid in id_text.plain
        # Id span is dim gray. Accept either "#6e7681" or "rgb(110,118,129)".
        gray_spans = [
            sp for sp in id_text.spans
            if "rgb(110,118,129)" in str(sp.style) or "#6e7681" in str(sp.style)
        ]
        assert gray_spans, (
            f"id row should style the id in #6e7681 gray; spans: "
            f"{[str(sp.style) for sp in id_text.spans]!r}"
        )
        # And there should be no row containing the literal "model " label.
        rendered_all = " ".join(_widget_text(c) for c in children)
        assert "model " not in rendered_all
        await _close_cleanly(pilot)


@pytest.mark.asyncio
async def test_info_sidebar_agent_uses_agent_color_and_100_char_prompt(
    tmp_path, monkeypatch
):
    """Agent id should render in the per-agent color (same family the info
    bar uses), and the prompt preview should be the first 100 chars of the
    raw prompt — not just the first line."""
    from taui.tui.widgets.info_bar import _agent_color
    from taui.tui.widgets.session_info_sidebar import SessionInfoSidebar

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        info_sidebar = pilot.app.query_one(SessionInfoSidebar)
        long_prompt = (
            "First line of system prompt is short.\n"
            "Then comes more text that should keep flowing past the line\n"
            "break into the preview when we truncate at 100 chars total."
        )
        expected_color = _agent_color("FOO")
        info_sidebar.update_info(
            session_id="abc",
            agent_id="FOO",
            agent_id_color=expected_color,
            agent_name="Tester",
            agent_prompt_preview=long_prompt,
        )
        for _ in range(3):
            await pilot.pause()
        section = info_sidebar.query_one("#sec-agent")
        children = list(section.children)
        assert len(children) == 2, "agent section should have id-row + prompt-row"
        id_row, prompt_row = children
        id_text = id_row.render()
        assert "FOO" in id_text.plain
        # Style repr can be either "#d2a8ff" or "rgb(210,168,255)" depending
        # on how Textual normalises it; accept both.
        r, g, b = (
            int(expected_color[1:3], 16),
            int(expected_color[3:5], 16),
            int(expected_color[5:7], 16),
        )
        rgb_repr = f"rgb({r},{g},{b})"
        agent_styles = " ".join(str(sp.style) for sp in id_text.spans)
        assert expected_color in agent_styles or rgb_repr in agent_styles, (
            f"agent id should render in its assigned color {expected_color} "
            f"(or {rgb_repr}); styles: {agent_styles!r}"
        )
        prompt_text = prompt_row.render()
        plain = prompt_text.plain
        # First-line slicing would have left only "First line of system prompt
        # is short." here. We want first 100 chars verbatim, so the second
        # line's content should be present.
        assert "Then comes more text" in plain, (
            f"prompt preview should span past the first newline; got {plain!r}"
        )
        # Total length capped to 100 (plus the truncation ellipsis).
        assert len(plain) <= 101, (
            f"prompt preview should be at most 100 chars (+ellipsis); got {len(plain)}: {plain!r}"
        )
        await _close_cleanly(pilot)


@pytest.mark.asyncio
async def test_info_sidebar_escape_dismisses(tmp_path, monkeypatch):
    """The right sidebar should support Escape to dismiss when focused."""
    from taui.tui.widgets.session_info_sidebar import SessionInfoSidebar

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        await pilot.press("ctrl+r")
        await pilot.pause()
        info_sidebar = pilot.app.query_one(SessionInfoSidebar)
        assert info_sidebar.has_class("visible")
        info_sidebar.action_dismiss()
        await pilot.pause()
        assert not info_sidebar.has_class("visible")
        await _close_cleanly(pilot)


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
        assert bar.items[0].name == "hello.txt"
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


@pytest.mark.asyncio
async def test_folder_toggle_adds_folder_pill(tmp_path, monkeypatch):
    """Sidebar.FolderToggleRequested should add a folder pill and re-firing
    should remove it. Pill label is the folder's basename (no path)."""
    from taui.tui.widgets.attachments_bar import AttachmentsBar
    from taui.tui.widgets.sidebar import Sidebar

    folder = tmp_path / "src"
    folder.mkdir()
    (folder / "main.py").write_text("x = 1\n")

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        sidebar = pilot.app.query_one(Sidebar)
        sidebar.post_message(Sidebar.FolderToggleRequested(folder))
        for _ in range(3):
            await pilot.pause()

        bar = pilot.app.query_one(AttachmentsBar)
        assert bar.count == 1
        assert bar.items[0].kind == "folder"
        assert bar.items[0].name == "src"
        assert folder.resolve() in pilot.app._pending_folders

        # Second toggle removes
        sidebar.post_message(Sidebar.FolderToggleRequested(folder))
        for _ in range(3):
            await pilot.pause()
        assert bar.count == 0
        assert pilot.app._pending_folders == []
        await _close_cleanly(pilot)


@pytest.mark.asyncio
async def test_files_tree_selection_actually_adds_pill(tmp_path, monkeypatch):
    """End-to-end: simulate the real click pipeline through the
    DirectoryTree subclass and verify a pill lands in the attachments bar.

    This exercises Tree.NodeSelected → Sidebar.on_tree_node_selected →
    Sidebar.{File,Folder}ToggleRequested → app handler → AttachmentsBar.add
    instead of jumping the queue with a hand-posted FileToggleRequested.
    """
    from taui.tui.widgets.attachments_bar import AttachmentsBar
    from taui.tui.widgets.sidebar import Sidebar, _FilesTree

    sample = tmp_path / "hello.txt"
    sample.write_text("hi")

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        await pilot.press("ctrl+b")
        await pilot.pause()
        sidebar = pilot.app.query_one(Sidebar)
        sidebar.action_show_tab("files")
        await pilot.pause()
        tree = sidebar.query_one("#dir-tree", _FilesTree)
        # Make sure the root is expanded so we can find the file as a child.
        tree.root.expand()
        # Wait for filesystem-walk worker to populate children.
        for _ in range(20):
            await pilot.pause()
            if tree.root.children:
                break
        # Locate the sample file's node.
        target = None
        for child in tree.root.children:
            data = child.data
            if data is not None and Path(str(data.path)).name == "hello.txt":
                target = child
                break
        child_paths = [str(c.data.path) for c in tree.root.children if c.data]
        assert target is not None, f"hello.txt not found among {child_paths!r}"
        # Drive the same code path a real label-click runs: point the
        # cursor at the node and invoke our overridden action_select_cursor.
        target_line = next(
            i
            for i, line in enumerate(tree._tree_lines)  # noqa: SLF001
            if line.path[-1] is target
        )
        tree.cursor_line = target_line
        tree.action_select_cursor()
        for _ in range(5):
            await pilot.pause()

        bar = pilot.app.query_one(AttachmentsBar)
        assert bar.count == 1, (
            f"expected one pill after selecting hello.txt, got {bar.count}; "
            f"items={[item.name for item in bar.items]}"
        )
        assert bar.items[0].kind == "file"
        assert bar.items[0].name == "hello.txt"
        await _close_cleanly(pilot)


def test_files_tree_uses_chevron_icons():
    """The custom DirectoryTree subclass should use ▶/▼ chevrons and aligned
    spaces in place of the stock 📁/📂/📄 emojis, and auto_expand off so
    clicking a folder label doesn't open it."""
    from taui.tui.widgets.sidebar import _FilesTree

    assert _FilesTree.ICON_NODE == "▶ "
    assert _FilesTree.ICON_NODE_EXPANDED == "▼ "
    # File icon is whitespace-only so file names align with the folder name
    # that sits under the chevron.
    assert _FilesTree.ICON_FILE.strip() == ""
    assert _FilesTree.auto_expand is False


def test_render_folder_listing_prunes_cruft(tmp_path):
    """Folder listings should skip hidden dirs and common build/cache dirs."""
    from taui.tui.app import _render_folder_listing

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.cpython.pyc").write_text("")
    (tmp_path / "README.md").write_text("# hi")

    listing = _render_folder_listing(tmp_path)
    assert "src/" in listing
    assert "app.py" in listing
    assert "README.md" in listing
    assert ".git" not in listing
    assert "__pycache__" not in listing


@pytest.mark.asyncio
async def test_render_bar_attachments_file_substitutes_at_path(tmp_path, monkeypatch):
    """File pills should substitute ``[N]`` with ``@<relpath>``."""
    from taui.tui.widgets.attachments_bar import AttachmentsBar

    sample = tmp_path / "snippet.py"
    sample.write_text("print('hi')\n")
    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        bar = pilot.app.query_one(AttachmentsBar)
        bar.add(str(sample.resolve()), kind="file", name="snippet.py")
        chat_text, llm_text, images = pilot.app._render_bar_attachments(
            "explain this [1]", None
        )
        assert chat_text == "explain this @snippet.py"
        assert llm_text == "explain this @snippet.py"
        assert images is None
        await _close_cleanly(pilot)


@pytest.mark.asyncio
async def test_render_bar_attachments_paste_uses_token_count(tmp_path, monkeypatch):
    """Paste pills should render ``[Pasted <tokens>t]`` in the chat-log copy."""
    from taui.tui.widgets.attachments_bar import AttachmentsBar

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        bar = pilot.app.query_one(AttachmentsBar)
        paste = "x" * 400  # ~100 tokens at chars/4
        bar.add(paste, kind="paste")
        chat_text, llm_text, _ = pilot.app._render_bar_attachments(
            "see [1] please", None
        )
        assert "[Pasted 100t]" in chat_text
        assert "```text" in llm_text
        assert paste in llm_text
        await _close_cleanly(pilot)


@pytest.mark.asyncio
async def test_render_bar_attachments_image_uses_image_label(tmp_path, monkeypatch):
    """Image pills should render ``[Image M]`` based on image order."""
    from taui.tui.widgets.attachments_bar import AttachmentsBar

    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test() as pilot:
        await _wait_until_ready(pilot)
        bar = pilot.app.query_one(AttachmentsBar)
        bar.add("data:image/png;base64,first", kind="image")
        bar.add("data:image/png;base64,second", kind="image")
        chat_text, llm_text, images = pilot.app._render_bar_attachments(
            "[1] then [2]", ["data:image/png;base64,first", "data:image/png;base64,second"]
        )
        assert chat_text == "[Image 1] then [Image 2]"
        assert llm_text == "[Image 1] then [Image 2]"
        assert images == [
            "data:image/png;base64,first",
            "data:image/png;base64,second",
        ]
        await _close_cleanly(pilot)


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


# ── Modal design tokens: every overlay shares one theme-aware palette ────


def _modal_css() -> dict[str, str]:
    """DEFAULT_CSS of every modal that belongs to the shared design system,
    plus the command-palette rules from app.tcss."""
    from pathlib import Path

    from taui.tui.screens._picker_base import FuzzyPickerScreen
    from taui.tui.screens.compaction_inspector import CompactionInspectorScreen
    from taui.tui.screens.session_picker import SessionPickerScreen
    from taui.tui.screens.theme_picker import ThemePickerScreen

    css = {
        "FuzzyPickerScreen": FuzzyPickerScreen.DEFAULT_CSS,
        "ThemePickerScreen": ThemePickerScreen.DEFAULT_CSS,
        "SessionPickerScreen": SessionPickerScreen.DEFAULT_CSS,
        "CompactionInspectorScreen": CompactionInspectorScreen.DEFAULT_CSS,
    }
    tcss = Path(__file__).resolve().parents[1] / "taui" / "tui" / "app.tcss"
    text = tcss.read_text()
    start = text.index("CommandPalette {")
    css["app.tcss CommandPalette"] = text[start:]
    return css


#: The deliberate, theme-neutral *content* grays (GitHub-style) reused for
#: secondary/tertiary text. They read correctly on both light and dark and are
#: pinned by the tool-status / info-sidebar tests, so they are exempt from the
#: chrome-token rule below.
_SANCTIONED_CONTENT_GRAYS = {"#8b949e", "#6e7681"}


def test_modal_chrome_has_no_hardcoded_hex():
    """Every modal in the shared design system must drive its *chrome*
    (surfaces, borders, backdrops) from ``$taui-*`` tokens, never raw hex —
    that is what keeps the overlay layer consistent and working in both light
    and dark themes. Only the sanctioned neutral content grays are allowed."""
    import re

    offenders: dict[str, list[str]] = {}
    for name, css in _modal_css().items():
        hits = [
            h
            for h in re.findall(r"#[0-9a-fA-F]{6}", css)
            if h.lower() not in _SANCTIONED_CONTENT_GRAYS
        ]
        if hits:
            offenders[name] = hits
    assert not offenders, (
        f"hardcoded chrome colors found in modal CSS (use $taui-* tokens): {offenders}"
    )


def test_fuzzy_pickers_share_the_base_stylesheet():
    """The four fuzzy pickers must not re-declare their own DEFAULT_CSS —
    they inherit the single tokenized stylesheet from FuzzyPickerScreen, so
    they cannot drift apart again."""
    from taui.tui.screens._picker_base import FuzzyPickerScreen
    from taui.tui.screens.agent_picker import AgentPickerScreen
    from taui.tui.screens.model_picker import ModelPickerScreen
    from taui.tui.screens.prompt_picker import PromptPickerScreen
    from taui.tui.screens.skill_picker import SkillPickerScreen

    for cls in (
        ModelPickerScreen,
        AgentPickerScreen,
        SkillPickerScreen,
        PromptPickerScreen,
    ):
        assert "DEFAULT_CSS" not in cls.__dict__, (
            f"{cls.__name__} redeclares DEFAULT_CSS; it should inherit "
            f"FuzzyPickerScreen's so the pickers stay visually identical"
        )
        assert cls.DEFAULT_CSS is FuzzyPickerScreen.DEFAULT_CSS


def test_modal_tokens_defined_in_both_themes():
    """Each ``$taui-*`` token referenced by the modal CSS must exist in both
    the dark and light themes, so no overlay renders with an unresolved
    variable in either theme."""
    import re

    from taui.tui.theme import TAUI_DARK, TAUI_LIGHT

    referenced: set[str] = set()
    for css in _modal_css().values():
        referenced.update(re.findall(r"\$(taui-[a-z-]+)", css))

    assert referenced, "expected modal CSS to reference $taui-* tokens"
    for theme in (TAUI_DARK, TAUI_LIGHT):
        missing = referenced - set(theme.variables)
        assert not missing, (
            f"{theme.name} is missing modal tokens referenced in CSS: {missing}"
        )


# ── Banner widgets: accent colors come from the theme, not one-offs ──────


def test_banner_widgets_use_theme_accents_not_oneoff_colors():
    """The mcp / skills / tool-group / system-prompt banners must take their
    title and emphasis colors from the theme (``$primary`` / ``$accent``)
    rather than the old one-off ``#ff9e64`` orange and ``#d2a8ff`` purple,
    so they match the rest of the app and stay readable in the light theme."""
    import inspect

    from taui.tui.widgets import mcp_banner, skills_banner, system_prompt, tool_groups_banner

    for module in (mcp_banner, skills_banner, tool_groups_banner, system_prompt):
        src = inspect.getsource(module)
        assert "#ff9e64" not in src, (
            f"{module.__name__} still hardcodes the one-off orange #ff9e64; "
            f"use $primary so it matches the theme and works in light mode"
        )
        assert "#d2a8ff" not in src, (
            f"{module.__name__} still hardcodes #d2a8ff; use $accent instead"
        )


# ── No theme-blind CSS color names anywhere in the TUI ──────────────────


def test_no_theme_blind_css_color_names():
    """Literal CSS color names like ``cyan`` ignore the active theme and
    vanish against a light background (cyan is ~invisible on white). Modal
    titles and similar accents must use theme variables (e.g. ``$primary``)
    so they render in both themes."""
    import re
    from pathlib import Path

    tui_dir = Path(__file__).resolve().parents[1] / "taui" / "tui"
    banned = re.compile(r"(?:color|background):\s*(cyan|magenta)\b")
    offenders: dict[str, list[str]] = {}
    for path in sorted(tui_dir.rglob("*.py")):
        hits = banned.findall(path.read_text())
        if hits:
            offenders[str(path.relative_to(tui_dir))] = hits
    for path in sorted(tui_dir.rglob("*.tcss")):
        hits = banned.findall(path.read_text())
        if hits:
            offenders[str(path.relative_to(tui_dir))] = hits
    assert not offenders, (
        f"theme-blind CSS color names found (use $primary/$accent/etc.): {offenders}"
    )


# ── Light theme actually renders ────────────────────────────────────────


@pytest.mark.asyncio
async def test_app_renders_in_light_theme(tmp_path, monkeypatch):
    """The whole app must mount and render in the light theme with a light
    background — every modal/banner color is now driven by theme tokens, so a
    leftover dark-only surface would show up here as a near-black screen
    background under the light theme."""
    app = _make_app(monkeypatch, tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await _wait_until_ready(pilot)
        app.theme = "taui-light"
        for _ in range(4):
            await pilot.pause()

        assert app.current_theme.name == "taui-light"
        # The screen background must resolve to the light theme's background,
        # not a hardcoded dark value.
        bg = app.theme_variables.get("background")
        assert str(bg).lower() in ("#ffffff", "#fff"), (
            f"light theme background did not apply: {bg!r}"
        )
        # The shared modal tokens must resolve to their light values.
        assert str(app.theme_variables.get("taui-dialog-bg")).lower() == "#ffffff"
        await _close_cleanly(pilot)
