"""
Copilot LLM client — OpenAI /chat/completions wire format.
"""

from __future__ import annotations

import json

from taui.auth.copilot import (
    COPILOT_HEADERS,
    CopilotCredentials,
    ensure_valid_token,
    get_copilot_base_url,
)
from taui.llms.base import BaseLLMClient, LLMRequest, Message


class CopilotLLMClient(BaseLLMClient):
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
                "model": model.split("/", 1)[-1],  # strip "github-copilot/" prefix
                "messages": messages,
                "stream": True,
                "temperature": temperature,
            },
        )

    def parse_chunk(self, data: str) -> str | None:
        chunk = json.loads(data)
        choices = chunk.get("choices") or []
        if not choices:
            return None
        return choices[0].get("delta", {}).get("content")

    def refresh_credentials(self) -> None:
        self.credentials = ensure_valid_token(self.credentials)
