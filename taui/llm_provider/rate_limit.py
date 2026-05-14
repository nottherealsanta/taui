"""Per-vendor rate-limit semaphore.

Prevents multiple concurrent sessions from stampeding the same provider
endpoint. Uses a token-bucket-style approach with a configurable
concurrency limit.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass(slots=True)
class RateLimiter:
    """Async semaphore-based rate limiter per provider.

    Usage::

        limiter = RateLimiter(max_concurrent=2)
        async with limiter.acquire():
            result = await provider.create_turn(...)
    """

    max_concurrent: int = 2
    _semaphore: asyncio.Semaphore = field(init=False)
    _total_requests: int = field(default=0, init=False)
    _active_requests: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

    class _AcquireContext:
        """Async context manager for rate limit acquisition."""

        def __init__(self, limiter: RateLimiter) -> None:
            self._limiter = limiter

        async def __aenter__(self) -> None:
            await self._limiter._semaphore.acquire()
            self._limiter._active_requests += 1
            self._limiter._total_requests += 1

        async def __aexit__(self, *exc: object) -> None:
            self._limiter._active_requests -= 1
            self._limiter._semaphore.release()

    def acquire(self) -> _AcquireContext:
        """Return an async context manager that acquires the semaphore."""
        return self._AcquireContext(self)

    @property
    def active(self) -> int:
        """Number of currently active requests."""
        return self._active_requests

    @property
    def total(self) -> int:
        """Total number of requests processed."""
        return self._total_requests


# ── Global registry ──────────────────────────────────────────────────────────

_limiters: dict[str, RateLimiter] = {}


def get_limiter(provider_name: str, max_concurrent: int = 2) -> RateLimiter:
    """Get or create a rate limiter for a provider."""
    if provider_name not in _limiters:
        _limiters[provider_name] = RateLimiter(max_concurrent=max_concurrent)
    return _limiters[provider_name]


def reset_all() -> None:
    """Clear all limiters (for testing)."""
    _limiters.clear()
