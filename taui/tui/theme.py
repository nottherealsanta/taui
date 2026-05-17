"""Taui default theme — a dark GitHub-inspired palette with orange accents.

Generated with the Textual theme system in mind.
See https://textual.textualize.io/guide/design/ and
https://github.com/xandertreat/textual-theme-gen for the Theme API.
"""

from __future__ import annotations

from textual.theme import Theme

# ── Base palette ──────────────────────────────────────────────────────
# Derived from the original hardcoded GitHub-dark colors already used
# throughout taui, with the markdown "main color" shifted from teal to
# orange as requested.

TAUI_DARK = Theme(
    name="taui-dark",
    primary="#f97316",       # orange — the signature accent
    secondary="#58a6ff",     # GitHub blue — secondary accent
    accent="#d2a8ff",        # purple — tertiary / emphasis
    foreground="#e6edf3",    # near-white text
    background="#0d1117",    # deepest background
    surface="#161b22",       # widget / card background
    panel="#21262d",         # sidebar / panel background
    success="#3fb950",       # green
    warning="#f2cc60",       # yellow
    error="#ff7b72",         # red / salmon
    dark=True,
    variables={
        "block-cursor-text-style": "none",
        "footer-key-foreground": "#e6edf3",
        "footer-description-foreground": "#8b949e",
        "input-selection-background": "#58a6ff 35%",
        "scrollbar-color": "#30363d",
        "scrollbar-color-hover": "#484f58",
        "scrollbar-color-active": "#6e7681",
        "scrollbar-background": "#0d1117",
    },
)

TAUI_LIGHT = Theme(
    name="taui-light",
    primary="#ea580c",       # orange-600
    secondary="#0969da",     # blue
    accent="#8250df",        # purple
    foreground="#1f2328",
    background="#ffffff",
    surface="#f6f8fa",
    panel="#f0f0f0",
    success="#1a7f37",
    warning="#9a6700",
    error="#cf222e",
    dark=False,
    variables={
        "block-cursor-text-style": "none",
        "footer-key-foreground": "#1f2328",
        "footer-description-foreground": "#656d76",
        "input-selection-background": "#0969da 25%",
    },
)

ALL_THEMES: list[Theme] = [TAUI_DARK, TAUI_LIGHT]
