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

    def test_tools_section_includes_builtins(self, tmp_path):
        items = inventory.list_items(tmp_path, "tools", "global")
        builtins = [i for i in items if i.builtin]
        assert len(builtins) >= 5
        names = {i.identifier for i in builtins}
        assert {"read", "edit", "write", "bash"}.issubset(names)

    def test_all_tool_names_lists_builtins(self, tmp_path):
        names = inventory.all_tool_names(tmp_path)
        assert "read" in names
        assert "edit" in names
        assert "bash" in names


class TestModelPicker:
    def test_subseq_match(self):
        from taui.tui.screens.self_edit_modal import _subseq_match

        assert _subseq_match("hk", "haiku")
        assert _subseq_match("snn", "sonnet")
        assert not _subseq_match("xyz", "haiku")
        assert _subseq_match("", "haiku")

    def test_picker_row_shows_provider_name(self):
        from taui.tui.screens.self_edit_modal import _ModelPicker

        picker = _ModelPicker(
            models=["claude-haiku", "gpt-4o"],
            provider_of={"claude-haiku": "anthropic", "gpt-4o": "openai"},
        )
        row = picker._row("claude-haiku")
        text = row.plain
        assert "claude-haiku" in text
        assert "anthropic" in text
        # Provider sits to the right of the model id.
        assert text.index("claude-haiku") < text.index("anthropic")

    async def test_picker_search_input_has_no_placeholder(
        self, tmp_path, monkeypatch
    ):
        from textual.widgets import Input

        from taui.tui.screens.self_edit_modal import _ModelPicker

        provider = scenarios.happy_path("(unused)")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test(size=(120, 40)) as pilot:
            await _ready(app)
            app.push_screen(_ModelPicker(models=["claude-haiku"]))
            await pilot.pause()
            search = app.screen.query_one("#se-mp-search", Input)
            assert search.placeholder == ""
            await pilot.press("escape")
            await app._session.close()

    def test_picker_filter_substring_first(self):
        from taui.tui.screens.self_edit_modal import _ModelPicker

        picker = _ModelPicker(
            models=[
                "claude-haiku-4.5",
                "claude-sonnet-4.6",
                "claude-opus-4.7",
                "gpt-4o",
            ],
        )
        # Substring matches come before subsequence matches.
        result = picker._filter("haiku")
        assert result == ["claude-haiku-4.5"]
        result = picker._filter("cl")
        assert result[0].startswith("claude-")
        # Subsequence picks up scattered matches.
        result = picker._filter("g4o")
        assert "gpt-4o" in result


class TestListView:
    def test_format_inventory_listing_all_categories(self, tmp_path):
        from taui.self_edit.list_view import format_inventory_listing

        text = format_inventory_listing(tmp_path)
        # Should mention every category label.
        for cat in inventory.CATEGORIES:
            assert cat.label in text
        # Both scopes appear.
        assert "global" in text
        assert "project" in text

    def test_format_inventory_listing_single_category(self, tmp_path):
        from taui.self_edit.list_view import format_inventory_listing

        text = format_inventory_listing(tmp_path, category="tools")
        # Tools section header is present, includes builtins.
        assert "▰ TOOLS" in text
        assert "read" in text
        # Other section headers are NOT rendered.
        assert "▰ SKILLS" not in text
        assert "▰ MCP" not in text

    def test_format_inventory_listing_unknown_category_raises(self, tmp_path):
        import pytest

        from taui.self_edit.list_view import format_inventory_listing

        with pytest.raises(KeyError):
            format_inventory_listing(tmp_path, category="nonsense")

    def test_format_inventory_listing_escapes_markup(self, tmp_path):
        from taui.self_edit import inventory as inv
        from taui.self_edit.list_view import format_inventory_listing

        # Create a command whose docstring has Rich-markup-like brackets —
        # the listing must escape them or Rich will try to parse them.
        inv.save_item(
            tmp_path,
            "commands",
            "project",
            "demo",
            '"""Has [tricky] markup."""\n',
        )
        text = format_inventory_listing(tmp_path, category="commands")
        assert r"\[tricky\]" in text

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

    async def test_modal_new_button_at_bottom_of_list(
        self, tmp_path, monkeypatch
    ):
        from textual.widgets import Button

        provider = scenarios.happy_path("(unused)")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test(size=(160, 50)) as pilot:
            await _ready(app)
            await app.action_enter_self_edit()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SelfEditModal)
            new_btn = screen.query_one("#se-new-button", Button)
            assert new_btn is not None
            # Clicking the button opens the editor in creating mode.
            from taui.tui.screens.self_edit_modal import _Editor

            new_btn.press()
            await pilot.pause()
            assert isinstance(app.screen, _Editor)
            await pilot.press("escape")
            await pilot.pause()
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

    async def test_agent_editor_uses_single_model_id_and_tool_grid(
        self, tmp_path, monkeypatch
    ):
        from textual.widgets import Input

        from taui.tui.screens.self_edit_modal import _Editor, _ToolToggle

        provider = scenarios.happy_path("(unused)")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test(size=(160, 50)) as pilot:
            await _ready(app)
            editor = _Editor(
                category=inventory.category_by_key("agents"),
                scope="project",
                creating=True,
                item=None,
                working_dir=tmp_path,
                provider=None,
                model="claude-haiku",
                provider_name="anthropic",
            )
            app.push_screen(editor)
            await pilot.pause()

            # Single combined model id input — no separate PROVIDER field.
            # Empty by default (the user asked for "empty by default,
            # optional"); a separate hint line explains it's optional.
            model_input = editor.query_one("#se-editor-model-id", Input)
            assert model_input.value == ""
            assert model_input.placeholder == ""

            # No editor-level model input besides MODEL ID — Generate
            # always opens the fuzzy picker.
            assert not editor.query("#se-editor-gen-model")

            # Agent id label is "AGENT ID" not "ID / NAME"
            from taui.tui.screens.self_edit_modal import _ToolToggle  # noqa: F401
            from textual.widgets import Label

            labels = [str(lbl.render()) for lbl in editor.query(Label)]
            assert "AGENT ID" in labels
            assert "ID / NAME" not in labels

            # Tools are rendered as a Grid of _ToolToggle widgets (one per
            # tool), not a SelectionList — so the user can click each cell
            # and see clearly which are on/off.
            toggles = list(editor.query(_ToolToggle))
            assert len(toggles) >= 5
            assert all(not t.is_selected for t in toggles)  # none selected yet

            # Click two toggles on.
            for t in toggles:
                if t.tool_name in {"read", "edit"}:
                    t.toggle()

            editor.query_one("#se-editor-id", Input).value = "XYZ"
            # Submit by invoking the underlying helper directly.
            saved: dict = {}
            dismissed_called = [False]

            def fake_dismiss(result):
                dismissed_called[0] = True
                if result is not None:
                    saved.update(result)

            editor.dismiss = fake_dismiss  # type: ignore[method-assign]
            editor._submit()

            # No model id typed — defaults stay empty.
            assert saved["extra"]["provider"] == ""
            assert saved["extra"]["model"] == ""
            assert set(saved["extra"]["allowed_tools"]) == {"read", "edit"}
            await app._session.close()

    async def test_tabs_wrap_to_two_rows_on_narrow_terminal(
        self, tmp_path, monkeypatch
    ):
        from textual.containers import Horizontal

        from taui.tui.screens.self_edit_modal import _CategoryTab

        provider = scenarios.happy_path("(unused)")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test(size=(70, 40)) as pilot:
            await _ready(app)
            await app.action_enter_self_edit()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SelfEditModal)
            row1 = screen.query_one("#se-tabs-row-1", Horizontal)
            row2 = screen.query_one("#se-tabs-row-2", Horizontal)
            tabs_r1 = list(row1.query(_CategoryTab))
            tabs_r2 = list(row2.query(_CategoryTab))
            # On a narrow 70-col terminal the categories should be split.
            assert len(tabs_r1) > 0
            assert len(tabs_r2) > 0
            assert len(tabs_r1) + len(tabs_r2) == len(inventory.CATEGORIES)
            await pilot.press("escape")
            await app._session.close()

    async def test_tabs_stay_in_one_row_on_wide_terminal(
        self, tmp_path, monkeypatch
    ):
        from textual.containers import Horizontal

        from taui.tui.screens.self_edit_modal import _CategoryTab

        provider = scenarios.happy_path("(unused)")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test(size=(200, 40)) as pilot:
            await _ready(app)
            await app.action_enter_self_edit()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SelfEditModal)
            row1 = screen.query_one("#se-tabs-row-1", Horizontal)
            row2 = screen.query_one("#se-tabs-row-2", Horizontal)
            assert len(list(row1.query(_CategoryTab))) == len(
                inventory.CATEGORIES
            )
            assert len(list(row2.query(_CategoryTab))) == 0
            await pilot.press("escape")
            await app._session.close()

    async def test_no_inline_model_input_for_any_panel(
        self, tmp_path, monkeypatch
    ):
        """Generate flow is unified — no panel has a separate model id box
        next to the Generate button; clicking Generate always opens the
        fuzzy model picker."""
        from taui.tui.screens.self_edit_modal import _Editor

        provider = scenarios.happy_path("(unused)")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test(size=(160, 50)) as pilot:
            await _ready(app)
            for cat_key in ("agents", "skills", "commands", "tools", "prompts", "mcp"):
                editor = _Editor(
                    category=inventory.category_by_key(cat_key),
                    scope="project",
                    creating=True,
                    item=None,
                    working_dir=tmp_path,
                    provider=None,
                    model="claude-haiku",
                    provider_name="anthropic",
                )
                app.push_screen(editor)
                await pilot.pause()
                assert not editor.query("#se-editor-gen-model"), cat_key
                await pilot.press("escape")
                await pilot.pause()
            await app._session.close()

    async def test_generate_opens_fuzzy_model_picker(
        self, tmp_path, monkeypatch
    ):
        from textual.widgets import Input

        from taui.tui.screens import self_edit_modal as sem
        from taui.tui.screens.self_edit_modal import _Editor, _ModelPicker

        # Stub the model catalog so the picker has something to show.
        monkeypatch.setattr(
            sem,
            "_available_models",
            lambda provider: [
                ("claude-haiku", "anthropic"),
                ("claude-sonnet", "anthropic"),
            ],
        )

        class FakeProvider:
            async def stream_text(self, messages, model, temperature=0.1):
                if False:
                    yield None  # pragma: no cover
                return

        provider = scenarios.happy_path("(unused)")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test(size=(160, 50)) as pilot:
            await _ready(app)
            editor = _Editor(
                category=inventory.category_by_key("commands"),
                scope="project",
                creating=True,
                item=None,
                working_dir=tmp_path,
                provider=FakeProvider(),
                model="claude-haiku",
                provider_name="anthropic",
            )
            app.push_screen(editor)
            await pilot.pause()
            editor.query_one("#se-editor-llm-prompt", Input).value = "do thing"
            editor._start_llm_generation()
            await pilot.pause()
            assert isinstance(app.screen, _ModelPicker)
            await pilot.press("escape")
            await app._session.close()

    async def test_edit_mode_has_brief_and_edit_button(
        self, tmp_path, monkeypatch
    ):
        """When editing an existing item, the same prompt+button row
        appears but the button reads 'Edit' instead of 'Generate'."""
        from textual.widgets import Button

        from taui.tui.screens.self_edit_modal import _Editor

        # Pre-create a command so we have something to edit.
        inv_path = inventory.save_item(
            tmp_path, "commands", "project", "demo",
            '"""hi."""\nprint("hi")\n',
        )
        items = inventory.list_items(tmp_path, "commands", "project")
        item = next(i for i in items if i.identifier == "demo")

        provider = scenarios.happy_path("(unused)")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test(size=(160, 50)) as pilot:
            await _ready(app)
            editor = _Editor(
                category=inventory.category_by_key("commands"),
                scope="project",
                creating=False,
                item=item,
                working_dir=tmp_path,
                provider=None,
                model="claude-haiku",
                provider_name="anthropic",
            )
            app.push_screen(editor)
            await pilot.pause()

            btn = editor.query_one("#se-editor-generate", Button)
            assert str(btn.label) == "◆ Edit"
            # Brief input still present.
            assert editor.query("#se-editor-llm-prompt")
            await app._session.close()

    async def test_do_generate_edit_mode_modifies_existing_body(
        self, tmp_path, monkeypatch
    ):
        """In edit mode, the LLM gets the current body in the prompt and
        the response replaces the body."""
        import json

        from taui.llm_provider.types import StreamEvent
        from taui.tui.screens.self_edit_modal import _Editor

        captured_prompt = []

        class FakeProvider:
            async def stream_text(self, messages, model, temperature=0.1):
                json.dumps(messages)
                captured_prompt.append(messages[-1]["content"])
                yield StreamEvent.text_delta("Edited result body.\n")
                yield StreamEvent.done()

        # Pre-create an item to edit.
        inventory.save_item(
            tmp_path, "commands", "project", "demo",
            "original body to be edited",
        )
        items = inventory.list_items(tmp_path, "commands", "project")
        item = next(i for i in items if i.identifier == "demo")

        provider = scenarios.happy_path("(unused)")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test() as pilot:
            await _ready(app)
            editor = _Editor(
                category=inventory.category_by_key("commands"),
                scope="project",
                creating=False,
                item=item,
                working_dir=tmp_path,
                provider=FakeProvider(),
                model="fake-model",
                provider_name="fake",
            )
            app.push_screen(editor)
            await pilot.pause()
            await editor._do_generate("make it terser", "fake-model")

            # The prompt contains both the user instruction and the
            # existing body so the model can produce a diff-style edit.
            assert "make it terser" in captured_prompt[0]
            assert "original body to be edited" in captured_prompt[0]
            # Body has been replaced with the streamed response.
            from textual.widgets import TextArea
            assert "Edited result body." in editor.query_one(
                "#se-editor-body", TextArea
            ).text
            await app._session.close()

    async def test_agent_editor_requires_at_least_one_tool(
        self, tmp_path, monkeypatch
    ):
        from textual.widgets import Input

        from taui.tui.screens.self_edit_modal import _Editor

        provider = scenarios.happy_path("(unused)")
        app = use_scripted_provider(monkeypatch, tmp_path, provider)
        async with app.run_test(size=(160, 50)) as pilot:
            await _ready(app)
            editor = _Editor(
                category=inventory.category_by_key("agents"),
                scope="project",
                creating=True,
                item=None,
                working_dir=tmp_path,
                provider=None,
                model="",
                provider_name="",
            )
            app.push_screen(editor)
            await pilot.pause()
            editor.query_one("#se-editor-id", Input).value = "XYZ"

            dismissed = [False]

            def fake_dismiss(result):
                dismissed[0] = True

            editor.dismiss = fake_dismiss  # type: ignore[method-assign]
            editor._submit()
            # No tool selected — submit should be refused.
            assert dismissed[0] is False
            await app._session.close()

    async def test_editor_llm_generate_populates_body(
        self, tmp_path, monkeypatch
    ):
        import json

        from taui.llm_provider.types import StreamEvent
        from taui.tui.screens.self_edit_modal import _Editor

        # Build a fake provider whose stream_text yields text_deltas then done.
        # The provider must accept plain dicts (json-serializable) — passing
        # Message dataclasses would crash real providers with
        # "Object of type Message is not JSON serializable".
        class FakeProvider:
            async def stream_text(self, messages, model, temperature=0.1):
                # Sanity: messages are JSON-serializable dicts.
                json.dumps(messages)
                assert messages[-1]["role"] == "user"
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
                working_dir=tmp_path,
                provider=FakeProvider(),
                model="fake-model",
                provider_name="fake",
            )
            app.push_screen(editor)
            await pilot.pause()

            # Type id + brief, then trigger generate.
            from textual.widgets import Input

            editor.query_one("#se-editor-id", Input).value = "demo"
            editor.query_one(
                "#se-editor-llm-prompt", Input
            ).value = "print hello"
            # Drive the worker directly — Generate now opens a fuzzy model
            # picker first; the worker is what actually runs after the user
            # picks a model.
            await editor._do_generate("print hello", "fake-model")

            body_widget = editor.query_one("#se-editor-body")
            assert "Generated body line 1." in body_widget.text
            assert "Generated body line 2." in body_widget.text

            await app._session.close()
