"""
Gemini CLI LLM client — Google Cloud Code Assist streaming API.
"""

from __future__ import annotations

import json

from taui.auth.gemini import GeminiCredentials, ensure_valid_token
from taui.llms.base import BaseLLMClient, LLMRequest, Message


class GeminiLLMClient(BaseLLMClient):
    BASE_URL = "https://cloudcode-pa.googleapis.com"

    def __init__(self, credentials: GeminiCredentials) -> None:
        self.credentials = credentials

    def build_request(
        self, messages: list[Message], model: str, temperature: float
    ) -> LLMRequest:
        system, contents = self._convert_messages(messages)
        body: dict = {
            "project": self.credentials.project_id,
            "model": model,
            "request": {
                "contents": contents,
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": 8192,
                },
            },
        }
        if system:
            body["request"]["systemInstruction"] = {"parts": [{"text": system}]}
        return LLMRequest(
            url=f"{self.BASE_URL}/v1internal:streamGenerateContent?alt=sse",
            headers={
                "Authorization": f"Bearer {self.credentials.access_token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "User-Agent": "google-cloud-sdk vscode_cloudshelleditor/0.1",
                "X-Goog-Api-Client": "gl-node/22.17.0",
                "Client-Metadata": '{"ideType":"IDE_UNSPECIFIED","platform":"PLATFORM_UNSPECIFIED","pluginType":"GEMINI"}',
            },
            body=body,
        )

    def parse_chunk(self, data: str) -> str | None:
        # {"response": {"candidates": [{"content": {"parts": [{"text": "..."}]}}]}}
        chunk = json.loads(data)
        candidates = chunk.get("response", {}).get("candidates") or []
        if not candidates:
            return None
        parts = candidates[0].get("content", {}).get("parts") or []
        # Skip thought=True parts (internal reasoning)
        texts = [p["text"] for p in parts if "text" in p and not p.get("thought")]
        return "".join(texts) if texts else None

    def refresh_credentials(self) -> None:
        self.credentials = ensure_valid_token(self.credentials)

    def _convert_messages(
        self, messages: list[Message]
    ) -> tuple[str | None, list[dict]]:
        """
        Extract system message -> returned as separate string for systemInstruction.
        Convert user/assistant messages -> Google GenAI Content[] format.
        "assistant" role -> "model"
        """
        system = None
        contents = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                system = content
            else:
                contents.append(
                    {
                        "role": "model" if role == "assistant" else "user",
                        "parts": [{"text": content}],
                    }
                )
        return system, contents
