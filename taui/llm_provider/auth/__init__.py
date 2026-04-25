"""
Auth package — provider credential registry.

Re-exports credential types and provides get_credentials() factory.
"""

from .copilot import CopilotCredentials, get_copilot_credentials
from .codex import CodexCredentials, get_codex_credentials

PROVIDER_NAMES: dict[str, str] = {
    "copilot": "GitHub Copilot",
    "codex": "OpenAI Codex (ChatGPT Plus/Pro)",
}


def get_credentials(provider: str):
    """Return credentials for the given provider name. Triggers interactive login if needed."""
    match provider:
        case "copilot":
            return get_copilot_credentials()
        case "codex":
            return get_codex_credentials()
        case _:
            raise ValueError(f"Unknown provider: {provider!r}")


__all__ = [
    "get_credentials",
    "PROVIDER_NAMES",
    "CopilotCredentials",
    "CodexCredentials",
    "get_copilot_credentials",
    "get_codex_credentials",
]
