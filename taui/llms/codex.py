"""
Codex LLM client — OpenAI Responses API at chatgpt.com.
"""

from __future__ import annotations

import json

from taui.auth.codex import CodexCredentials, ensure_valid_token
from taui.llms.base import BaseLLMClient, LLMRequest, Message


class CodexLLMClient(BaseLLMClient):
    BASE_URL = "https://chatgpt.com/backend-api"

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
