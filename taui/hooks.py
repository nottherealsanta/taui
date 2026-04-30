"""
taui.hooks — extension hook system.

Hooks let extensions customize every aspect of taui without modifying
source code.  Extensions register hook functions via the ``hooks``
argument to ``register(tools, commands, hooks)``.

Hook categories
───────────────
**UI hooks** (sync, return values — all return ``str | None``):
  prompt(session)       — override the input prompt text
  banner(session)       — add a line to the startup banner
  status(session)       — add a status-bar segment
  turn_summary(result, session) — add a segment to the turn summary

**Pipeline hooks** (sync or async, transform data):
  before_send(message, session) -> message
  after_result(result, session) -> result
  system_prompt(prompt, session) -> prompt

**Observer hooks** (sync or async, side-effects only):
  on_tool_call(name, args, session)
  on_tool_result(name, content, is_error, session)
  on_session_start(session)
  on_mode_change(mode, session)

**Override hooks** (sync or async, first non-None wins):
  on_approval(name, args, session) -> bool | None

Custom hooks
────────────
Extensions can also register arbitrary hooks with ``hooks.add(name, fn)``
and fire them with ``hooks.run(name, …)``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class HookRegistry:
    """Collects and executes hook functions registered by extensions."""

    def __init__(self) -> None:
        self._hooks: dict[str, list[Callable[..., Any]]] = {}

    # ── Registration ──────────────────────────────────────────────────────

    def add(self, name: str, fn: Callable[..., Any]) -> None:
        """Register a hook function under *name*."""
        self._hooks.setdefault(name, []).append(fn)

    # Convenience — typed registrars for the documented hooks
    def prompt(self, fn: Callable[..., Any]) -> None:
        self.add("prompt", fn)

    def banner(self, fn: Callable[..., Any]) -> None:
        self.add("banner", fn)

    def status(self, fn: Callable[..., Any]) -> None:
        self.add("status", fn)

    def turn_summary(self, fn: Callable[..., Any]) -> None:
        self.add("turn_summary", fn)

    def before_send(self, fn: Callable[..., Any]) -> None:
        self.add("before_send", fn)

    def after_result(self, fn: Callable[..., Any]) -> None:
        self.add("after_result", fn)

    def system_prompt(self, fn: Callable[..., Any]) -> None:
        self.add("system_prompt", fn)

    def on_tool_call(self, fn: Callable[..., Any]) -> None:
        self.add("on_tool_call", fn)

    def on_tool_result(self, fn: Callable[..., Any]) -> None:
        self.add("on_tool_result", fn)

    def on_session_start(self, fn: Callable[..., Any]) -> None:
        self.add("on_session_start", fn)

    def on_mode_change(self, fn: Callable[..., Any]) -> None:
        self.add("on_mode_change", fn)

    def on_approval(self, fn: Callable[..., Any]) -> None:
        self.add("on_approval", fn)

    # ── Inspection ────────────────────────────────────────────────────────

    def has(self, name: str) -> bool:
        """True if at least one hook is registered under *name*."""
        return bool(self._hooks.get(name))

    def clear(self) -> None:
        """Remove all registered hooks."""
        self._hooks.clear()

    @property
    def hook_names(self) -> list[str]:
        return sorted(self._hooks)

    def count(self, name: str) -> int:
        return len(self._hooks.get(name, []))

    # ── Execution helpers ─────────────────────────────────────────────────

    async def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Call *fn*, awaiting if it's async."""
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        return fn(*args, **kwargs)

    async def run(self, name: str, *args: Any, **kwargs: Any) -> list[Any]:
        """Run all hooks for *name*. Return a list of results.

        Errors in individual hooks are logged and skipped — one broken
        extension should never crash the agent.
        """
        results: list[Any] = []
        for fn in self._hooks.get(name, []):
            try:
                results.append(await self._call(fn, *args, **kwargs))
            except Exception:
                logger.warning("Hook %s failed in %s", name, fn, exc_info=True)
        return results

    async def collect(self, name: str, *args: Any, **kwargs: Any) -> list[Any]:
        """Like :meth:`run` but filters out ``None`` results."""
        return [r for r in await self.run(name, *args, **kwargs) if r is not None]

    async def transform(self, name: str, value: Any, *args: Any, **kwargs: Any) -> Any:
        """Run hooks as a pipeline — each receives and returns *value*.

        Used for ``before_send``, ``after_result``, ``system_prompt``.
        """
        for fn in self._hooks.get(name, []):
            try:
                value = await self._call(fn, value, *args, **kwargs)
            except Exception:
                logger.warning("Hook %s transform failed in %s", name, fn, exc_info=True)
        return value

    async def first(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """Return the first non-None result. Used for ``on_approval``."""
        for fn in self._hooks.get(name, []):
            try:
                result = await self._call(fn, *args, **kwargs)
                if result is not None:
                    return result
            except Exception:
                logger.warning("Hook %s failed in %s", name, fn, exc_info=True)
        return None
