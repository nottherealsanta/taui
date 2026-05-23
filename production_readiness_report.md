# Production Readiness Report

Date: 2026-05-23

Verdict: not production ready. The release gates do not pass, and the remaining
failures include TUI workflow regressions in the product's only supported interface.

## Checks Run

| Check | Result |
| --- | --- |
| `uv run ruff check .` | Failed before linting: `ruff` is not installed in the project environment. |
| `uv run --with ruff ruff check .` | Failed with 54 lint errors. 33 are auto-fixable. |
| `uv run python -m pytest tests/ -q` | Failed: 60 failed, 1135 passed, 2 warnings. |
| `env HOME=/private/tmp/taui-empty-home uv run python -m pytest tests/test_extensions.py tests/test_skills.py -q` | Passed: 60 passed. |
| `env HOME=/private/tmp/taui-empty-home uv run python -m pytest tests/ -q` | Failed: 42 failed, 1153 passed, 2 warnings. |

Note: I briefly ran `uv run python -m pytest tests/test_tui_visual.py --snapshot-update -q`
as a probe. It updated 21 snapshots and passed that focused file; those generated snapshot
changes were reverted and are not part of this report.

## Major Hurdles

### 1. Release gates fail before functional readiness can be trusted

The documented check `uv run ruff check .` cannot run because `ruff` is missing from the
project dependency groups. `pyproject.toml:72` defines the `dev` group with pytest and
Textual tooling only; Ruff is configured at `pyproject.toml:38` but not installed.

Using `uv run --with ruff ruff check .` confirms the lint baseline is not clean:
54 errors across source, scripts, and tests. The most common issues are unsorted imports,
unused imports, ambiguous variable names, and lines over the configured 100-character
limit.

Why this blocks production: the standard handoff command is broken, and a clean CI signal
cannot be produced from the repo as configured.

Recommended next actions:

- Add Ruff to the dev dependency group or change the documented check to the injected
  form intentionally.
- Fix or auto-fix the 54 lint errors.
- Re-run `uv run ruff check .` as the canonical gate.

### 2. Extension and skill discovery is not hermetic under test

The default registries always scan global user directories:

- `taui/extensions/__init__.py:123` scans `Path.home() / ".taui" / "extensions"`.
- `taui/skills/__init__.py:95` scans global skill directories before project skills.

On this machine, `/Users/santa/.taui/extensions/notebook_edit.py` is discovered during
tests and then fails to load because it imports `taui.tools.builtins.notebook_edit`, which
does not exist. That single global file caused extension tests and TUI startup paths to
see unexpected extension state. Global skills similarly changed the expected skill list.

Evidence: the normal full suite failed 60 tests. Re-running only extension and skill tests
with an empty `HOME` passed all 60 tests:

```bash
env HOME=/private/tmp/taui-empty-home uv run python -m pytest tests/test_extensions.py tests/test_skills.py -q
```

Why this blocks production: the test suite is environment-dependent, and user-installed
extensions/skills can change startup behavior and command output in unrelated tests.

Recommended next actions:

- Add a test fixture that isolates `HOME` or monkeypatches global extension/skill paths.
- Consider an explicit registry option for `include_globals=False` in tests.
- Keep runtime extension failures isolated, but make startup warnings and registry state
  deterministic in automated checks.

### 3. TUI behavior and visual contracts are out of sync

With global state isolated, the full suite still fails 42 tests. The failures cluster around
TUI behavior and snapshot contracts:

- 33 Textual snapshots fail, with one unused snapshot.
- `tests/test_scenario_tui_interactions.py::TestSlashCommands::test_clear_removes_chat_log_children`
  still queries `#chat-log`, but runtime now creates per-session logs with ids like
  `chat-log-{sid}` at `taui/tui/app.py:464`.
- `tests/test_scenario_tui_interactions.py::TestApprovalFlow::test_bash_call_triggers_approval_prompt`
  expects approval mode, but `Info2` remains hidden.
- `tests/test_self_edit.py::test_handle_command_routes_slash_i_to_session_toggle`
  can raise `NoMatches("No chat log found")` through `_get_active_chat_log()` at
  `taui/tui/app.py:486`.
- `/copy` now returns `CommandResult` metadata for the TUI to copy at
  `taui/commands/builtins.py:615`, while the command test still expects direct `pbcopy`.
- Self-edit inventory tests expect six categories, but runtime now exposes an additional
  `general` category.

Why this blocks production: Taui is a full-screen Textual TUI only, so unresolved TUI
workflow failures are product failures, not cosmetic test noise.

Recommended next actions:

- Decide which TUI changes are intentional, then update the tests and snapshots in one
  reviewed pass.
- Fix behavior failures before accepting snapshots: approval prompt visibility, command
  handling without an active chat log, and any broken slash command workflows.
- Replace direct `#chat-log` test assumptions with the active session chat log helper or
  add a stable compatibility selector if external code relies on it.

