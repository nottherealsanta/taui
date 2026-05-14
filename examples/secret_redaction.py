"""Example: tool result post-processor that redacts secrets.

Scans every tool result for patterns that look like API keys,
tokens, or passwords and replaces them with [REDACTED].
"""

from __future__ import annotations

import re

from taui.tools.base import ToolResult

# Patterns that look like secrets
_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*\S+"),
    re.compile(r"(?i)bearer\s+[a-zA-Z0-9._-]{20,}"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]


def redact_secrets(
    tool_name: str, call_id: str, result: ToolResult
) -> ToolResult:
    """Replace secret-looking patterns with [REDACTED]."""
    content = result.content
    for pattern in _SECRET_PATTERNS:
        content = pattern.sub("[REDACTED]", content)
    if content != result.content:
        return ToolResult(
            content=content,
            error=result.error,
            metadata={**result.metadata, "redacted": True},
        )
    return result


def register(ctx):
    """Register as a taui extension.

    Usage: copy to .taui/extensions/secret_redaction.py
    """
    # Result processors are registered on the session,
    # not through the extension context. This example shows
    # the function signature — wire it in your own code:
    #
    #   session.add_result_processor(redact_secrets)
    pass
