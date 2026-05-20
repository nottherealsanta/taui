"""Tests for the self-edit modal screen (futuristic yellow console)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from taui.self_edit import inventory
from taui.tui.screens.self_edit_modal import (
    SelfEditModal,
    _ConfirmDelete,
    _Editor,
)
from tests.scenarios import scenarios
from tests.scenarios.tui_harness import use_scripted_provider


async def _ready(app, *, timeout: float = 2.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if app._session is not None and not app._session_initializing:
            return
        await asyncio.sleep(0)
    raise TimeoutError("session never ready")


# ── Inventory unit tests ──────────────────────────────────────────────


class TestInventory:
    def test_categories_exposed(self):
        keys = {c.key for c in inventory.CATEGORIES}
        assert keys == {"agents", "skills", "commands", "tools", "prompts", "mcp"}

    def test_create_and_list_command(self, tmp_path):
        inventory.save_item(
            tmp_path, "commands", "project", "demo", '"""one liner."""\n'
        )
        items = inventory.list_items(tmp_path, "commands", "project")
        assert [(i.identifier, i.summary) for i in items] == [("demo", "one liner.")]

    def test_create_and_delete_skill(self, tmp_path):
        inventory.save_item(
            tmp_path,
            "skills",
            "project",
            "ks",
            "---\nname: ks\ndescription: A skill\n---\nbody",
        )
        items = inventory.list_items(tmp_path, "skills", "project")
        assert [i.identifier for i in items] == ["ks"]
        inventory.delete_item(tmp_path, "skills", "project", "ks")
        assert inventory.list_items(tmp_path, "skills", "project") == []

    def test_create_and_delete_mcp(self, tmp_path):
        inventory.save_item(
            tmp_path,
            "mcp",
            "project",
            "demo",
            '[servers.demo]\ncommand = "x"\nargs = ["-y"]\n',
        )
        items = inventory.list_items(tmp_path, "mcp", "project")
        assert [(i.identifier, "x" in i.summary) for i in items] == [("demo", True)]
        inventory.delete_item(tmp_path, "mcp", "project", "demo")
        assert inventory.list_items(tmp_path, "mcp", "project") == []

    def test_create_and_delete_agent(self, tmp_path):
        inventory.save_item(
            tmp_path,
            "agents",
            "project",
            "XYZ",
            "Be quick.",
            {
                "name": "Xeno",
                "provider": "anthropic",
                "model": "claude-haiku",
                "allowed_tools": ["read", "grep"],
            },
        )
        items = inventory.list_items(tmp_path, "agents", "project")
        xyz = next((i for i in items if i.identifier == "XYZ"), None)
        assert xyz is not None
        assert xyz.extra["model"] == "claude-haiku"
        inventory.delete_item(tmp_path, "agents", "project", "XYZ")
        items = inventory.list_items(tmp_path, "agents", "project")
        assert all(i.identifier != "XYZ" for i in items)

    def test_counts_includes_all_categories(self, tmp_path):
        c = inventory.counts(tmp_path)
        assert set(c) == {
            "agents",
            "skills",
            "commands",
            "tools",
            "prompts",
            "mcp",
        }

    def test_first_docstring_extraction(self):
        assert inventory._first_docstring('"""Hi there."""\n') == "Hi there."
        assert (
            inventory._first_docstring('"""\nMulti.\nline.\n"""\n') == "Multi."
        )


# ── Modal screen tests ────────────────────────────────────────────────


class TestSelfEditModal:
    async def test_modal_opens_via_action(self, tmp_path, monkeypatch):
        provider = scenarios.happy_path("(unused)")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test() as pilot:
            await _ready(app)
            await app.action_enter_self_edit()
            await pilot.pause()
            assert isinstance(app.screen, SelfEditModal)
            await pilot.press("escape")
            await pilot.pause()
            await app._session.close()

    async def test_modal_starts_on_agents_and_shows_builtins(
        self, tmp_path, monkeypatch
    ):
        provider = scenarios.happy_path("(unused)")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test() as pilot:
            await _ready(app)
            await app.action_enter_self_edit()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SelfEditModal)
            assert screen._category.key == "agents"
            await pilot.press("escape")
            await app._session.close()

    async def test_modal_category_cycling(self, tmp_path, monkeypatch):
        provider = scenarios.happy_path("(unused)")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test() as pilot:
            await _ready(app)
            await app.action_enter_self_edit()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SelfEditModal)
            start = screen._category.key
            await pilot.press("right")
            await pilot.pause()
            assert screen._category.key != start
            await pilot.press("left")
            await pilot.pause()
            assert screen._category.key == start
            await pilot.press("escape")
            await app._session.close()

    async def test_modal_scope_toggle(self, tmp_path, monkeypatch):
        provider = scenarios.happy_path("(unused)")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test() as pilot:
            await _ready(app)
            await app.action_enter_self_edit()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SelfEditModal)
            start = screen._scope
            await pilot.press("tab")
            await pilot.pause()
            assert screen._scope != start
            await pilot.press("tab")
            await pilot.pause()
            assert screen._scope == start
            await pilot.press("escape")
            await app._session.close()

    async def test_modal_lists_created_command(self, tmp_path, monkeypatch):
        # Create a command on disk first.
        inventory.save_item(
            tmp_path, "commands", "project", "smoke", '"""Smoke test cmd."""\n'
        )
        provider = scenarios.happy_path("(unused)")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test() as pilot:
            await _ready(app)
            await app.action_enter_self_edit()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SelfEditModal)
            screen._scope = "project"
            # cycle to commands category
            while screen._category.key != "commands":
                screen.action_next_category()
            screen._refresh_items()
            await pilot.pause()
            ids = [i.identifier for i in screen._items]
            assert "smoke" in ids
            await pilot.press("escape")
            await app._session.close()

    async def test_modal_close_via_escape(self, tmp_path, monkeypatch):
        provider = scenarios.happy_path("(unused)")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test() as pilot:
            await _ready(app)
            await app.action_enter_self_edit()
            await pilot.pause()
            assert isinstance(app.screen, SelfEditModal)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, SelfEditModal)
            await app._session.close()

    async def test_modal_tabs_are_clickable(self, tmp_path, monkeypatch):
        from taui.tui.screens.self_edit_modal import (
            _CategoryClicked,
            _CategoryTab,
            _ScopeChip,
            _ScopeClicked,
        )

        provider = scenarios.happy_path("(unused)")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test(size=(160, 50)) as pilot:
            await _ready(app)
            await app.action_enter_self_edit()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SelfEditModal)

            tabs = list(screen.query(_CategoryTab))
            assert len(tabs) == len(inventory.CATEGORIES)

            # Posting the click message simulates the click handler firing
            # without depending on the tab's screen geometry.
            screen.post_message(_CategoryClicked("commands"))
            await pilot.pause()
            assert screen._category.key == "commands"

            chips = list(screen.query(_ScopeChip))
            assert len(chips) == 2
            screen.post_message(_ScopeClicked("project"))
            await pilot.pause()
            assert screen._scope == "project"

            await pilot.press("escape")
            await app._session.close()

    async def test_editor_llm_generate_populates_body(
        self, tmp_path, monkeypatch
    ):
        from taui.agent.types import Message
        from taui.llm_provider.types import StreamEvent
        from taui.tui.screens.self_edit_modal import _Editor

        # Build a fake provider whose stream_text yields one text_delta then done.
        class FakeProvider:
            async def stream_text(self, messages, model, temperature=0.1):
                # Sanity: the prompt is the last user message.
                assert messages[-1].role == "user"
                yield StreamEvent.text_delta("Generated body line 1.\n")
                yield StreamEvent.text_delta("Generated body line 2.\n")
                yield StreamEvent.done()

        provider = scenarios.happy_path("(unused)")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test() as pilot:
            await _ready(app)
            await app.action_enter_self_edit()
            await pilot.pause()

            editor = _Editor(
                category=inventory.category_by_key("commands"),
                scope="project",
                creating=True,
                item=None,
                provider=FakeProvider(),
                model="fake-model",
            )
            app.push_screen(editor)
            await pilot.pause()

            # Type id + brief, then trigger generate.
            from textual.widgets import Input

            editor.query_one("#se-editor-id", Input).value = "demo"
            editor.query_one(
                "#se-editor-llm-prompt", Input
            ).value = "print hello"
            editor._start_llm_generation()
            # Let the worker run.
            for _ in range(20):
                await pilot.pause()
                if "Generated body line" in editor.query_one(
                    "#se-editor-body"
                ).text:
                    break

            body_widget = editor.query_one("#se-editor-body")
            assert "Generated body line 1." in body_widget.text
            assert "Generated body line 2." in body_widget.text

            await app._session.close()
