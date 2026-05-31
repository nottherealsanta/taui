"""Visual snapshot tests for the self-edit modal (yellow construction theme).

Only the GLOBAL scope view is snapshotted — PROJECT scope renders the
pytest tmp_path absolute path, which changes between runs and would
make the snapshot flaky. The rest of the modal's CRUD behavior is
covered by `test_self_edit_modal.py`.
"""

from __future__ import annotations

import asyncio

from textual.pilot import Pilot

from tests.scenarios import scenarios
from tests.scenarios.tui_harness import use_scripted_provider


async def _wait_until_ready(pilot: Pilot, *, timeout: float = 2.0) -> None:
    app = pilot.app
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        await pilot.pause()
        ready = (
            not getattr(app, "_session_initializing", True)
            and getattr(app, "_session", None) is not None
        )
        if ready:
            await pilot.pause()
            return
    raise TimeoutError("Session never finished initializing")


def _normalize_scope_path(pilot: Pilot) -> None:
    roots = [pilot.app.screen, *getattr(pilot.app, "screen_stack", [])]
    for root in roots:
        for path_label in root.query("#se-scope-path"):
            path_label.update("~/.taui  ")


async def _close_cleanly(pilot: Pilot) -> None:
    session = getattr(pilot.app, "_session", None)
    if session is not None:
        try:
            await session.close()
        except Exception:
            pass
        pilot.app._session = None


def test_self_edit_modal_opens_default(snap_compare, tmp_path, monkeypatch):
    """Modal opens on Agents tab, GLOBAL scope, yellow construction theme."""
    provider = scenarios.happy_path("(unused)")
    app = use_scripted_provider(monkeypatch, tmp_path, provider)

    async def setup(pilot: Pilot) -> None:
        await _wait_until_ready(pilot)
        await pilot.app.action_enter_self_edit()
        await pilot.pause()
        await pilot.pause()
        _normalize_scope_path(pilot)
        await _close_cleanly(pilot)

    assert snap_compare(app, run_before=setup, terminal_size=(120, 36))
