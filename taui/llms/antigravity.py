"""
Antigravity LLM client — subclass of GeminiLLMClient.

Differences from plain Gemini:
- Different base URL (daily sandbox endpoint)
- Different User-Agent (antigravity/<version> darwin/arm64)
- Different X-Goog-Api-Client header
- Injects a fixed system instruction before any user-provided system prompt
"""

from __future__ import annotations

import json
import os

from taui.auth.antigravity import AntigravityCredentials, ensure_valid_token
from taui.llms.base import LLMRequest, Message
from taui.llms.gemini import GeminiLLMClient

# The fixed system instruction Antigravity prepends to every request.
_SYSTEM_INSTRUCTION = (
    "You are Antigravity, a powerful agentic AI coding assistant designed by the "
    "Google Deepmind team working on Advanced Agentic Coding. "
    "You are pair programming with a USER to solve their coding task. "
    "The task may require creating a new codebase, modifying or debugging an existing "
    "codebase, or simply answering a question. "
    "**Absolute paths only** **Proactiveness**"
)

_DEFAULT_VERSION = "1.15.8"


def _agent_version() -> str:
    return os.environ.get("PI_AI_ANTIGRAVITY_VERSION", _DEFAULT_VERSION)


class AntigravityLLMClient(GeminiLLMClient):
    """Subclass of GeminiLLMClient with Antigravity-specific headers and system prompt."""

    BASE_URL = "https://daily-cloudcode-pa.sandbox.googleapis.com"

    def __init__(self, credentials: AntigravityCredentials) -> None:
        self.credentials = credentials  # type: ignore[assignment]

    def build_request(
        self, messages: list[Message], model: str, temperature: float
    ) -> LLMRequest:
        system, contents = self._convert_messages(messages)

        # Prepend the fixed Antigravity system instruction.
        if system:
            combined_system = _SYSTEM_INSTRUCTION + "\n" + system
        else:
            combined_system = _SYSTEM_INSTRUCTION

        body: dict = {
            "project": self.credentials.project_id,
            "model": model,
            "request": {
                "contents": contents,
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": 8192,
                },
                "systemInstruction": {"parts": [{"text": combined_system}]},
            },
        }

        version = _agent_version()
        return LLMRequest(
            url=f"{self.BASE_URL}/v1internal:streamGenerateContent?alt=sse",
            headers={
                "Authorization": f"Bearer {self.credentials.access_token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "User-Agent": f"antigravity/{version} darwin/arm64",
                "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
                "Client-Metadata": json.dumps(
                    {
                        "ideType": "IDE_UNSPECIFIED",
                        "platform": "PLATFORM_UNSPECIFIED",
                        "pluginType": "GEMINI",
                    }
                ),
            },
            body=body,
        )

    def refresh_credentials(self) -> None:
        self.credentials = ensure_valid_token(self.credentials)  # type: ignore[arg-type]
