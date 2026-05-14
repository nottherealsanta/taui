"""Tokenizer abstraction for per-provider token estimation."""

from __future__ import annotations

from collections.abc import Callable


class Tokenizer:
    """Token estimation strategy.

    Default: ~4 chars per token. Providers can supply better estimators.
    The calibration mechanism adjusts based on actual Usage.input_tokens.
    """

    def __init__(
        self,
        estimator: Callable[[str], int] | None = None,
    ) -> None:
        self._estimator = estimator or _default_estimator
        self._calibration_factor: float = 1.0

    def estimate(self, text: str) -> int:
        """Estimate token count for a text string."""
        raw = self._estimator(text)
        return max(1, int(raw * self._calibration_factor))

    def calibrate(self, estimated_tokens: int, actual_tokens: int) -> None:
        """Adjust estimation based on actual usage from the provider.

        Called after each turn with the estimated vs actual input token counts.
        Uses exponential moving average to smooth calibration.
        """
        if estimated_tokens <= 0 or actual_tokens <= 0:
            return
        ratio = actual_tokens / estimated_tokens
        # Exponential moving average with alpha=0.3
        self._calibration_factor = 0.7 * self._calibration_factor + 0.3 * ratio

    @property
    def calibration_factor(self) -> float:
        return self._calibration_factor


def _default_estimator(text: str) -> int:
    """~4 chars per token, minimum 1."""
    return max(1, len(text) // 4 + 1)


def create_tokenizer(provider_name: str = "") -> Tokenizer:
    """Create a tokenizer appropriate for the provider.

    Currently all providers use the default char/4 estimator.
    This is the extension point for adding tiktoken or other tokenizers.
    """
    # Future: if provider_name == "codex" and tiktoken available, use cl100k_base
    return Tokenizer()
