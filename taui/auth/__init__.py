"""
Auth package — provider credential registry.

Re-exports all credential types and provides the get_credentials() factory.
"""

from taui.auth.copilot import CopilotCredentials, get_copilot_credentials
from taui.auth.gemini import GeminiCredentials, get_gemini_credentials
from taui.auth.antigravity import AntigravityCredentials, get_antigravity_credentials
from taui.auth.codex import CodexCredentials, get_codex_credentials

PROVIDER_NAMES: dict[str, str] = {
    "copilot": "GitHub Copilot",
    "gemini": "Google Gemini CLI (Cloud Code Assist)",
    "antigravity": "Google Antigravity",
    "codex": "OpenAI Codex (ChatGPT Plus/Pro)",
}


def get_credentials(provider: str):
    """Return credentials for the given provider name. Triggers interactive login if needed."""
    match provider:
        case "copilot":
            return get_copilot_credentials()
        case "gemini":
            return get_gemini_credentials()
        case "antigravity":
            return get_antigravity_credentials()
        case "codex":
            return get_codex_credentials()
        case _:
            raise ValueError(f"Unknown provider: {provider!r}")


__all__ = [
    "get_credentials",
    "PROVIDER_NAMES",
    "CopilotCredentials",
    "GeminiCredentials",
    "AntigravityCredentials",
    "CodexCredentials",
]
