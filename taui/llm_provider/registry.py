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

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from taui.llm_provider.base import BaseLLMProvider

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ProviderEntry:
    """Registration entry for a provider."""

    name: str
    label: str
    factory: Callable[[Any], BaseLLMProvider]
    auth: Callable[[], Any]
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


def create_provider(name: str) -> BaseLLMProvider:
    """Create and authenticate a provider by name."""
    entry = get_provider_entry(name)
    creds = entry.auth()
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
