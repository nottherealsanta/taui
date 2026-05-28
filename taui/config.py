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
    model_variant: str = ""  # e.g. "high", "minimal" — reasoning effort/thinking variant

    # Agent
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    max_turns: int = 50
    session_id: str | None = None

    # Paths
    working_dir: Path = field(default_factory=Path.cwd)

    # Tool policy
    auto_approve: bool = False  # session-level: skip approval for tools that would ask
    tool_policy: dict[str, str] = field(default_factory=dict)  # per-tool overrides
    permission: dict[str, dict[str, str]] = field(default_factory=dict)  # pattern-based rules

    # CLI display
    verbose_tools: bool = True  # show full tool output (toggle with /verbose)
    theme: dict = field(default_factory=dict)  # style overrides
    keybindings: dict = field(default_factory=dict)  # custom keybindings
    extension_dirs: list[str] = field(default_factory=list)
    # Prefix characters for input triggers
    prefixes: dict[str, str] = field(default_factory=lambda: {
        "file_attach": "@",
        "command": "/",
        "skills": "!",
        "prompts": "#",
    })
    # Notifications: in-app toast when focused, OS-level when backgrounded.
    notifications: bool = True
    notify_on_turn_done: bool = True
    notify_on_question: bool = True

    @classmethod
    def load(cls, **overrides) -> Config:
        """Load config from file, then apply overrides (env/CLI)."""
        file_cfg = load_config()
        taui_cfg = file_cfg.get("taui", {})

        kwargs: dict = {}
        for fld in ("provider", "model", "model_variant", "system_prompt", "max_turns"):
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
        if "permission" in taui_cfg:
            kwargs["permission"] = taui_cfg["permission"]
        if "extension_dirs" in taui_cfg:
            val = taui_cfg["extension_dirs"]
            if isinstance(val, list):
                kwargs["extension_dirs"] = val
        if "prefixes" in taui_cfg:
            val = taui_cfg["prefixes"]
            if isinstance(val, dict):
                # Merge with defaults so missing keys still have a value
                defaults = {
                    "file_attach": "@",
                    "command": "/",
                    "skills": "!",
                    "prompts": "#",
                }
                defaults.update(val)
                kwargs["prefixes"] = defaults
        for fld in ("notifications", "notify_on_turn_done", "notify_on_question"):
            if fld in taui_cfg:
                kwargs[fld] = bool(taui_cfg[fld])

        # CLI/env overrides win
        kwargs.update({k: v for k, v in overrides.items() if v is not None})

        cfg = cls(**kwargs)

        # If no model was set from any source, use last-used or pick default
        if not cfg.model:
            from taui.llm_provider.config import load_last_model
            last = load_last_model(cfg.provider)
            if last:
                cfg.model = last
            else:
                from taui.llm_provider.models import get_default_model
                cfg.model = get_default_model(cfg.provider)

        return cfg
