"""
Copilot LLM client — OpenAI /chat/completions wire format.
"""

from __future__ import annotations

import json
from typing import Any
import httpx

from taui.auth.copilot import (
    COPILOT_HEADERS,
    CopilotCredentials,
    ensure_valid_token,
    get_copilot_base_url,
)
from taui.llms.base import (
    BaseLLMClient,
    LLMRequest,
    Message,
    ProviderToolCall,
    ProviderTurnResult,
)


class CopilotLLMClient(BaseLLMClient):
    supports_tools: bool = True
    tool_call_mode = "chat"

    def __init__(self, credentials: CopilotCredentials) -> None:
        self.credentials = credentials

    def build_request(
        self, messages: list[Message], model: str, temperature: float
    ) -> LLMRequest:
        base_url = get_copilot_base_url(
            self.credentials.copilot_token,
            self.credentials.enterprise_domain,
        )
        return LLMRequest(
            url=f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.credentials.copilot_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Initiator": "user",
                "Openai-Intent": "conversation-edits",
                **COPILOT_HEADERS,
            },
            body={
                "model": model,
                "messages": messages,
                "stream": True,
                "temperature": temperature,
            },
        )

    async def stream_chat(
        self,
        messages: list[Message],
        model: str,
        temperature: float = 0.1,
    ) -> str:
        candidates = [model]
        if "/" in model:
            stripped = model.split("/", 1)[-1]
            if stripped and stripped != model:
                candidates.append(stripped)

        last_exc: Exception | None = None
        for idx, candidate in enumerate(candidates):
            try:
                return await super().stream_chat(messages, candidate, temperature)
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                body = exc.response.text
                is_model_error = (
                    exc.response.status_code == 400 and "model_not_supported" in body
                )
                if is_model_error and idx < len(candidates) - 1:
                    continue
                raise

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Copilot request failed without a specific error.")

    def parse_chunk(self, data: str) -> str | None:
        chunk = json.loads(data)
        choices = chunk.get("choices") or []
        if not choices:
            return None
        return choices[0].get("delta", {}).get("content")

    def refresh_credentials(self) -> None:
        self.credentials = ensure_valid_token(self.credentials)

    async def create_turn(
        self,
        messages: list[Message],
        model: str,
        *,
        tools: list[dict[str, object]] | None = None,
        input_items: list[dict[str, object]] | None = None,
        previous_response_id: str | None = None,
        temperature: float = 0.1,
    ) -> ProviderTurnResult:
        del input_items, previous_response_id
        self.refresh_credentials()

        candidates = [model]
        if "/" in model:
            stripped = model.split("/", 1)[-1]
            if stripped and stripped != model:
                candidates.append(stripped)

        last_exc: Exception | None = None
        for idx, candidate in enumerate(candidates):
            try:
                return await self._create_turn_once(
                    messages=messages,
                    model=candidate,
                    tools=tools or [],
                    temperature=temperature,
                )
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                body = exc.response.text
                is_model_error = (
                    exc.response.status_code == 400 and "model_not_supported" in body
                )
                if is_model_error and idx < len(candidates) - 1:
                    continue
                raise

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Copilot request failed without a specific error.")

    async def _create_turn_once(
        self,
        *,
        messages: list[Message],
        model: str,
        tools: list[dict[str, object]],
        temperature: float,
    ) -> ProviderTurnResult:
        base_url = get_copilot_base_url(
            self.credentials.copilot_token,
            self.credentials.enterprise_domain,
        )
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                json=body,
                headers={
                    "Authorization": f"Bearer {self.credentials.copilot_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "X-Initiator": "user",
                    "Openai-Intent": "conversation-edits",
                    **COPILOT_HEADERS,
                },
            )
        if response.status_code == 401:
            raise PermissionError(
                "Authentication failed (401). Delete ~/.config/taui/config.toml "
                "and re-run to log in again."
            )
        if not response.is_success:
            import logging as _logging

            _logging.getLogger(__name__).error(
                "Copilot API error status=%s model=%s body=%s",
                response.status_code,
                model,
                response.text[:2000],
            )
            # Include the API error body in the exception so callers can see it
            raise httpx.HTTPStatusError(
                f"HTTP {response.status_code}: {response.text[:500]}",
                request=response.request,
                response=response,
            )

        payload = response.json()
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ProviderTurnResult(
                response_id=None,
                text="",
                tool_calls=[],
                assistant_metadata=None,
            )

        message = choices[0].get("message")
        if not isinstance(message, dict):
            return ProviderTurnResult(
                response_id=None,
                text="",
                tool_calls=[],
                assistant_metadata=None,
            )

        content = message.get("content")
        text = content if isinstance(content, str) else ""
        reasoning_opaque = message.get("reasoning_opaque")
        reasoning_text = message.get("reasoning_text")
        assistant_metadata: dict[str, Any] | None = None
        if isinstance(reasoning_opaque, str) and reasoning_opaque:
            assistant_metadata = {"reasoning_opaque": reasoning_opaque}
            if isinstance(reasoning_text, str) and reasoning_text:
                assistant_metadata["reasoning_text"] = reasoning_text

        parsed_calls: list[ProviderToolCall] = []
        raw_tool_calls = message.get("tool_calls")
        if isinstance(raw_tool_calls, list):
            for item in raw_tool_calls:
                if not isinstance(item, dict):
                    continue
                call_id = item.get("id")
                function = item.get("function")
                if not isinstance(call_id, str) or not isinstance(function, dict):
                    continue
                name = function.get("name")
                arguments_raw = function.get("arguments", "{}")
                if not isinstance(name, str):
                    continue
                arguments: dict[str, Any] = {}
                if isinstance(arguments_raw, str):
                    try:
                        decoded = json.loads(arguments_raw)
                        if isinstance(decoded, dict):
                            arguments = decoded
                    except json.JSONDecodeError:
                        arguments = {}
                elif isinstance(arguments_raw, dict):
                    arguments = arguments_raw

                parsed_calls.append(
                    ProviderToolCall(call_id=call_id, name=name, arguments=arguments)
                )

        return ProviderTurnResult(
            response_id=None,
            text=text,
            tool_calls=parsed_calls,
            assistant_metadata=assistant_metadata,
        )
