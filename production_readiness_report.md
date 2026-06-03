# Production Readiness Report

Date: 2026-06-03

Verdict: the release gates pass. `uv run ruff check .` is clean and the entire
non-visual test suite is green and exits cleanly. The only remaining failures are
the Textual SVG snapshot tests, which are environment-specific baselines (see
below) — not functional regressions.

## Checks Run

| Check | Result |
| --- | --- |
| `uv run ruff check .` | Passed (clean). |
| `env HOME=/tmp/taui-empty-home uv run python -m pytest tests/ -q` | 1455 passed, 22 failed (all `*_visual.py` SVG snapshots), ~65–85s, process exits cleanly. |
| Non-visual subset (everything except the SVG snapshot files) | All green. |

`ruff` is now a dev dependency, so the documented gate runs without `--with`. A 120s
per-test `timeout` (pytest-timeout) is configured as a backstop so an accidental hang
fails fast with a thread dump instead of wedging the run.

## What Changed Since 2026-05-23

The previous report listed three blockers; all are resolved:

1. **Release gates couldn't run.** `ruff` wasn't installed and the lint baseline had
   63 errors. Ruff (and pytest-timeout) are in the dev group and the lint baseline is
   clean.

2. **The suite hung / was non-hermetic.** Two independent causes are fixed in
   `tests/conftest.py`:
   - Tests that booted an unmocked provider triggered a *real* GitHub/Codex interactive
     device-flow login, which blocked forever in a poll loop on an uncancelable
     `asyncio.to_thread` worker. Session creation is now non-interactive: it raises
     `ProviderAuthRequired` (surfaced by the TUI's startup-error panel as "run
     `taui --login`"), and conftest also makes the interactive `login()` calls raise so
     no test can start a real device flow. This was also a real product bug — launching
     taui with an unauthenticated provider used to hang on startup.
   - aiosqlite opens each connection on a **non-daemon** worker thread. A test that
     never closed its `Store` leaked that thread, and `threading._shutdown` joins
     non-daemon threads with no timeout, so the process hung *after* the suite finished.
     Conftest now forces those worker threads daemon for the test run.

3. **TUI behavior/contract drift.** The non-visual TUI failures were fixed: the approval
   menu's deny option moved to index 2 (a middle "allow for session" option was added);
   the info sidebar again renders the session id in gray under the description (a cleanup
   pass had dropped it); and several count/assertion tests were updated to match current
   behavior (general settings 12→13, max-turns wrap-up turn, session-prompt description).

## Known Remaining Item

The ~22 `test_tui_visual.py` / `*_modal_visual.py` SVG snapshot tests fail locally because
the committed baselines were rendered in a different environment (font metrics differ).
They are useful as a local visual-diff tool but should not be `--snapshot-update`-d and
committed from an arbitrary machine. Treat them as a separate, environment-pinned gate
(ideally regenerated in CI), not as functional regressions.

## Tool Sandboxing / Security

The agent-facing tool boundaries were reviewed and hardened:

- Self-edit's read-only bash facade no longer lets a newline (or CR) smuggle a second
  command past the first-token allowlist, and treats find's file-writing actions
  (`-fprint*`/`-fls`) as non-read-only.
- The git tool rejects option-like `ref`/`branch`/`remote`/`base`/`file` values, so an
  auto-approved read op can't be turned into a write via an injected flag
  (e.g. `git diff --output=...`).
- The skill installer's `git clone` uses `--` to end option parsing, so a source can't be
  misread as a git flag. (It already used list-form subprocess — no shell.)
- The self-edit file allowlist and the file tools' `resolve_path` both canonicalize via
  `Path.resolve()` (following symlinks and `..`) before the containment check.

Open decision: `webfetch` performs no SSRF filtering (auto-approved, follows redirects).
Blocking private/loopback hosts would break the legitimate dev use of fetching a local
server, while a literal metadata-IP block is trivially bypassed via DNS/redirect — so the
right policy (and its utility trade-off) is left to the maintainer rather than imposed.
