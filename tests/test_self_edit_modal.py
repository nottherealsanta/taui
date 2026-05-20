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
