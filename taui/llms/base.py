"""
Abstract base class for all LLM chat clients.

Subclasses implement build_request(), parse_chunk(), and refresh_credentials().
The base class owns the SSE streaming loop, retry logic, and error handling.
"""

from __future__ import annotations

import asyncio
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

# ── Types ──────────────────────────────────────────────────────────────────────

Message = dict[str, str]  # {"role": "user"|"assistant"|"system", "content": str}


@dataclass
class LLMRequest:
    url: str
    headers: dict[str, str]
    body: dict  # JSON-serializable


# ── Retry config ───────────────────────────────────────────────────────────────

MAX_RETRIES = 3
BASE_RETRY_DELAY = 1.0  # seconds
MAX_SERVER_DELAY = 60.0  # if server asks for more, fail immediately

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_RETRYABLE_PATTERNS = re.compile(
    r"rate.?limit|overloaded|service.?unavailable|resource.?exhausted"
    r"|upstream.?connect|connection.?refused|other.?side.?closed",
    re.IGNORECASE,
)

# ── Context overflow detection ─────────────────────────────────────────────────

_OVERFLOW_PATTERNS = re.compile(
    r"prompt is too long"
    r"|input is too long for requested model"
    r"|exceeds the context window"
    r"|input token count.*exceeds the maximum"
    r"|maximum prompt length is \d+"
    r"|reduce the length of the messages"
    r"|maximum context length is \d+ tokens"
    r"|exceeds the available context size"
    r"|exceeded model token limit"
    r"|exceeds the limit of \d+"
    r"|context[_ ]length[_ ]exceeded"
    r"|too many tokens"
    r"|token limit exceeded",
    re.IGNORECASE,
)


# ── Base class ─────────────────────────────────────────────────────────────────


class BaseLLMClient(ABC):
    @abstractmethod
    def build_request(
        self, messages: list[Message], model: str, temperature: float
    ) -> LLMRequest:
        """Build the provider-specific HTTP request descriptor."""

    @abstractmethod
    def parse_chunk(self, data: str) -> str | None:
        """Parse an SSE data: line. Return text token or None if no text in this chunk."""

    @abstractmethod
    def refresh_credentials(self) -> None:
        """Refresh token if expired. Mutates self in place."""

    def is_context_overflow(self, status: int, body: str) -> bool:
        """Override in subclasses with non-standard overflow signals."""
        return bool(_OVERFLOW_PATTERNS.search(body))

    def is_usage_limit(self, status: int, body: str) -> bool:
        """Check if the user has hit their plan quota/usage limits."""
        if status != 429:
            return False
        return (
            "usage_limit_reached" in body
            or "quota_exceeded" in body
            or "insufficient_quota" in body
        )

    async def stream_chat(
        self,
        messages: list[Message],
        model: str,
        temperature: float = 0.1,
    ) -> str:
        """
        Stream one chat turn to stdout. Returns full response text.

        Steps:
        1. refresh_credentials() — refresh if expired
        2. build_request() — provider-specific URL/headers/body
        3. _stream_with_retry() — POST with retry loop
        4. Parse SSE lines via parse_chunk()
        5. Print each token to stdout as it arrives
        6. Return joined response string
        """
        self.refresh_credentials()
        req = self.build_request(messages, model, temperature)
        return await self._stream_with_retry(req)

    async def _stream_with_retry(self, req: LLMRequest) -> str:
        last_exc: Exception | None = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                return await self._do_stream(req)
            except PermissionError:
                raise  # 401 — never retry auth failures
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                body = exc.response.text

                # Context overflow → fail immediately with a helpful message
                if self.is_context_overflow(status, body):
                    raise RuntimeError(
                        "Context length exceeded. Try shortening the conversation."
                    ) from exc

                # Plan/quota usage limit → fail immediately
                if self.is_usage_limit(status, body):
                    try:
                        data = json.loads(body)
                        # Extract reset time/message if available in OpenAI's format
                        if "error" in data and isinstance(data["error"], dict):
                            msg = data["error"].get(
                                "message", "The usage limit has been reached."
                            )
                            resets_in = data["error"].get("resets_in_seconds")
                            if resets_in:
                                raise RuntimeError(
                                    f"{msg} Resets in {resets_in // 3600}h {(resets_in % 3600) // 60}m."
                                )
                            raise RuntimeError(msg)
                    except json.JSONDecodeError:
                        pass
                    raise RuntimeError(
                        "Subscription or quota usage limit reached. Try again later."
                    ) from exc

                if status not in _RETRYABLE_STATUSES:
                    raise

                last_exc = exc
                delay = self._compute_retry_delay(exc.response, attempt)
                if delay > MAX_SERVER_DELAY:
                    raise RuntimeError(
                        f"Server requested {delay:.0f}s retry delay. Try again later."
                    ) from exc
                await asyncio.sleep(delay)
            except (httpx.TransportError, OSError) as exc:
                # Network-level errors — always retryable
                last_exc = exc
                await asyncio.sleep(BASE_RETRY_DELAY * (2**attempt))

        raise RuntimeError(
            f"Request failed after {MAX_RETRIES} retries. Last error: {repr(last_exc)}"
        ) from last_exc

    async def _do_stream(self, req: LLMRequest) -> str:
        parts: list[str] = []

        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST", req.url, json=req.body, headers=req.headers
            ) as response:
                if response.status_code == 401:
                    raise PermissionError(
                        "Authentication failed (401). Delete ~/.config/taui/config.toml "
                        "and re-run to log in again."
                    )
                if response.status_code >= 400:
                    # Must read the body before leaving the stream context,
                    # otherwise exc.response.text is unavailable to the retry handler.
                    await response.aread()
                    response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        text = self.parse_chunk(data)
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue  # skip malformed chunks
                    if text:
                        parts.append(text)
                        print(text, end="", flush=True)

        print()
        return "".join(parts)

    @staticmethod
    def _compute_retry_delay(response: httpx.Response, attempt: int) -> float:
        """
        Parse server-requested retry delay from headers/body. Falls back to exponential backoff.

        Checks in order:
        1. Retry-After header (seconds or HTTP date)
        2. x-ratelimit-reset header (Unix timestamp)
        3. x-ratelimit-reset-after header (seconds)
        4. Body: "Please retry in Ns" / "Please retry in Nms"
        5. Body: "retryDelay": "N.Ns"
        6. Exponential backoff: BASE_RETRY_DELAY * 2^attempt
        """
        import time

        # 1. Retry-After
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return float(retry_after) + 1.0
            except ValueError:
                pass

        # 2. x-ratelimit-reset (Unix timestamp)
        reset_ts = response.headers.get("x-ratelimit-reset")
        if reset_ts:
            try:
                return max(0, float(reset_ts) - time.time()) + 1.0
            except ValueError:
                pass

        # 3. x-ratelimit-reset-after (seconds)
        reset_after = response.headers.get("x-ratelimit-reset-after")
        if reset_after:
            try:
                return float(reset_after) + 1.0
            except ValueError:
                pass

        body = response.text

        # 4. "Please retry in 30s" / "Please retry in 500ms"
        m = re.search(r"retry in (\d+)(ms|s)", body, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if m.group(2) == "ms":
                return val / 1000 + 1.0
            return val + 1.0

        # 5. "retryDelay": "34.07s"
        m = re.search(r'"retryDelay":\s*"([\d.]+)s"', body)
        if m:
            return float(m.group(1)) + 1.0

        # 6. Exponential backoff
        return BASE_RETRY_DELAY * (2**attempt)
