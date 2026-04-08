import json
from pathlib import Path

from taui.config.project_settings import ProjectSettingsStore, default_settings


def test_settings_seed_and_roundtrip(tmp_path: Path) -> None:
    store = ProjectSettingsStore(tmp_path)
    settings = store.load()
    assert "tabs" in settings
    assert "layout" in settings
    assert "theme" in settings
    assert "prompts" in settings
    assert (tmp_path / ".taui" / "settings.json").exists()


def test_settings_prompt_update_and_reset(tmp_path: Path) -> None:
    store = ProjectSettingsStore(tmp_path)
    store.load()
    updated = store.update_prompt("prime_system", "custom prompt")
    assert updated["is_default"] is False
    assert updated["content"] == "custom prompt"
    reset = store.reset_prompt("prime_system")
    assert reset is not None
    assert reset["is_default"] is True


def test_settings_default_tabs(tmp_path: Path) -> None:
    store = ProjectSettingsStore(tmp_path)
    settings = store.load()
    tabs = settings["tabs"]
    assert isinstance(tabs["open"], list)
    assert isinstance(tabs["active"], str)


def test_settings_default_layout(tmp_path: Path) -> None:
    store = ProjectSettingsStore(tmp_path)
    settings = store.load()
    layout = settings["layout"]
    assert "sidebarCollapsed" in layout
    assert "splitSizes" in layout
    assert isinstance(layout["splitSizes"], list)
    assert len(layout["splitSizes"]) == 3


def test_settings_default_theme(tmp_path: Path) -> None:
    store = ProjectSettingsStore(tmp_path)
    settings = store.load()
    assert settings["theme"] in ("dark", "light")


def test_settings_file_is_valid_json(tmp_path: Path) -> None:
    store = ProjectSettingsStore(tmp_path)
    store.load()
    raw = (tmp_path / ".taui" / "settings.json").read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)


def test_settings_save_and_reload(tmp_path: Path) -> None:
    store = ProjectSettingsStore(tmp_path)
    settings = store.load()
    settings["theme"] = "light"
    store.save(settings)

    store2 = ProjectSettingsStore(tmp_path)
    reloaded = store2.load()
    assert reloaded["theme"] == "light"


def test_settings_merge_defaults_adds_missing_keys(tmp_path: Path) -> None:
    # Write a minimal settings file missing some keys
    (tmp_path / ".taui").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".taui" / "settings.json").write_text(
        json.dumps({"theme": "light"}), encoding="utf-8"
    )
    store = ProjectSettingsStore(tmp_path)
    settings = store.load()
    # Should merge in missing defaults
    assert "tabs" in settings
    assert "layout" in settings
    assert "prompts" in settings
    assert settings["theme"] == "light"


def test_settings_corrupted_file_falls_back_to_defaults(tmp_path: Path) -> None:
    (tmp_path / ".taui").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".taui" / "settings.json").write_text(
        "not valid json", encoding="utf-8"
    )
    store = ProjectSettingsStore(tmp_path)
    settings = store.load()
    assert "tabs" in settings
    assert "theme" in settings


def test_settings_invalid_json_type_falls_back(tmp_path: Path) -> None:
    (tmp_path / ".taui").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".taui" / "settings.json").write_text("[1, 2, 3]", encoding="utf-8")
    store = ProjectSettingsStore(tmp_path)
    settings = store.load()
    assert isinstance(settings, dict)
    assert "tabs" in settings


def test_settings_snapshot_includes_required_keys() -> None:
    settings = default_settings()
    assert "tabs" in settings
    assert "layout" in settings
    assert "theme" in settings
    assert "prompts" in settings
    assert "open" in settings["tabs"]
    assert "active" in settings["tabs"]


def test_settings_prompt_update_does_not_affect_other_prompts(tmp_path: Path) -> None:
    store = ProjectSettingsStore(tmp_path)
    store.load()
    store.update_prompt("prime_system", "custom prime")
    prompts = store.list_prompts()
    # Other prompts should remain at default
    assert prompts["tangle_maker"]["is_default"] is True
    assert prompts["prime_system"]["is_default"] is False
