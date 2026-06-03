"""
Provider registry — centralized mapping from provider names to factory functions.

All provider-specific wiring (imports, credential fetching, instantiation) is registered
here. Other modules use `create_provider()` and `KNOWN_PROVIDERS` instead of hardcoding
match/if-elif blocks.

To add a new provider:
  1. Implement a BaseLLMProvider subclass in providers/
  2. Implement a credentials getter in auth/
  3. Call register_provider() here or in your extension
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from taui.llm_provider.base import BaseLLMProvider

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ProviderEntry:
    """Registration entry for a provider.

    ``auth`` may optionally accept an ``interactive`` keyword. When ``False``
    (used by session creation) it must not block on user input — it should
    raise instead, so an unauthenticated launch fails fast with a clear message.
    """

    name: str
    label: str
    factory: Callable[[Any], BaseLLMProvider]
    auth: Callable[..., Any]
    default_model: str


_REGISTRY: dict[str, ProviderEntry] = {}


def register_provider(
    name: str,
    *,
    label: str,
    factory: Callable[[Any], BaseLLMProvider],
    auth: Callable[[], Any],
    default_model: str,
) -> None:
    """Register a provider by name."""
    _REGISTRY[name] = ProviderEntry(
        name=name,
        label=label,
        factory=factory,
        auth=auth,
        default_model=default_model,
    )


def get_provider_names() -> list[str]:
    """Return sorted list of registered provider names."""
    return sorted(_REGISTRY)


def get_provider_entry(name: str) -> ProviderEntry:
    """Look up a provider entry. Raises ValueError if unknown."""
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise ValueError(f"Unknown provider: {name!r}. Available: {available}")
    return _REGISTRY[name]


def _call_auth(auth: Callable[..., Any], *, interactive: bool) -> Any:
    """Call a provider auth callable, passing ``interactive`` only if accepted.

    Keeps backward compatibility with extension providers whose ``auth`` takes
    no arguments (the original contract).
    """
    try:
        params = inspect.signature(auth).parameters
    except (TypeError, ValueError):
        return auth()
    accepts_interactive = "interactive" in params or any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
    )
    return auth(interactive=interactive) if accepts_interactive else auth()


def create_provider(name: str, *, interactive: bool = False) -> BaseLLMProvider:
    """Create and authenticate a provider by name.

    ``interactive`` defaults to ``False`` because this is the session-creation
    path: it must surface a clear auth error rather than block on an
    interactive login the user may not be able to see. The ``taui --login``
    flow authenticates interactively before the TUI starts.
    """
    entry = get_provider_entry(name)
    creds = _call_auth(entry.auth, interactive=interactive)
    return entry.factory(creds)


# ── Register builtins ──────────────────────────────────────────────────────────


def _register_builtins() -> None:
    """Register the built-in copilot and codex providers."""
    from taui.llm_provider.auth.codex import get_codex_credentials
    from taui.llm_provider.auth.copilot import get_copilot_credentials
    from taui.llm_provider.providers.codex import CodexProvider
    from taui.llm_provider.providers.copilot import CopilotProvider

    register_provider(
        "copilot",
        label="GitHub Copilot",
        factory=lambda creds: CopilotProvider(credentials=creds),
        auth=get_copilot_credentials,
        default_model="claude-haiku-4.5",
    )
    register_provider(
        "codex",
        label="OpenAI Codex (ChatGPT Plus/Pro)",
        factory=lambda creds: CodexProvider(credentials=creds),
        auth=get_codex_credentials,
        default_model="gpt-5.3-codex",
    )


_register_builtins()
