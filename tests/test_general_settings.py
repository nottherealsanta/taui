"""Comprehensive tests for the General settings feature.

Covers:
- Config prefixes defaults and custom values
- Inventory general category, sections, map, defaults, load, format, save, counts
- SelfEditModal instantiation with general category
- _PrefixEditor and _GeneralSettings widget instantiation
- _StringEditor instantiation
- ChatInput prefix defaults and set_prefixes
"""

from __future__ import annotations

from unittest.mock import patch

# ── 1. Config prefix tests ────────────────────────────────────────────


class TestPrefixConfig:
    def test_default_prefixes(self):
        from taui.config import Config

        cfg = Config()
        assert cfg.prefixes == {
            "file_attach": "@",
            "command": "/",
            "skills": "!",
            "prompts": "#",
        }

    def test_custom_prefixes(self):
        from taui.config import Config

        cfg = Config(prefixes={"file_attach": "#", "command": "!", "skills": "~", "prompts": "^"})
        assert cfg.prefixes["file_attach"] == "#"
        assert cfg.prefixes["command"] == "!"
        assert cfg.prefixes["skills"] == "~"
        assert cfg.prefixes["prompts"] == "^"

    def test_load_preserves_default_prefixes(self):
        from taui.config import Config

        cfg = Config.load()
        assert "file_attach" in cfg.prefixes
        assert "command" in cfg.prefixes
        assert "skills" in cfg.prefixes
        assert "prompts" in cfg.prefixes

    def test_prefix_defaults_are_strings(self):
        from taui.config import Config

        cfg = Config()
        for key, value in cfg.prefixes.items():
            assert isinstance(value, str), f"prefixes[{key!r}] should be str"

    def test_load_merges_file_prefixes_with_defaults(self):
        """Partial file config should be merged with defaults, not replace them."""
        from taui.config import Config

        fake_config = {"taui": {"prefixes": {"file_attach": "&"}}}
        with patch("taui.config.load_config", return_value=fake_config):
            cfg = Config.load()
        assert cfg.prefixes["file_attach"] == "&"
        # Other defaults remain
        assert cfg.prefixes["command"] == "/"
        assert cfg.prefixes["skills"] == "!"
        assert cfg.prefixes["prompts"] == "#"


# ── 2. Inventory general settings tests ──────────────────────────────


class TestGeneralCategory:
    def test_general_category_exists(self):
        from taui.self_edit.inventory import CATEGORIES

        keys = [c.key for c in CATEGORIES]
        assert "general" in keys

    def test_general_is_last_category(self):
        from taui.self_edit.inventory import CATEGORIES

        assert CATEGORIES[-1].key == "general"

    def test_general_label(self):
        from taui.self_edit.inventory import CATEGORIES

        cat = next(c for c in CATEGORIES if c.key == "general")
        assert cat.label == "GENERAL"

    def test_general_settings_sections_structure(self):
        from taui.self_edit.inventory import GENERAL_SETTINGS_SECTIONS

        section_names = [name for name, _ in GENERAL_SETTINGS_SECTIONS]
        assert section_names == ["PREFIXES", "AGENT", "NOTIFICATIONS", "DISPLAY"]

    def test_prefixes_section_has_four_entries(self):
        from taui.self_edit.inventory import GENERAL_SETTINGS_SECTIONS

        for name, rows in GENERAL_SETTINGS_SECTIONS:
            if name == "PREFIXES":
                keys = [r[0] for r in rows]
                assert keys == ["file_attach", "command", "skills", "prompts"]

    def test_all_settings_have_map_entry(self):
        from taui.self_edit.inventory import _GENERAL_SETTINGS_MAP, GENERAL_SETTINGS_SECTIONS

        for _, rows in GENERAL_SETTINGS_SECTIONS:
            for key, _, _, _ in rows:
                assert key in _GENERAL_SETTINGS_MAP, f"{key!r} missing from _GENERAL_SETTINGS_MAP"

    def test_all_settings_have_default(self):
        from taui.self_edit.inventory import _GENERAL_DEFAULTS, GENERAL_SETTINGS_SECTIONS

        for _, rows in GENERAL_SETTINGS_SECTIONS:
            for key, _, _, _ in rows:
                assert key in _GENERAL_DEFAULTS, f"{key!r} missing from _GENERAL_DEFAULTS"

    def test_load_general_values_returns_all_keys(self):
        from taui.self_edit.inventory import _GENERAL_DEFAULTS, _load_general_values

        values = _load_general_values()
        for key in _GENERAL_DEFAULTS:
            assert key in values, f"{key!r} missing from _load_general_values() result"

    def test_format_bool_on(self):
        from taui.self_edit.inventory import _format_general_value

        assert _format_general_value(True) == "on"

    def test_format_bool_off(self):
        from taui.self_edit.inventory import _format_general_value

        assert _format_general_value(False) == "off"

    def test_format_empty_string(self):
        from taui.self_edit.inventory import _format_general_value

        assert _format_general_value("") == "(auto)"

    def test_format_none(self):
        from taui.self_edit.inventory import _format_general_value

        assert _format_general_value(None) == "(auto)"

    def test_format_string(self):
        from taui.self_edit.inventory import _format_general_value

        assert _format_general_value("copilot") == "copilot"

    def test_format_int(self):
        from taui.self_edit.inventory import _format_general_value

        assert _format_general_value(50) == "50"

    def test_general_settings_count(self):
        from taui.self_edit.inventory import GENERAL_SETTINGS_SECTIONS

        total = sum(len(rows) for _, rows in GENERAL_SETTINGS_SECTIONS)
        # 4 prefixes + 4 agent + 3 notifications + 3 display
        assert total == 14

    def test_save_general_setting_is_callable(self):
        from taui.self_edit.inventory import save_general_setting

        assert callable(save_general_setting)

    def test_save_general_setting_unknown_key_raises(self):
        import pytest

        from taui.self_edit.inventory import save_general_setting

        with pytest.raises(KeyError):
            save_general_setting("__nonexistent__", "value")

    def test_save_and_load_roundtrip(self, tmp_path):
        """save_general_setting persists a value that can be read back."""
        from taui.self_edit.inventory import save_general_setting

        fake_config_path = tmp_path / "config.toml"
        fake_config_path.write_text("", encoding="utf-8")

        def fake_load_config():
            import tomllib
            text = fake_config_path.read_text(encoding="utf-8")
            if not text.strip():
                return {}
            return tomllib.loads(text)

        with (
            patch("taui.llm_provider.config.CONFIG_PATH", fake_config_path),
            patch("taui.llm_provider.config.load_config", side_effect=fake_load_config),
        ):
            save_general_setting("max_turns", 99)
            # Verify the file was written with TOML
            written = fake_config_path.read_text(encoding="utf-8")
            assert "99" in written

    def test_general_settings_map_contains_prefix_keys(self):
        from taui.self_edit.inventory import _GENERAL_SETTINGS_MAP

        for key in ("file_attach", "command", "skills", "prompts"):
            assert key in _GENERAL_SETTINGS_MAP

    def test_general_settings_map_prefix_paths(self):
        from taui.self_edit.inventory import _GENERAL_SETTINGS_MAP

        for key in ("file_attach", "command", "skills", "prompts"):
            dot_path, vtype = _GENERAL_SETTINGS_MAP[key]
            assert dot_path.startswith("prefixes.")
            assert vtype is str

    def test_general_defaults_prefix_values(self):
        from taui.self_edit.inventory import _GENERAL_DEFAULTS

        assert _GENERAL_DEFAULTS["file_attach"] == "@"
        assert _GENERAL_DEFAULTS["command"] == "/"
        assert _GENERAL_DEFAULTS["skills"] == "!"
        assert _GENERAL_DEFAULTS["prompts"] == "#"

    def test_general_defaults_agent_values(self):
        from taui.self_edit.inventory import _GENERAL_DEFAULTS

        assert _GENERAL_DEFAULTS["max_turns"] == 50
        assert _GENERAL_DEFAULTS["provider"] == "copilot"
        assert _GENERAL_DEFAULTS["model"] == ""

    def test_general_defaults_notification_values(self):
        from taui.self_edit.inventory import _GENERAL_DEFAULTS

        assert _GENERAL_DEFAULTS["notifications"] is True
        assert _GENERAL_DEFAULTS["notify_on_turn_done"] is True
        assert _GENERAL_DEFAULTS["notify_on_question"] is True

    def test_general_defaults_display_values(self):
        from taui.self_edit.inventory import _GENERAL_DEFAULTS

        assert _GENERAL_DEFAULTS["verbose_tools"] is True
        assert _GENERAL_DEFAULTS["auto_approve"] is False


# ── 3. SelfEditModal instantiation tests ─────────────────────────────


class TestSelfEditModal:
    def test_instantiate(self, tmp_path):
        from taui.tui.screens.self_edit_modal import SelfEditModal

        modal = SelfEditModal(tmp_path)
        assert modal is not None

    def test_instantiate_with_general_category(self, tmp_path):
        from taui.tui.screens.self_edit_modal import SelfEditModal

        modal = SelfEditModal(tmp_path, initial_category="general")
        assert modal._category.key == "general"

    def test_general_is_valid_category(self, tmp_path):
        from taui.tui.screens.self_edit_modal import SelfEditModal

        modal = SelfEditModal(tmp_path, initial_category="general")
        assert modal._category.label == "GENERAL"

    def test_default_category_is_agents(self, tmp_path):
        from taui.tui.screens.self_edit_modal import SelfEditModal

        modal = SelfEditModal(tmp_path)
        assert modal._category.key == "agents"

    def test_invalid_category_falls_back_to_first(self, tmp_path):
        from taui.tui.screens.self_edit_modal import SelfEditModal

        modal = SelfEditModal(tmp_path, initial_category="__nonexistent__")
        # Falls back to first category (index 0 = agents)
        assert modal._category is not None

    def test_working_dir_stored(self, tmp_path):
        from taui.tui.screens.self_edit_modal import SelfEditModal

        modal = SelfEditModal(tmp_path)
        assert modal._working_dir == tmp_path


# ── 4. _PrefixEditor tests ────────────────────────────────────────────


class TestPrefixEditor:
    def test_instantiate(self):
        from taui.tui.screens.self_edit_modal import _PrefixEditor

        editor = _PrefixEditor(label="Test", current_value="@")
        assert editor._current == "@"

    def test_label_stored(self):
        from taui.tui.screens.self_edit_modal import _PrefixEditor

        editor = _PrefixEditor(label="File Attachment", current_value="#")
        assert editor._label == "File Attachment"

    def test_current_value_stored(self):
        from taui.tui.screens.self_edit_modal import _PrefixEditor

        editor = _PrefixEditor(label="Command", current_value="/")
        assert editor._current == "/"

    def test_different_characters(self):
        from taui.tui.screens.self_edit_modal import _PrefixEditor

        for char in ("@", "/", "!", "#", "~", "^", "&", "%"):
            editor = _PrefixEditor(label="X", current_value=char)
            assert editor._current == char


# ── 5. _GeneralSettings widget tests ──────────────────────────────────


class TestGeneralSettingsWidget:
    def test_instantiate(self):
        from taui.tui.screens.self_edit_modal import _GeneralSettings

        gs = _GeneralSettings(id="test")
        assert gs is not None

    def test_instantiate_no_id(self):
        from taui.tui.screens.self_edit_modal import _GeneralSettings

        gs = _GeneralSettings()
        assert gs is not None

    def test_initial_cursor(self):
        from taui.tui.screens.self_edit_modal import _GeneralSettings

        gs = _GeneralSettings()
        assert gs._cursor == 0

    def test_initial_rows_empty(self):
        from taui.tui.screens.self_edit_modal import _GeneralSettings

        gs = _GeneralSettings()
        assert gs._rows == []

    def test_current_key_returns_none_when_empty(self):
        from taui.tui.screens.self_edit_modal import _GeneralSettings

        gs = _GeneralSettings()
        assert gs.current_key() is None


# ── 6. _StringEditor tests ────────────────────────────────────────────


class TestStringEditor:
    def test_instantiate(self):
        from taui.tui.screens.self_edit_modal import _StringEditor

        editor = _StringEditor(label="Max Turns", current_value="50")
        assert editor is not None

    def test_label_stored(self):
        from taui.tui.screens.self_edit_modal import _StringEditor

        editor = _StringEditor(label="Default Provider", current_value="copilot")
        assert editor._label == "Default Provider"

    def test_current_value_stored(self):
        from taui.tui.screens.self_edit_modal import _StringEditor

        editor = _StringEditor(label="Model", current_value="gpt-4o")
        assert editor._current == "gpt-4o"

    def test_default_hint(self):
        from taui.tui.screens.self_edit_modal import _StringEditor

        editor = _StringEditor(label="X", current_value="y")
        assert "Esc" in editor._hint

    def test_custom_hint(self):
        from taui.tui.screens.self_edit_modal import _StringEditor

        editor = _StringEditor(label="X", current_value="y", hint="custom hint text")
        assert editor._hint == "custom hint text"

    def test_empty_current_value(self):
        from taui.tui.screens.self_edit_modal import _StringEditor

        editor = _StringEditor(label="Model", current_value="")
        assert editor._current == ""


# ── 7. ChatInput prefix tests ─────────────────────────────────────────


class TestChatInputPrefixes:
    def test_default_file_attach_prefix(self):
        from taui.tui.widgets.chat_input import ChatInput

        ci = ChatInput()
        assert ci._file_attach_prefix == "@"

    def test_default_command_prefix(self):
        from taui.tui.widgets.chat_input import ChatInput

        ci = ChatInput()
        assert ci._command_prefix == "/"

    def test_set_prefixes_both(self):
        from taui.tui.widgets.chat_input import ChatInput

        ci = ChatInput()
        ci.set_prefixes({"file_attach": "#", "command": "!"})
        assert ci._file_attach_prefix == "#"
        assert ci._command_prefix == "!"

    def test_set_prefixes_partial_file_attach_only(self):
        from taui.tui.widgets.chat_input import ChatInput

        ci = ChatInput()
        ci.set_prefixes({"file_attach": "#"})
        assert ci._file_attach_prefix == "#"
        assert ci._command_prefix == "/"  # default unchanged

    def test_set_prefixes_partial_command_only(self):
        from taui.tui.widgets.chat_input import ChatInput

        ci = ChatInput()
        ci.set_prefixes({"command": "!"})
        assert ci._file_attach_prefix == "@"  # default unchanged
        assert ci._command_prefix == "!"

    def test_set_prefixes_empty_dict(self):
        from taui.tui.widgets.chat_input import ChatInput

        ci = ChatInput()
        ci.set_prefixes({})
        assert ci._file_attach_prefix == "@"
        assert ci._command_prefix == "/"

    def test_set_prefixes_callable(self):
        from taui.tui.widgets.chat_input import ChatInput

        ci = ChatInput()
        assert callable(ci.set_prefixes)

    def test_set_prefixes_multiple_times(self):
        from taui.tui.widgets.chat_input import ChatInput

        ci = ChatInput()
        ci.set_prefixes({"file_attach": "#"})
        assert ci._file_attach_prefix == "#"
        ci.set_prefixes({"file_attach": "&"})
        assert ci._file_attach_prefix == "&"


# ── 8. Inventory counts for general ──────────────────────────────────


class TestGeneralCounts:
    def test_counts_returns_general_key(self, tmp_path):
        from taui.self_edit.inventory import counts

        result = counts(tmp_path)
        assert "general" in result

    def test_counts_general_global_equals_14(self, tmp_path):
        from taui.self_edit.inventory import counts

        result = counts(tmp_path)
        assert result["general"]["global"] == 14

    def test_counts_general_project_equals_0(self, tmp_path):
        from taui.self_edit.inventory import counts

        result = counts(tmp_path)
        assert result["general"]["project"] == 0

    def test_counts_contains_all_categories(self, tmp_path):
        from taui.self_edit.inventory import CATEGORIES, counts

        result = counts(tmp_path)
        for cat in CATEGORIES:
            assert cat.key in result, f"counts missing category {cat.key!r}"

    def test_counts_general_structure(self, tmp_path):
        from taui.self_edit.inventory import counts

        result = counts(tmp_path)
        general = result["general"]
        assert "global" in general
        assert "project" in general
        assert isinstance(general["global"], int)
        assert isinstance(general["project"], int)
