"""
Copilot LLM provider — OpenAI /chat/completions wire format via GitHub's proxy.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..auth.copilot import (
    COPILOT_AGENT_HEADERS,
    COPILOT_HEADERS,
    CopilotCredentials,
    ensure_valid_token,
    get_copilot_base_url,
)
from ..base import BaseLLMProvider
from ..types import (
    LLMRequest,
    ProviderCapabilities,
    ProviderTurnResult,
    ReasoningFormat,
    StreamEvent,
    ToolIdFormat,
    Usage,
)

logger = logging.getLogger(__name__)


class CopilotProvider(BaseLLMProvider):
    """GitHub Copilot provider using OpenAI Chat Completions format."""

    api_format = "chat_completions"

    def __init__(self, credentials: CopilotCredentials) -> None:
        self.credentials = credentials

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tools=True,
            supports_streaming=True,
            supports_reasoning=True,
            supports_images=True,
            supports_cache_control=False,
            supports_response_id=False,
            supports_developer_role=False,
            reasoning_format=ReasoningFormat.OPAQUE,
            tool_call_id_format=ToolIdFormat.OPENAI_CHAT,
            requires_streaming_for_tools=True,
            supports_parallel_tool_calls=True,
            supports_strict_tool_schema=False,
        )

    def build_request(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        *,
        tools: list[dict[str, Any]] | None = None,
        thinking_level: str | None = None,
        **kwargs: Any,
    ) -> LLMRequest:
        base_url = get_copilot_base_url(
            self.credentials.copilot_token,
            self.credentials.enterprise_domain,
        )
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        # Copilot accepts ``reasoning_effort`` on its OpenAI-compatible chat
        # completions endpoint for GPT-5 / Claude models. Mirrors opencode's
        # github-copilot variant payload (see tmp/opencode transform.ts).
        if thinking_level:
            body["reasoning_effort"] = thinking_level

        # Use agent headers when tool calling, standard headers otherwise
        extra_headers = COPILOT_AGENT_HEADERS if tools else COPILOT_HEADERS

        return LLMRequest(
            url=f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.credentials.copilot_token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "X-Initiator": "user",
                "Openai-Intent": "conversation-panel" if tools else "conversation-edits",
                **extra_headers,
            },
            body=body,
        )

    def parse_stream_event(self, data: str) -> StreamEvent | list[StreamEvent] | None:
        chunk = json.loads(data)

        choices = chunk.get("choices")
        if isinstance(choices, list) and choices:
            # Normal delta processing — handled below
            pass
        else:
            # No choices — check for token usage event (final SSE chunk)
            usage_data = chunk.get("usage")
            if isinstance(usage_data, dict):
                prompt_details = usage_data.get("prompt_tokens_details") or {}
                completion_details = usage_data.get("completion_tokens_details") or {}

                cache_read = 0
                if isinstance(prompt_details, dict):
                    cache_read = prompt_details.get("cached_tokens", 0)

                reasoning = 0
                if isinstance(completion_details, dict):
                    reasoning = completion_details.get("reasoning_tokens", 0)

                return StreamEvent.usage_event(
                    Usage(
                        input_tokens=usage_data.get("prompt_tokens", 0),
                        output_tokens=usage_data.get("completion_tokens", 0),
                        cache_read_tokens=cache_read,
                        reasoning_tokens=reasoning,
                    )
                )
            return None

        choice = choices[0]
        delta = choice.get("delta", {})
        if not isinstance(delta, dict):
            return None

        # Collect all events from this chunk — a single SSE delta can
        # carry reasoning_text, content, *and* tool_calls simultaneously.
        events: list[StreamEvent] = []

        # Text content
        content = delta.get("content")
        if isinstance(content, str) and content:
            events.append(StreamEvent.text_delta(content))

        # Reasoning text (visible to user)
        reasoning_text = delta.get("reasoning_text")
        if isinstance(reasoning_text, str) and reasoning_text:
            events.append(StreamEvent.reasoning_delta(reasoning_text))

        # Tool call deltas — handle every entry, not just the first
        tc_deltas = delta.get("tool_calls")
        if isinstance(tc_deltas, list):
            for tc in tc_deltas:
                if not isinstance(tc, dict):
                    continue
                idx = tc.get("index", 0)
                func = tc.get("function", {})

                # Start of a new tool call (has id and name)
                if tc.get("id") and isinstance(func, dict) and func.get("name"):
                    events.append(
                        StreamEvent.tool_call_start(
                            index=idx,
                            call_id=tc["id"],
                            name=func["name"],
                        )
                    )
                # Arguments delta
                elif isinstance(func, dict) and isinstance(func.get("arguments"), str):
                    events.append(StreamEvent.tool_call_delta(idx, func["arguments"]))

        if not events:
            return None
        return events[0] if len(events) == 1 else events

    def refresh_credentials(self) -> None:
        self.credentials = ensure_valid_token(self.credentials)

    async def create_turn(
        self,
        messages: list[dict[str, Any]],
        model: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.1,
        previous_response_id: str | None = None,
        thinking_level: str | None = None,
        **kwargs: Any,
    ) -> ProviderTurnResult:
        """
        Override to handle Copilot model name fallback.

        If the model name contains '/' (enterprise prefix like 'enterprise/claude-sonnet'),
        try with the full name first, then fall back to the stripped name.
        """
        self.refresh_credentials()

        candidates = [model]
        if "/" in model:
            stripped = model.split("/", 1)[-1]
            if stripped and stripped != model:
                candidates.append(stripped)

        last_exc: Exception | None = None
        for idx, candidate in enumerate(candidates):
            try:
                converted_tools = self.convert_tools(tools) if tools else None
                req = self.build_request(
                    messages,
                    candidate,
                    temperature,
                    tools=converted_tools,
                    thinking_level=thinking_level,
                )
                return await self._stream_turn_with_retry(req)
            except (httpx.HTTPStatusError, RuntimeError) as exc:
                last_exc = exc
                # Check for model_not_supported in the error message/body
                err_text = ""
                if isinstance(exc, httpx.HTTPStatusError):
                    err_text = exc.response.text
                else:
                    err_text = str(exc)
                if "model_not_supported" in err_text and idx < len(candidates) - 1:
                    logger.info(
                        "Model %r not supported, trying fallback %r",
                        candidate,
                        candidates[idx + 1],
                    )
                    continue
                raise

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Copilot request failed without a specific error.")
