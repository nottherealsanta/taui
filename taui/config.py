"""
Runtime configuration for taui.

Layered config: defaults → config file → env vars → CLI args.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from taui.llm_provider.config import load_config

# ── Default system prompt ──────────────────────────────────────────────────────
# Fallback only — Session.create() uses SystemPromptBuilder with template
# variables instead. This is used when constructing a Config directly
# without a builder (e.g., tests).

DEFAULT_SYSTEM_PROMPT = """\
You are an expert software engineer. You solve problems by using your tools.

Rules:
- Read before editing. Never edit blind.
- Keep changes minimal and scoped to the task.
- Run tests after changes when a test suite exists.
"""


# ── Config ─────────────────────────────────────────────────────────────────────


@dataclass
class Config:
    """Runtime configuration assembled from multiple sources."""

    # LLM
    provider: str = "copilot"
    model: str = ""

    # Agent
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    max_turns: int = 50
    session_id: str | None = None

    # Paths
    working_dir: Path = field(default_factory=Path.cwd)

    # Tool policy
    auto_approve_reads: bool = True
    tool_policy: dict[str, str] = field(default_factory=dict)  # per-tool overrides

    # CLI display
    verbose_tools: bool = True  # show full tool output (toggle with /verbose)
    theme: dict = field(default_factory=dict)  # style overrides
    keybindings: dict = field(default_factory=dict)  # custom keybindings

    @classmethod
    def load(cls, **overrides) -> Config:
        """Load config from file, then apply overrides (env/CLI)."""
        file_cfg = load_config()
        taui_cfg = file_cfg.get("taui", {})

        kwargs: dict = {}
        for fld in ("provider", "model", "system_prompt", "max_turns"):
            if fld in taui_cfg:
                kwargs[fld] = taui_cfg[fld]

        # CLI display settings
        if "verbose_tools" in taui_cfg:
            kwargs["verbose_tools"] = taui_cfg["verbose_tools"]
        if "theme" in taui_cfg:
            kwargs["theme"] = taui_cfg["theme"]
        if "keybindings" in taui_cfg:
            kwargs["keybindings"] = taui_cfg["keybindings"]
        if "tool_policy" in taui_cfg:
            kwargs["tool_policy"] = taui_cfg["tool_policy"]

        # CLI/env overrides win
        kwargs.update({k: v for k, v in overrides.items() if v is not None})

        cfg = cls(**kwargs)

        # If no model was set from any source, pick the best for this provider
        if not cfg.model:
            from taui.llm_provider.models import get_default_model

            cfg.model = get_default_model(cfg.provider)

        return cfg
