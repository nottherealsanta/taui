"""Global test fixtures.

Redirect home-backed Taui paths to a temp directory so tests never read or
write real user extensions, skills, agents, model caches, or config files.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import aiosqlite.core as _aiosqlite_core
import pytest

# aiosqlite runs every connection on a background worker thread that it creates
# *without* daemon=True. A test that forgets to close its Store leaks that
# thread, and threading._shutdown joins non-daemon threads with no timeout — so
# a single unclosed connection wedges the whole pytest process at exit (this was
# an intermittent multi-minute "hang" after the suite had already finished).
# Force the worker threads daemon for the test run so an unclosed test Store can
# never block interpreter shutdown. Production code closes its stores explicitly.
_RealAiosqliteThread = _aiosqlite_core.Thread


class _DaemonAiosqliteThread(_RealAiosqliteThread):  # type: ignore[valid-type,misc]
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("daemon", True)
        super().__init__(*args, **kwargs)


_aiosqlite_core.Thread = _DaemonAiosqliteThread

_DOMAIN_MARKERS = {
    "agent",
    "commands",
    "common",
    "config",
    "cost",
    "extensions",
    "git",
    "lsp",
    "mcp",
    "memory",
    "permissions",
    "prompts",
    "provider",
    "self_edit",
    "session",
    "skills",
    "store",
    "tasks",
    "tools",
    "tui",
    "webfetch",
    "worktree",
}

_FILE_DOMAINS: dict[str, set[str]] = {
    "test_agent.py": {"agent"},
    "test_agent_variants.py": {"agent"},
    "test_apply_patch.py": {"tools"},
    "test_at_completion.py": {"tui"},
    "test_auto_recovery.py": {"agent"},
    "test_background_bash.py": {"tasks", "tools"},
    "test_batch10.py": {"agent", "config", "extensions", "git", "store", "tools"},
    "test_builtins.py": {"tools"},
    "test_chat_input_movement.py": {"tui"},
    "test_chat_input_movement_visual.py": {"tui"},
    "test_commands.py": {"commands", "config", "extensions", "session", "tui"},
    "test_common.py": {"common"},
    "test_compact_property.py": {"agent"},
    "test_config.py": {"config"},
    "test_context.py": {"agent"},
    "test_cost.py": {"cost", "store"},
    "test_debug_mcp.py": {"mcp"},
    "test_debug_mcp_scripted.py": {"mcp"},
    "test_edit.py": {"tools"},
    "test_ext_registration.py": {"extensions"},
    "test_extensions.py": {"extensions"},
    "test_file_tracker.py": {"store"},
    "test_general_settings.py": {"config"},
    "test_git.py": {"git", "tools"},
    "test_git_workflow_commands.py": {"commands", "git"},
    "test_grep_glob.py": {"tools"},
    "test_hooks.py": {"extensions"},
    "test_lsp.py": {"lsp"},
    "test_lsp_tool.py": {"lsp", "tools"},
    "test_main.py": {"config"},
    "test_mcp.py": {"mcp"},
    "test_mcp_command.py": {"commands", "mcp"},
    "test_memory.py": {"tools"},
    "test_message_kind.py": {"agent"},
    "test_models.py": {"config", "provider"},
    "test_parallel_tools.py": {"tools"},
    "test_paste_attach.py": {"tui"},
    "test_permission_rules.py": {"permissions", "tools"},
    "test_permissions.py": {"permissions", "tools"},
    "test_prompt_builder.py": {"prompts"},
    "test_prompt_snapshot.py": {"prompts"},
    "test_provider_auth.py": {"provider"},
    "test_provider_errors.py": {"provider"},
    "test_provider_scenarios.py": {"agent", "provider"},
    "test_question.py": {"tools"},
    "test_resume_e2e.py": {"session", "store"},
    "test_retry.py": {"agent"},
    "test_run_result.py": {"agent"},
    "test_scenario_edge_cases.py": {"agent", "provider"},
    "test_scenario_loop_limits.py": {"agent", "provider"},
    "test_scenario_streaming.py": {"agent", "provider"},
    "test_scenario_tool_calls.py": {"agent", "provider", "tools"},
    "test_scenario_tui_interactions.py": {"tui"},
    "test_self_edit.py": {"self_edit", "tui"},
    "test_self_edit_modal.py": {"self_edit", "tui"},
    "test_self_edit_modal_visual.py": {"self_edit", "tui"},
    "test_session.py": {"session", "store"},
    "test_session_fork.py": {"session", "store"},
    "test_session_isolation.py": {"session", "store"},
    "test_session_picker.py": {"session", "store", "tui"},
    "test_skills.py": {"skills"},
    "test_skill_installer.py": {"skills"},
    "test_skill_install_command.py": {"skills", "commands"},
    "test_skills_mcp_banner.py": {"mcp", "skills", "tui"},
    "test_steering.py": {"agent"},
    "test_store.py": {"store"},
    "test_sub_agent.py": {"agent"},
    "test_symbols.py": {"lsp"},
    "test_task_manager.py": {"tasks"},
    "test_task_tool.py": {"tasks", "tools"},
    "test_tokenizer.py": {"agent"},
    "test_tool_groups.py": {"extensions", "tools", "tui"},
    "test_tool_result_ordering.py": {"agent", "store", "tools"},
    "test_tools.py": {"tools"},
    "test_truncation.py": {"tools"},
    "test_tui.py": {"tui"},
    "test_tui_design_smoke.py": {"tui"},
    "test_tui_visual.py": {"tui"},
    "test_webfetch.py": {"tools", "webfetch"},
    "test_widget_rendering_prototype.py": {"tui"},
    "test_worktree.py": {"tools", "worktree"},
    "test_worktree_command.py": {"commands", "worktree"},
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply domain groups from file names.

    Keep domain ownership here instead of hand-marking every test. The mapping is
    intentionally strict so new test files must declare at least one domain.
    """
    missing: set[str] = set()
    invalid: dict[str, set[str]] = {}

    for item in items:
        filename = Path(str(item.path)).name
        markers = set(_FILE_DOMAINS.get(filename, ()))
        if not markers:
            missing.add(filename)
            continue

        unknown = markers - _DOMAIN_MARKERS
        if unknown:
            invalid[filename] = unknown
            continue

        for marker in sorted(markers):
            item.add_marker(getattr(pytest.mark, marker))

    if missing or invalid:
        parts: list[str] = []
        if missing:
            parts.append(f"missing domain mapping for: {', '.join(sorted(missing))}")
        if invalid:
            bad = ", ".join(
                f"{filename} -> {', '.join(sorted(markers))}"
                for filename, markers in sorted(invalid.items())
            )
            parts.append(f"unknown test domains: {bad}")
        raise pytest.UsageError("; ".join(parts))


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path: Path):
    """Ensure tests use throwaway config and global taui state."""
    fake_home = tmp_path / "home"
    fake_taui = fake_home / ".taui"
    fake_config = fake_home / ".config" / "taui" / "config.toml"
    fake_skill_dirs = (
        fake_home / ".config" / "agents" / "skills",
        fake_taui / "skills",
    )

    with ExitStack() as stack:
        stack.enter_context(patch("pathlib.Path.home", return_value=fake_home))
        stack.enter_context(patch("taui.llm_provider.config.CONFIG_PATH", fake_config))
        stack.enter_context(
            patch("taui.llm_provider.models.CACHE_DIR", fake_home / ".cache" / "taui")
        )
        stack.enter_context(
            patch("taui.extensions.ExtensionRegistry.GLOBAL_DIR", fake_taui / "extensions")
        )
        stack.enter_context(patch("taui.skills.SkillRegistry.GLOBAL_DIRS", fake_skill_dirs))
        stack.enter_context(patch("taui.self_edit.store.SelfEditStore.GLOBAL_DIR", fake_taui))
        # Tests must never start a real interactive provider login: it blocks on
        # a device-flow poll that cannot be cancelled, hanging the whole suite at
        # teardown. The session path is already non-interactive; this seals the
        # remaining direct paths. Tests that exercise login mock it themselves.
        stack.enter_context(
            patch(
                "taui.llm_provider.auth.copilot.login",
                side_effect=RuntimeError("interactive copilot login is disabled in tests"),
            )
        )
        stack.enter_context(
            patch(
                "taui.llm_provider.auth.codex.login",
                side_effect=RuntimeError("interactive codex login is disabled in tests"),
            )
        )
        yield
