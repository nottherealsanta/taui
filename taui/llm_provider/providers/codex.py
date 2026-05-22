"""
Codex LLM provider — OpenAI Responses API at chatgpt.com.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..auth.codex import CodexCredentials, ensure_valid_token
from ..base import BaseLLMProvider
from ..types import (
    LLMRequest,
    ProviderCapabilities,
    ProviderToolCall,
    ReasoningFormat,
    StreamEvent,
    ToolIdFormat,
    Usage,
)

logger = logging.getLogger(__name__)


class CodexProvider(BaseLLMProvider):
    """OpenAI Codex provider using the Responses API."""

    BASE_URL = "https://chatgpt.com/backend-api"
    api_format = "responses"

    def __init__(self, credentials: CodexCredentials) -> None:
        self.credentials = credentials

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tools=True,
            supports_streaming=True,
            supports_reasoning=True,
            supports_images=False,
            supports_cache_control=False,
            supports_response_id=True,
            supports_developer_role=False,
            reasoning_format=ReasoningFormat.ENCRYPTED,
            tool_call_id_format=ToolIdFormat.OPENAI_RESPONSES,
            requires_streaming_for_tools=False,
            supports_parallel_tool_calls=False,
            supports_strict_tool_schema=False,
        )

    def build_request(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        *,
        tools: list[dict[str, Any]] | None = None,
        previous_response_id: str | None = None,
        thinking_level: str | None = None,
        **kwargs: Any,
    ) -> LLMRequest:
        system, input_items = self._convert_messages(messages)
        body: dict[str, Any] = {
            "model": model,
            "stream": True,
            "store": False,
            "input": input_items,
            "instructions": system or "",
            "text": {"verbosity": "medium"},
            "tools": self._normalize_tools(tools or []),
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "include": ["reasoning.encrypted_content"],
        }
        if previous_response_id:
            body["previous_response_id"] = previous_response_id
        # OpenAI Responses API takes ``reasoning.effort`` (e.g. "minimal" /
        # "low" / "medium" / "high" / "xhigh" / "none") — supported set is
        # model-specific (see compute_variants for codex). Mirrors opencode's
        # openaiReasoningEfforts() variant payload.
        if thinking_level:
            body["reasoning"] = {"effort": thinking_level}

        return LLMRequest(
            url=f"{self.BASE_URL}/codex/responses",
            headers={
                "Authorization": f"Bearer {self.credentials.access_token}",
                "chatgpt-account-id": self.credentials.account_id,
                "OpenAI-Beta": "responses=experimental",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "originator": "taui",
                "User-Agent": "taui (darwin; arm64)",
            },
            body=body,
        )

    def parse_stream_event(self, data: str) -> StreamEvent | list[StreamEvent] | None:
        chunk = json.loads(data)
        event_type = chunk.get("type", "")

        if event_type == "response.output_text.delta":
            delta = chunk.get("delta")
            if isinstance(delta, str):
                return StreamEvent.text_delta(delta)
            return None

        if event_type == "response.output_item.done":
            item = chunk.get("item")
            call = self._parse_function_call_item(item)
            if call is not None:
                return StreamEvent.tool_call_done(call)
            return None

        if event_type == "response.completed":
            # Extract usage if available
            raw_response = chunk.get("response", {})
            usage_data = raw_response.get("usage", {})
            if usage_data:
                return StreamEvent.usage_event(
                    Usage(
                        input_tokens=usage_data.get("input_tokens", 0),
                        output_tokens=usage_data.get("output_tokens", 0),
                    )
                )
            return None

        if event_type == "error":
            err = chunk.get("error", {})
            if isinstance(err, dict):
                code = err.get("code", "")
                message = str(err.get("message") or code or "").strip()
                if code == "usage_limit_reached":
                    resets_at = err.get("resets_at", "unknown")
                    raise RuntimeError(f"Usage limit reached. Resets at {resets_at}.")
                raise RuntimeError(message or "Codex API returned an error event.")

        return None

    def refresh_credentials(self) -> None:
        self.credentials = ensure_valid_token(self.credentials)

    def _convert_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str | None, list[dict]]:
        """
        Extract system message -> top-level "instructions" field.
        Convert user/assistant messages to OpenAI Responses API format.
        """
        system = None
        items: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                system = content
            elif role == "user":
                user_content: list[dict[str, Any]] = []
                if isinstance(content, list):
                    # Already content blocks (multimodal from _build_llm_messages)
                    for block in content:
                        if isinstance(block, dict):
                            btype = block.get("type", "")
                            if btype == "text":
                                user_content.append(
                                    {"type": "input_text", "text": block.get("text", "")}
                                )
                            elif btype == "image_url":
                                url = block.get("image_url", {}).get("url", "")
                                if url:
                                    user_content.append(
                                        {"type": "input_image", "image_url": url}
                                    )
                else:
                    user_content.append({"type": "input_text", "text": content or ""})
                items.append({"role": "user", "content": user_content})
            elif role == "assistant":
                if content:
                    items.append(
                        {
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": content}],
                        }
                    )
                # Emit function_call items for tool calls
                for tc in msg.get("tool_calls", []):
                    fn = tc.get("function", {})
                    items.append(
                        {
                            "type": "function_call",
                            "call_id": tc.get("id", ""),
                            "name": fn.get("name", ""),
                            "arguments": fn.get("arguments", "{}"),
                        }
                    )
            elif role == "tool":
                # Tool results in Responses API format
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": msg.get("tool_call_id", ""),
                        "output": content or "",
                    }
                )
        return system, items

    @staticmethod
    def _normalize_tools(
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Convert Chat Completions tool format to Responses API format."""
        normalized: list[dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") != "function":
                normalized.append(tool)
                continue

            function_raw = tool.get("function")
            if isinstance(function_raw, dict):
                entry: dict[str, Any] = {"type": "function"}
                for key in ("name", "description", "parameters"):
                    value = function_raw.get(key)
                    if value is not None:
                        entry[key] = value
                normalized.append(entry)
                continue

            normalized.append(tool)
        return normalized

    @staticmethod
    def _parse_function_call_item(item: Any) -> ProviderToolCall | None:
        if not isinstance(item, dict) or item.get("type") != "function_call":
            return None

        raw_name = item.get("name")
        raw_call_id = item.get("call_id")
        raw_args = item.get("arguments", "{}")
        if not isinstance(raw_name, str) or not isinstance(raw_call_id, str):
            return None

        parsed_args: dict[str, Any]
        if isinstance(raw_args, str):
            try:
                decoded = json.loads(raw_args)
                parsed_args = decoded if isinstance(decoded, dict) else {}
            except json.JSONDecodeError:
                parsed_args = {}
        elif isinstance(raw_args, dict):
            parsed_args = raw_args
        else:
            parsed_args = {}

        return ProviderToolCall(
            call_id=raw_call_id, name=raw_name, arguments=parsed_args
        )
