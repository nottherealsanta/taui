from pathlib import Path

from taui.config.project_settings import ProjectSettingsStore, default_prompt_content


def test_prompts_list_get_update_reset(tmp_path: Path) -> None:
    store = ProjectSettingsStore(tmp_path)
    seeded = store.list_prompts()
    assert "prime_system" in seeded

    current = store.get_prompt("prime_system")
    assert current is not None

    next_prompt = store.update_prompt("prime_system", "new content")
    assert next_prompt["content"] == "new content"
    assert next_prompt["is_default"] is False

    reset = store.reset_prompt("prime_system")
    assert reset is not None
    assert reset["is_default"] is True


def test_prompts_all_default_keys_present(tmp_path: Path) -> None:
    store = ProjectSettingsStore(tmp_path)
    prompts = store.list_prompts()
    for key in default_prompt_content():
        assert key in prompts, f"Missing prompt key: {key}"


def test_prompts_default_is_default_flag(tmp_path: Path) -> None:
    store = ProjectSettingsStore(tmp_path)
    prompts = store.list_prompts()
    for key, value in prompts.items():
        assert value["is_default"] is True, f"Expected is_default=True for {key}"
        assert "content" in value
        assert "last_updated" in value


def test_prompts_update_sets_is_default_false(tmp_path: Path) -> None:
    store = ProjectSettingsStore(tmp_path)
    store.load()
    result = store.update_prompt("tangle_maker", "Custom tangle maker prompt.")
    assert result["is_default"] is False
    assert result["content"] == "Custom tangle maker prompt."


def test_prompts_reset_restores_default_content(tmp_path: Path) -> None:
    store = ProjectSettingsStore(tmp_path)
    store.load()
    original = store.get_prompt("root_agent_system")
    assert original is not None
    original_content = original["content"]

    store.update_prompt("root_agent_system", "something else")
    store.reset_prompt("root_agent_system")

    restored = store.get_prompt("root_agent_system")
    assert restored is not None
    assert restored["is_default"] is True
    assert restored["content"] == original_content


def test_prompts_reset_unknown_key_returns_none(tmp_path: Path) -> None:
    store = ProjectSettingsStore(tmp_path)
    store.load()
    result = store.reset_prompt("non_existent_key")
    assert result is None


def test_prompts_get_unknown_key_returns_none(tmp_path: Path) -> None:
    store = ProjectSettingsStore(tmp_path)
    store.load()
    result = store.get_prompt("does_not_exist")
    assert result is None


def test_prompts_update_persists_across_reload(tmp_path: Path) -> None:
    store = ProjectSettingsStore(tmp_path)
    store.load()
    store.update_prompt("sub_agent_system", "persistent custom prompt")

    store2 = ProjectSettingsStore(tmp_path)
    prompt = store2.get_prompt("sub_agent_system")
    assert prompt is not None
    assert prompt["content"] == "persistent custom prompt"
    assert prompt["is_default"] is False


def test_prompts_upgrade_only_overwrites_default_prompts(tmp_path: Path) -> None:
    """Simulates the upgrade scenario: default prompts are overwritten on reset,
    user-edited prompts are preserved."""
    store = ProjectSettingsStore(tmp_path)
    store.load()

    # User edits prime_system — is_default becomes False
    store.update_prompt("prime_system", "my custom prime")
    # tangle_reviewer remains at default

    prompts = store.list_prompts()
    assert prompts["prime_system"]["is_default"] is False
    assert prompts["tangle_reviewer"]["is_default"] is True

    # Simulate upgrade: reset only default prompts
    for key, prompt in prompts.items():
        if prompt["is_default"]:
            store.reset_prompt(key)

    # prime_system was user-edited — should NOT be reset
    assert store.get_prompt("prime_system")["content"] == "my custom prime"  # type: ignore[index]
    # tangle_reviewer was default — would be reset by upgrade logic
    assert store.get_prompt("tangle_reviewer")["is_default"] is True  # type: ignore[index]


def test_prompts_list_returns_all_five_prompts(tmp_path: Path) -> None:
    store = ProjectSettingsStore(tmp_path)
    prompts = store.list_prompts()
    expected_keys = {
        "prime_system",
        "root_agent_system",
        "sub_agent_system",
        "tangle_maker",
        "tangle_reviewer",
    }
    assert set(prompts.keys()) == expected_keys
