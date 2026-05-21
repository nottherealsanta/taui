"""Taui default theme — a dark, near-black palette with orange accents.

Generated with the Textual theme system in mind.
See https://textual.textualize.io/guide/design/ and
https://github.com/xandertreat/textual-theme-gen for the Theme API.
"""

from __future__ import annotations

from textual.theme import Theme

# ── Base palette ──────────────────────────────────────────────────────
# Near-black neutral background — no blue tint. Orange remains the
# signature accent.

TAUI_DARK = Theme(
    name="taui-dark",
    primary="#f97316",       # orange — the signature accent
    secondary="#a8a8a8",     # neutral light gray — secondary accent
    accent="#d2a8ff",        # purple — tertiary / emphasis
    foreground="#e8e8e8",    # near-white neutral text
    background="#070707",    # near-black, neutral
    surface="#0e0e0e",       # widget / card background
    panel="#161616",         # sidebar / panel background
    success="#3fb950",       # green
    warning="#f2cc60",       # yellow
    error="#ff7b72",         # red / salmon
    dark=True,
    variables={
        "block-cursor-text-style": "none",
        "footer-key-foreground": "#e8e8e8",
        "footer-description-foreground": "#8a8a8a",
        "input-selection-background": "#f97316 30%",
        "scrollbar-color": "#262626",
        "scrollbar-color-hover": "#3a3a3a",
        "scrollbar-color-active": "#5a5a5a",
        "scrollbar-background": "#070707",
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
