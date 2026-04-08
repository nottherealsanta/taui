"""
LLMs package — LLM client registry and factory.
"""

from taui.llms.base import (
    BaseLLMClient,
    LLMRequest,
    Message,
    ProviderToolCall,
    ProviderTurnResult,
)
from taui.llms.copilot import CopilotLLMClient
from taui.llms.gemini import GeminiLLMClient
from taui.llms.antigravity import AntigravityLLMClient
from taui.llms.codex import CodexLLMClient

DEFAULT_MODELS: dict[str, str] = {
    "copilot": "claude-sonnet-4.6",
}


def get_llm_client(provider: str, credentials) -> BaseLLMClient:
    match provider:
        case "copilot":
            return CopilotLLMClient(credentials)
        case "gemini":
            return GeminiLLMClient(credentials)
        case "antigravity":
            return AntigravityLLMClient(credentials)
        case "codex":
            return CodexLLMClient(credentials)
        case _:
            raise ValueError(f"Unknown provider: {provider!r}")


__all__ = [
    "get_llm_client",
    "DEFAULT_MODELS",
    "BaseLLMClient",
    "LLMRequest",
    "Message",
    "ProviderToolCall",
    "ProviderTurnResult",
    "CopilotLLMClient",
    "GeminiLLMClient",
    "AntigravityLLMClient",
    "CodexLLMClient",
]
