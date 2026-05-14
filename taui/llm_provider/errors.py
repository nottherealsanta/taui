"""Typed error hierarchy for LLM provider failures."""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for all provider errors."""

    def __init__(self, message: str, *, status_code: int | None = None, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class ContextOverflowError(ProviderError):
    """Context length exceeded — conversation too long."""


class QuotaExceededError(ProviderError):
    """User's plan quota or billing limit reached."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str = "",
        resets_in_seconds: int | None = None,
    ):
        super().__init__(message, status_code=status_code, body=body)
        self.resets_in_seconds = resets_in_seconds


class TransientProviderError(ProviderError):
    """Retryable error — rate limit, server error, transient network issue."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str = "",
        retry_after: float | None = None,
    ):
        super().__init__(message, status_code=status_code, body=body)
        self.retry_after = retry_after


class AuthExpiredError(ProviderError):
    """Authentication token expired or invalid."""
