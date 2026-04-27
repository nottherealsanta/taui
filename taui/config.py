"""
Runtime configuration for taui.

Layered config: defaults → config file → env vars → CLI args.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from taui.llm_provider.config import load_config


# ── Default system prompt ──────────────────────────────────────────────────────

DEFAULT_SYSTEM_PROMPT = """\
You are a skilled software engineer. You have access to tools for reading, \
writing, editing, searching files, and running shell commands.

Rules:
- Read files before editing. Never edit blind.
- Keep changes minimal — only change what's needed.
- Prefer `edit` for targeted changes, `write` for new files.
- Run tests after making changes when a test suite exists.
- Be concise in your responses.
"""


# ── Config ─────────────────────────────────────────────────────────────────────


@dataclass
class Config:
    """Runtime configuration assembled from multiple sources."""

    # LLM
    provider: str = "copilot"
    model: str = "claude-sonnet-4.6"

    # Agent
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    max_turns: int = 50

    # Paths
    working_dir: Path = field(default_factory=Path.cwd)

    # Tool policy
    auto_approve_reads: bool = True

    @classmethod
    def load(cls, **overrides) -> Config:
        """Load config from file, then apply overrides (env/CLI)."""
        file_cfg = load_config()
        taui_cfg = file_cfg.get("taui", {})

        kwargs: dict = {}
        for fld in ("provider", "model", "system_prompt", "max_turns"):
            if fld in taui_cfg:
                kwargs[fld] = taui_cfg[fld]

        # CLI/env overrides win
        kwargs.update({k: v for k, v in overrides.items() if v is not None})

        return cls(**kwargs)
