# Testing

Run focused tests near the code you changed, then the full suite for shared behavior.

## Standard Checks

```bash
uv run ruff check .
uv run python -m pytest -q -m tools  # replace tools with the changed domain
```

Pick the domain marker that matches the code you changed. Run the complete suite before
merges or when changing shared behavior:

```bash
uv run python -m pytest -q
```

Ruff settings are in `pyproject.toml:40`. Test dependencies and commands should stay in
repo tooling rather than docs-only assumptions.

## Test Groups

`tests/conftest.py` assigns domain pytest markers from file names, so most changes do not
need the whole suite:

```bash
uv run python -m pytest -q -m tools
uv run python -m pytest -q -m agent
uv run python -m pytest -q -m store
uv run python -m pytest -q -m extensions
uv run python -m pytest -q -m "agent or provider"
uv run python -m pytest -q -m tui
```

Available domain markers are `agent`, `commands`, `common`, `config`, `cost`,
`extensions`, `git`, `lsp`, `mcp`, `memory`, `permissions`, `prompts`, `provider`,
`self_edit`, `session`, `skills`, `store`, `tasks`, `tools`, `tui`, `webfetch`, and
`worktree`.

## Focus Areas

| Change area | Tests |
| --- | --- |
| tools and policy | `tests/test_tools.py:1`, `tests/test_builtins.py:1`, `tests/test_question.py:1` |
| agent loop and context | `tests/test_agent.py:1`, `tests/test_context.py:1`, `tests/test_sub_agent.py:1` |
| TUI behavior | `tests/test_tui.py:1`, `tests/test_tui_visual.py:1` |
| config/session/store | `tests/test_config.py:1`, `tests/test_session.py:1`, `tests/test_store.py:1` |
| extensions/skills/hooks | `tests/test_extensions.py:1`, `tests/test_skills.py:1`, `tests/test_hooks.py:1` |
| provider scenarios | `tests/test_provider_scenarios.py:1` |

## Scripted Provider Harness

The deterministic provider lives in `tests/scenarios/scripted_provider.py:82`.
Scenario factories live in `tests/scenarios/scenarios.py:25`.

Use this harness when testing provider response shapes without network or auth:

- provider contract tests: `tests/test_provider_scenarios.py:1`
- TUI visual snapshots: `tests/test_tui_visual.py:1`
- app harness: `tests/scenarios/tui_harness.py:32`

## Visual Snapshots

Verify:

```bash
uv run python -m pytest -q tests/test_tui_visual.py tests/test_chat_input_movement_visual.py
```

Update only after inspecting the generated diff report:

```bash
uv run python -m pytest tests/test_tui_visual.py --snapshot-update
```

The visual tests render `TauiApp` with `ScriptedProvider`, so they should stay offline
and deterministic: `tests/test_tui_visual.py:12`.
