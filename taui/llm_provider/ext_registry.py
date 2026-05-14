"""Extension-safe proxy for registering LLM providers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from taui.llm_provider.base import BaseLLMProvider
from taui.llm_provider.registry import register_provider


class ProviderRegistrationProxy:
    """Proxy that extensions use to register new providers.

    Wraps the module-level register_provider() with a simpler API.
    """

    def register(
        self,
        name: str,
        *,
        label: str = "",
        factory: Callable[[Any], BaseLLMProvider],
        auth: Callable[[], Any] = lambda: None,
        default_model: str = "",
    ) -> None:
        register_provider(
            name,
            label=label or name,
            factory=factory,
            auth=auth,
            default_model=default_model,
        )
