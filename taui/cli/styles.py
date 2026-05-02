"""Style constants for the CLI interface."""

from __future__ import annotations

from prompt_toolkit.styles import Style

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

_SEP_CHAR = "─"
_BOX_HORIZONTAL = "─"
_BOX_VERTICAL = "│"
_BOX_TOP_LEFT = "┌"
_BOX_TOP_RIGHT = "┐"
_BOX_BOTTOM_LEFT = "└"
_BOX_BOTTOM_RIGHT = "┘"

_DEFAULT_STYLE = {
    # Message area
    "output-field": "bg:#000000 fg:#e0e0e0",
    # Input box
    "input-box": "bg:#1a1a2e fg:#e0e0e0",
    "input-box.border": "fg:#5f87af",
    "input-box.prompt": "fg:ansigreen bold",
    "input-box.prompt.ext": "fg:ansiyellow bold",
    # Info bar
    "info-bar": "bg:#16213e fg:#a0a0c0",
    "info-bar.provider": "fg:#7ec8e3 bold",
    "info-bar.cost": "fg:#98c379",
    "info-bar.context": "fg:#e5c07b",
    "info-bar.context-warn": "fg:#e06c75 bold",
    "info-bar.spinner": "fg:#61afef bold",
    "info-bar.sep": "fg:#3b3b5c",
    # Scrollbar
    "scrollbar.background": "bg:#1a1a2e",
    "scrollbar.button": "bg:#5f87af",
    "scrollbar.arrow": "fg:#5f87af",
}

PROMPT_STYLE = Style.from_dict(_DEFAULT_STYLE)


def build_style(overrides: dict | None = None) -> Style:
    """Build a prompt-toolkit Style with optional overrides from config.

    Overrides are key-value pairs matching the style dict keys above.
    Example config.toml:

        [taui.theme]
        "output-field" = "bg:#1e1e2e fg:#cdd6f4"
        "input-box" = "bg:#313244 fg:#cdd6f4"
        "info-bar" = "bg:#181825 fg:#a6adc8"
    """
    if not overrides:
        return PROMPT_STYLE
    merged = {**_DEFAULT_STYLE, **overrides}
    return Style.from_dict(merged)
