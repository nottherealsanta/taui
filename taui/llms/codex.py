"""
Codex LLM client — OpenAI Responses API at chatgpt.com.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from taui.auth.codex import CodexCredentials, ensure_valid_token
from taui.llms.base import (
    BaseLLMClient,
    LLMRequest,
    Message,
    ProviderToolCall,
    ProviderTurnResult,
)


class CodexLLMClient(BaseLLMClient):
    BASE_URL = "https://chatgpt.com/backend-api"
    supports_tools: bool = True
    tool_call_mode = "responses"

    def __init__(self, credentials: CodexCredentials) -> None:
        self.credentials = credentials

    def build_request(
        self, messages: list[Message], model: str, temperature: float
    ) -> LLMRequest:
        system, input_items = self._convert_messages(messages)
        body: dict = {
            "model": model,
            "stream": True,
            "store": False,
            "input": input_items,
            # instructions must always be present (empty string if no system prompt)
            "instructions": system or "",
            "text": {"verbosity": "medium"},
            # required fields per the Responses API wire format
            "tools": [],
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "include": ["reasoning.encrypted_content"],
        }
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

    def parse_chunk(self, data: str) -> str | None:
        chunk = json.loads(data)
        event_type = chunk.get("type", "")
        if event_type == "response.output_text.delta":
            return chunk.get("delta", "")
        # Codex-specific: usage_limit_reached means subscription quota hit
        if event_type == "error":
            err = chunk.get("error", {})
            if err.get("code") == "usage_limit_reached":
                resets_at = err.get("resets_at", "unknown")
                raise RuntimeError(f"Usage limit reached. Resets at {resets_at}.")
        return None

    def refresh_credentials(self) -> None:
        self.credentials = ensure_valid_token(self.credentials)

    async def create_response(
        self,
        messages: list[Message],
        model: str,
        *,
        tools: list[dict[str, object]] | None = None,
        input_items: list[dict[str, object]] | None = None,
        previous_response_id: str | None = None,
        temperature: float = 0.1,
    ) -> ProviderTurnResult:
        del temperature
        self.refresh_credentials()
        system, converted_input = self._convert_messages(messages)
        body: dict[str, object] = {
            "model": model,
            "stream": True,
            "store": False,
            "input": input_items if input_items is not None else converted_input,
            "instructions": system or "",
            "text": {"verbosity": "medium"},
            "tools": _normalize_tools_for_responses(tools or []),
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "include": ["reasoning.encrypted_content"],
        }
        if previous_response_id:
            body["previous_response_id"] = previous_response_id

        text_parts: list[str] = []
        tool_calls: dict[str, ProviderToolCall] = {}
        response_id = ""

        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{self.BASE_URL}/codex/responses",
                json=body,
                headers={
                    "Authorization": f"Bearer {self.credentials.access_token}",
                    "chatgpt-account-id": self.credentials.account_id,
                    "OpenAI-Beta": "responses=experimental",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    "originator": "taui",
                    "User-Agent": "taui (darwin; arm64)",
                },
            ) as response:
                if response.status_code == 401:
                    raise PermissionError(
                        "Authentication failed (401). Delete ~/.config/taui/config.toml "
                        "and re-run to log in again."
                    )
                if response.status_code >= 400:
                    detail = (await response.aread()).decode("utf-8", errors="replace").strip()
                    if detail:
                        raise RuntimeError(
                            f"Codex API request failed ({response.status_code}): {detail}"
                        )
                    response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    event_type = chunk.get("type", "")
                    if event_type == "response.output_text.delta":
                        delta = chunk.get("delta")
                        if isinstance(delta, str):
                            text_parts.append(delta)
                        continue
                    if event_type == "response.output_item.done":
                        item = chunk.get("item")
                        call = _parse_function_call_item(item)
                        if call is not None:
                            tool_calls[call.call_id] = call
                        continue
                    if event_type == "response.completed":
                        raw_response = chunk.get("response")
                        if isinstance(raw_response, dict):
                            parsed = _parse_response_payload(raw_response)
                            if parsed.response_id:
                                response_id = parsed.response_id
                            if not text_parts and parsed.text:
                                text_parts.append(parsed.text)
                            for call in parsed.tool_calls:
                                tool_calls[call.call_id] = call
                        continue
                    if event_type == "error":
                        err = chunk.get("error", {})
                        message = ""
                        if isinstance(err, dict):
                            message = str(err.get("message") or err.get("code") or "").strip()
                        raise RuntimeError(message or "Codex API returned an error event.")

        return ProviderTurnResult(
            response_id=response_id,
            text="".join(text_parts),
            tool_calls=list(tool_calls.values()),
        )

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
        return await self.create_response(
            messages=messages,
            model=model,
            tools=tools,
            input_items=input_items,
            previous_response_id=previous_response_id,
            temperature=temperature,
        )

    def _convert_messages(
        self, messages: list[Message]
    ) -> tuple[str | None, list[dict]]:
        """
        Extract system message -> top-level "instructions" field.
        Convert user/assistant messages to OpenAI Responses API format.
        """
        system = None
        items = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                system = content
            elif role == "user":
                items.append(
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": content}],
                    }
                )
            elif role == "assistant":
                items.append(
                    {
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": content}],
                    }
                )
        return system, items


def _parse_response_payload(payload: dict[str, Any]) -> ProviderTurnResult:
    response_id_raw = payload.get("id")
    response_id = str(response_id_raw) if response_id_raw is not None else ""

    text_parts: list[str] = []
    tool_calls: list[ProviderToolCall] = []
    output = payload.get("output")
    if not isinstance(output, list):
        return ProviderTurnResult(response_id=response_id, text="", tool_calls=[])

    for item in output:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "message":
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                part_type = part.get("type")
                if part_type in {"output_text", "text"} and isinstance(
                    part.get("text"), str
                ):
                    text_parts.append(part["text"])
        if item_type == "function_call":
            raw_name = item.get("name")
            raw_call_id = item.get("call_id")
            raw_args = item.get("arguments", "{}")
            if not isinstance(raw_name, str) or not isinstance(raw_call_id, str):
                continue
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
            tool_calls.append(
                ProviderToolCall(
                    call_id=raw_call_id, name=raw_name, arguments=parsed_args
                )
            )

    return ProviderTurnResult(
        response_id=response_id,
        text="".join(text_parts),
        tool_calls=tool_calls,
    )


def _normalize_tools_for_responses(
    tools: list[dict[str, object]],
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") != "function":
            normalized.append(tool)
            continue

        function_raw = tool.get("function")
        if isinstance(function_raw, dict):
            entry: dict[str, object] = {"type": "function"}
            for key in ("name", "description", "parameters"):
                value = function_raw.get(key)
                if value is not None:
                    entry[key] = value
            normalized.append(entry)
            continue

        normalized.append(tool)
    return normalized


def _parse_function_call_item(item: object) -> ProviderToolCall | None:
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
    return ProviderToolCall(call_id=raw_call_id, name=raw_name, arguments=parsed_args)
