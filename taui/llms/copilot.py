"""
Copilot LLM client — OpenAI /chat/completions wire format.
"""

from __future__ import annotations

import json
import logging
from typing import Any
import httpx

from taui.auth.copilot import (
    COPILOT_AGENT_HEADERS,
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


logger = logging.getLogger(__name__)


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
            "stream": True,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        _tool_names = (
            [t.get("function", {}).get("name", "?") for t in tools] if tools else []
        )
        logger.info(
            "Copilot API request: model=%s, %d messages, %d tools (%s)",
            model,
            len(messages),
            len(tools) if tools else 0,
            ", ".join(_tool_names[:8]),
        )

        # Use streaming so the Copilot proxy includes tool_calls in the response.
        # Non-streaming responses from the enterprise proxy strip tool_calls even
        # when finish_reason=tool_calls.
        text_parts: list[str] = []
        # tool_calls_map: index → {id, name, arguments_parts}
        tc_map: dict[int, dict[str, Any]] = {}
        finish_reason: str = ""
        reasoning_opaque: str = ""
        reasoning_text: str = ""

        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                json=body,
                headers={
                    "Authorization": f"Bearer {self.credentials.copilot_token}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    "X-Initiator": "user",
                    "Openai-Intent": "conversation-panel",
                    **COPILOT_AGENT_HEADERS,
                },
            ) as response:
                if response.status_code == 401:
                    raise PermissionError(
                        "Authentication failed (401). Delete ~/.config/taui/config.toml "
                        "and re-run to log in again."
                    )
                if not response.is_success:
                    body_text = (await response.aread()).decode(
                        "utf-8", errors="replace"
                    )
                    logger.error(
                        "Copilot API error status=%s model=%s body=%s",
                        response.status_code,
                        model,
                        body_text[:2000],
                    )
                    raise httpx.HTTPStatusError(
                        f"HTTP {response.status_code}: {body_text[:500]}",
                        request=response.request,
                        response=response,
                    )

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    if not isinstance(delta, dict):
                        continue

                    # Finish reason
                    fr = choices[0].get("finish_reason")
                    if fr:
                        finish_reason = fr

                    # Text content
                    content_delta = delta.get("content")
                    if isinstance(content_delta, str):
                        text_parts.append(content_delta)

                    # Reasoning
                    ro = delta.get("reasoning_opaque")
                    if isinstance(ro, str):
                        reasoning_opaque += ro
                    rt = delta.get("reasoning_text")
                    if isinstance(rt, str):
                        reasoning_text += rt

                    # Tool call deltas (OpenAI streaming format)
                    tc_deltas = delta.get("tool_calls")
                    if isinstance(tc_deltas, list):
                        for tc_delta in tc_deltas:
                            if not isinstance(tc_delta, dict):
                                continue
                            idx = tc_delta.get("index", 0)
                            if idx not in tc_map:
                                tc_map[idx] = {"id": "", "name": "", "args": ""}
                            entry = tc_map[idx]
                            if "id" in tc_delta and tc_delta["id"]:
                                entry["id"] = tc_delta["id"]
                            func = tc_delta.get("function", {})
                            if isinstance(func, dict):
                                if "name" in func and func["name"]:
                                    entry["name"] = func["name"]
                                if "arguments" in func and isinstance(
                                    func["arguments"], str
                                ):
                                    entry["args"] += func["arguments"]

        text = "".join(text_parts)

        # Build parsed tool calls from accumulated deltas
        parsed_calls: list[ProviderToolCall] = []
        for idx in sorted(tc_map.keys()):
            entry = tc_map[idx]
            call_id = entry.get("id", "")
            name = entry.get("name", "")
            args_raw = entry.get("args", "{}")
            if not call_id or not name:
                continue
            try:
                arguments = json.loads(args_raw) if args_raw else {}
                if not isinstance(arguments, dict):
                    arguments = {}
            except json.JSONDecodeError:
                arguments = {}
            parsed_calls.append(
                ProviderToolCall(call_id=call_id, name=name, arguments=arguments)
            )

        assistant_metadata: dict[str, Any] | None = None
        if reasoning_opaque:
            assistant_metadata = {"reasoning_opaque": reasoning_opaque}
            if reasoning_text:
                assistant_metadata["reasoning_text"] = reasoning_text

        logger.info(
            "Copilot API response: finish_reason=%s, has_tool_calls=%s",
            finish_reason,
            bool(parsed_calls),
        )
        if parsed_calls:
            logger.info(
                "Copilot API parsed %d tool call(s): %s",
                len(parsed_calls),
                [tc.name for tc in parsed_calls],
            )
        elif finish_reason == "tool_calls":
            logger.warning(
                "Copilot API: finish_reason=tool_calls but no tool calls were parsed "
                "(tc_map=%s, text=%r)",
                tc_map,
                text[:200],
            )

        return ProviderTurnResult(
            response_id=None,
            text=text,
            tool_calls=parsed_calls,
            assistant_metadata=assistant_metadata,
        )
