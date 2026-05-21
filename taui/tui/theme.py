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

TAUI_ARCADE = Theme(
    name="taui-arcade",
    primary="#ff2bd6",       # hot magenta
    secondary="#00e5ff",     # cyan
    accent="#b14bff",         # violet
    foreground="#e8eaff",
    background="#0a0420",     # deep indigo
    surface="#150a3a",
    panel="#1f1252",
    success="#7cff5a",        # lime
    warning="#ffb84d",        # amber
    error="#ff4d6d",
    dark=True,
    variables={
        "block-cursor-text-style": "none",
        "footer-key-foreground": "#e8eaff",
        "footer-description-foreground": "#a4a0d4",
        "input-selection-background": "#ff2bd6 30%",
        "scrollbar-color": "#2a1a6b",
        "scrollbar-color-hover": "#3f2a99",
        "scrollbar-color-active": "#5b3ee0",
        "scrollbar-background": "#0a0420",
    },
)

TAUI_TERMINAL = Theme(
    name="taui-terminal",
    primary="#33ff66",        # phosphor green
    secondary="#1faa44",      # dim green
    accent="#9aff9a",
    foreground="#c8ffd0",
    background="#020602",     # near-black
    surface="#061206",
    panel="#0a1c0a",
    success="#33ff66",
    warning="#ffb000",        # amber
    error="#ff5050",
    dark=True,
    variables={
        "block-cursor-text-style": "none",
        "footer-key-foreground": "#c8ffd0",
        "footer-description-foreground": "#5f9a66",
        "input-selection-background": "#33ff66 25%",
        "scrollbar-color": "#0e2a14",
        "scrollbar-color-hover": "#1a4424",
        "scrollbar-color-active": "#33ff66",
        "scrollbar-background": "#020602",
    },
)

ALL_THEMES: list[Theme] = [TAUI_DARK, TAUI_LIGHT, TAUI_ARCADE, TAUI_TERMINAL]
