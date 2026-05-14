"""
Abstract base class for all LLM providers.

Subclasses implement:
  - build_request()          — provider-specific HTTP request
  - parse_stream_event()     — parse one SSE event into a StreamEvent
  - refresh_credentials()    — handle token refresh
  - convert_tools()          — convert tool schemas to provider format
  - convert_messages()       — convert message history to provider format

The base class owns:
  - SSE streaming loop
  - Retry logic with exponential backoff + server-requested delays
  - Error classification (overflow, rate limit, auth, usage limit)
  - Streaming tool call accumulation (Chat Completions format)
  - Credential refresh lifecycle
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx

from .errors import (
    AuthExpiredError,
    ContextOverflowError,
    ProviderError,
    QuotaExceededError,
    TransientProviderError,
)
from .types import (
    ApiFormat,
    LLMRequest,
    ProviderCapabilities,
    ProviderToolCall,
    ProviderTurnResult,
    StreamEvent,
    Usage,
)

logger = logging.getLogger(__name__)

# ── Retry config ───────────────────────────────────────────────────────────────

MAX_RETRIES = 3
BASE_RETRY_DELAY = 1.0  # seconds
MAX_SERVER_DELAY = 60.0  # cap on server-requested delay

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
    r"|token limit exceeded"
    r"|model_context_window_exceeded",
    re.IGNORECASE,
)

# ── Usage limit detection ──────────────────────────────────────────────────────

_USAGE_LIMIT_PATTERNS = re.compile(
    r"usage_limit_reached"
    r"|quota_exceeded"
    r"|insufficient_quota"
    r"|billing_hard_limit_reached"
    r"|rate_limit_exceeded.*plan",
    re.IGNORECASE,
)

Message = dict[str, Any]
ToolSchema = dict[str, Any]


# ── Base class ─────────────────────────────────────────────────────────────────


class BaseLLMProvider(ABC):
    """
    Abstract base for all LLM providers.

    The provider layer sits between the agent loop and the HTTP APIs.
    Each provider converts its wire format into the unified types
    (StreamEvent, ProviderTurnResult). The base class handles retry,
    streaming, and error classification.
    """

    api_format: ApiFormat = "chat_completions"

    # Optional streaming callback — set by agent loop for live output
    on_text_delta: Callable[[str], Any] | None = None
    on_reasoning_delta: Callable[[str], Any] | None = None

    # ── Abstract interface ─────────────────────────────────────────

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Declare what this provider supports."""
        ...

    @abstractmethod
    def build_request(
        self,
        messages: list[Message],
        model: str,
        temperature: float,
        *,
        tools: list[ToolSchema] | None = None,
        **kwargs: Any,
    ) -> LLMRequest:
        """Build the provider-specific HTTP request descriptor."""
        ...

    @abstractmethod
    def parse_stream_event(self, data: str) -> StreamEvent | None:
        """
        Parse one SSE `data:` line into a StreamEvent.

        Return None if this chunk contains no actionable event
        (e.g., a keepalive or metadata-only chunk).
        """
        ...

    @abstractmethod
    def refresh_credentials(self) -> None:
        """Refresh token if expired. Mutates self in place."""
        ...

    def convert_tools(self, tools: list[ToolSchema]) -> list[dict[str, Any]]:
        """
        Convert tool schemas to provider-specific format.

        Default: pass through (works for Chat Completions format).
        Override for Responses API, Anthropic, etc.
        """
        return tools

    def convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """
        Convert messages to provider-specific format.

        Default: pass through (works for Chat Completions format).
        Override for Responses API (input items), Anthropic (content blocks), etc.
        """
        return messages

    # ── Error classification (overridable) ─────────────────────────

    def is_context_overflow(self, status: int, body: str) -> bool:
        """Check if the error indicates context length was exceeded."""
        return bool(_OVERFLOW_PATTERNS.search(body))

    def is_usage_limit(self, status: int, body: str) -> bool:
        """Check if the user has hit their plan quota/usage limits."""
        if status != 429:
            return False
        return bool(_USAGE_LIMIT_PATTERNS.search(body))

    def is_retryable(self, status: int, body: str) -> bool:
        """Check if the error is retryable (rate limit, server error)."""
        if status in _RETRYABLE_STATUSES:
            return True
        return bool(_RETRYABLE_PATTERNS.search(body))

    # ── High-level API ─────────────────────────────────────────────

    async def create_turn(
        self,
        messages: list[Message],
        model: str,
        *,
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.1,
        previous_response_id: str | None = None,
        thinking_level: str | None = None,
        **kwargs: Any,
    ) -> ProviderTurnResult:
        """
        Execute one complete LLM turn.

        This is the primary entry point for the agent loop. It:
        1. Refreshes credentials
        2. Builds the request
        3. Streams the response with retry
        4. Accumulates text, tool calls, reasoning, and usage
        5. Returns a ProviderTurnResult

        Subclasses can override this entirely for providers that need
        custom turn logic (e.g., Codex with previous_response_id).
        """
        self.refresh_credentials()

        converted_tools = self.convert_tools(tools) if tools else None
        req = self.build_request(
            messages,
            model,
            temperature,
            tools=converted_tools,
            previous_response_id=previous_response_id,
            thinking_level=thinking_level,
            **kwargs,
        )

        return await self._stream_turn_with_retry(req)

    async def stream_text(
        self,
        messages: list[Message],
        model: str,
        temperature: float = 0.1,
    ) -> AsyncIterator[StreamEvent]:
        """
        Stream text-only response as StreamEvent objects.

        Simpler than create_turn() — no tool accumulation, just text deltas
        and a done event. Used for simple text completion in the CLI.
        """
        self.refresh_credentials()
        req = self.build_request(messages, model, temperature)

        async for event in self._do_stream(req):
            yield event

    # ── Streaming with retry ───────────────────────────────────────

    async def _stream_turn_with_retry(self, req: LLMRequest) -> ProviderTurnResult:
        """Execute a streaming turn with retry logic."""
        last_exc: Exception | None = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                return await self._accumulate_turn(req)
            except AuthExpiredError:
                raise  # 401 — never retry auth failures
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                body = exc.response.text

                # Context overflow → fail immediately
                if self.is_context_overflow(status, body):
                    raise ContextOverflowError(
                        "Context length exceeded. Try shortening the conversation.",
                        status_code=status,
                        body=body,
                    ) from exc

                # Usage limit → fail immediately with reset info
                if self.is_usage_limit(status, body):
                    msg, resets_in = self._extract_usage_limit_info(body)
                    raise QuotaExceededError(
                        msg, status_code=status, body=body, resets_in_seconds=resets_in
                    ) from exc

                # Not retryable → raise with body for debugging
                if not self.is_retryable(status, body):
                    raise ProviderError(
                        f"HTTP {status}: {body[:1000]}", status_code=status, body=body
                    ) from exc

                last_exc = exc
                delay = self._compute_retry_delay(exc.response, attempt)
                if delay > MAX_SERVER_DELAY:
                    raise TransientProviderError(
                        f"Server requested {delay:.0f}s retry delay. Try again later.",
                        status_code=status,
                        body=body,
                        retry_after=delay,
                    ) from exc

                logger.info(
                    "Retrying after HTTP %s (attempt %s/%s, delay %.1fs)",
                    status,
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)

            except (httpx.TransportError, OSError) as exc:
                last_exc = exc
                delay = BASE_RETRY_DELAY * (2**attempt)
                logger.info(
                    "Retrying after %s (attempt %s/%s, delay %.1fs)",
                    type(exc).__name__,
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)

        raise TransientProviderError(
            f"Request failed after {MAX_RETRIES} retries: {repr(last_exc)}",
            retry_after=None,
        ) from last_exc

    async def _accumulate_turn(self, req: LLMRequest) -> ProviderTurnResult:
        """Stream one turn, accumulating text, tool calls, reasoning, and usage."""
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: dict[int, _ToolCallAccumulator] = {}
        completed_tool_calls: list[ProviderToolCall] = []
        usage: Usage | None = None
        response_id: str | None = None
        stop_reason = "stop"

        async for event in self._do_stream(req):
            match event.type:
                case "text_delta":
                    if event.delta:
                        text_parts.append(event.delta)
                        if self.on_text_delta:
                            self.on_text_delta(event.delta)

                case "reasoning_delta":
                    if event.reasoning_text:
                        reasoning_parts.append(event.reasoning_text)
                        if self.on_reasoning_delta:
                            self.on_reasoning_delta(event.reasoning_text)

                case "tool_call_start":
                    if event.tool_call_index is not None and event.tool_call:
                        tc = event.tool_call
                        tool_calls[event.tool_call_index] = _ToolCallAccumulator(
                            call_id=tc.call_id,
                            name=tc.name,
                            arguments_json="",
                        )

                case "tool_call_delta":
                    if event.tool_call_index is not None and event.delta:
                        acc = tool_calls.get(event.tool_call_index)
                        if acc:
                            acc.arguments_json += event.delta

                case "tool_call_done":
                    if event.tool_call:
                        completed_tool_calls.append(event.tool_call)
                        stop_reason = "tool_use"

                case "usage":
                    if event.usage:
                        usage = event.usage

                case "done":
                    if event.usage:
                        usage = event.usage

                case "error":
                    raise RuntimeError(event.error_message or "Provider returned an error")

        # Finalize streaming tool calls (Chat Completions format)
        for idx in sorted(tool_calls):
            acc = tool_calls[idx]
            try:
                args = json.loads(acc.arguments_json) if acc.arguments_json else {}
            except json.JSONDecodeError:
                args = {}
            completed_tool_calls.append(
                ProviderToolCall(call_id=acc.call_id, name=acc.name, arguments=args)
            )

        if completed_tool_calls:
            stop_reason = "tool_use"

        # Build metadata
        metadata: dict[str, Any] = {}
        if reasoning_parts:
            metadata["reasoning_text"] = "".join(reasoning_parts)
        if usage:
            metadata["input_tokens"] = usage.input_tokens
            metadata["output_tokens"] = usage.output_tokens

        return ProviderTurnResult(
            response_id=response_id,
            text="".join(text_parts),
            tool_calls=completed_tool_calls,
            usage=usage,
            assistant_metadata=metadata if metadata else None,
            stop_reason=stop_reason,
        )

    async def _do_stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        """
        Open an HTTP stream and yield StreamEvents.

        Handles SSE parsing: reads `data:` lines, stops on `[DONE]`.
        Each data line is passed to parse_stream_event() for provider-
        specific parsing.
        """
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST", req.url, json=req.body, headers=req.headers
            ) as response:
                # Auth failure
                if response.status_code == 401:
                    raise AuthExpiredError(
                        "Authentication failed (401). Delete ~/.config/taui/config.toml "
                        "and re-run to log in again.",
                        status_code=401,
                    )

                # HTTP error — read body for error classification
                if response.status_code >= 400:
                    await response.aread()
                    response.raise_for_status()

                # SSE parsing loop
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue

                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break

                    try:
                        event = self.parse_stream_event(data)
                    except (json.JSONDecodeError, KeyError, IndexError):
                        logger.debug("Skipping malformed stream chunk")
                        continue

                    if event is not None:
                        yield event

    # ── Retry delay computation ────────────────────────────────────

    @staticmethod
    def _compute_retry_delay(response: httpx.Response, attempt: int) -> float:
        """
        Parse server-requested retry delay from headers/body.
        Falls back to exponential backoff.

        Checks in order:
        1. Retry-After header (seconds)
        2. x-ratelimit-reset header (Unix timestamp)
        3. x-ratelimit-reset-after header (seconds)
        4. Body: "retry in Ns" / "retryDelay: Ns"
        5. Exponential backoff
        """
        # 1. Retry-After header
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

        # 4. Body patterns
        try:
            body = response.text
            match = re.search(r"retry\s+in\s+(\d+\.?\d*)\s*(ms|s)", body, re.IGNORECASE)
            if match:
                val = float(match.group(1))
                unit = match.group(2).lower()
                return (val / 1000 if unit == "ms" else val) + 1.0

            match = re.search(r'"retryDelay"\s*:\s*"(\d+\.?\d*)s"', body)
            if match:
                return float(match.group(1)) + 1.0
        except Exception:
            pass

        # 5. Exponential backoff
        return BASE_RETRY_DELAY * (2**attempt)

    @staticmethod
    def _extract_usage_limit_info(body: str) -> tuple[str, int | None]:
        """Extract a human-readable usage limit message and reset seconds from the response body."""
        try:
            data = json.loads(body)
            if "error" in data and isinstance(data["error"], dict):
                msg = data["error"].get("message", "Usage limit reached.")
                resets_in: int | None = data["error"].get("resets_in_seconds")
                if resets_in:
                    hours = resets_in // 3600
                    minutes = (resets_in % 3600) // 60
                    return f"{msg} Resets in {hours}h {minutes}m.", resets_in
                return msg, None
        except (json.JSONDecodeError, TypeError):
            pass
        return "Subscription or quota usage limit reached. Try again later.", None

    @staticmethod
    def _extract_usage_limit_message(body: str) -> str:
        """Extract a human-readable usage limit message from the response body."""
        msg, _ = BaseLLMProvider._extract_usage_limit_info(body)
        return msg


# ── Internal helpers ───────────────────────────────────────────────────────────


class _ToolCallAccumulator:
    """Accumulates streaming tool call chunks (Chat Completions format)."""

    __slots__ = ("call_id", "name", "arguments_json")

    def __init__(self, call_id: str, name: str, arguments_json: str = ""):
        self.call_id = call_id
        self.name = name
        self.arguments_json = arguments_json
