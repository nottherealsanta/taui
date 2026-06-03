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
        # ── Modal / dialog chrome ──────────────────────────────────────
        # Shared design tokens for every overlay (pickers, command palette,
        # diff/inspector modals). Referencing these as `$taui-*` keeps the
        # whole modal layer consistent and theme-aware instead of each
        # screen hardcoding its own grays.
        "taui-scrim": "#070707 70%",      # dimmed backdrop behind a modal
        "taui-dialog-bg": "#0d0d0d",      # dialog container surface
        "taui-field-bg": "#121212",       # inputs / option lists inside a dialog
        "taui-border": "#2a2a2a",         # resting border / keyline
        "taui-border-subtle": "#1e1e1e",  # faint frame border / section divider
        "taui-border-focus": "#5a5a5a",   # focused border
        "taui-option-active": "#2a2a2a",  # highlighted option row
        "taui-cyan": "#56d4dd",           # category/group header accent (mcp, tools)
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
        "scrollbar-color": "#d0d7de",
        "scrollbar-color-hover": "#afb8c1",
        "scrollbar-color-active": "#8c959f",
        "scrollbar-background": "#ffffff",
        # ── Modal / dialog chrome ──────────────────────────────────────
        # Light-theme counterparts of the dark tokens above. Defining them
        # here is what makes every modal render correctly in light mode —
        # previously each screen hardcoded dark grays and looked broken.
        "taui-scrim": "#1f2328 40%",      # dark translucent scrim over light content
        "taui-dialog-bg": "#ffffff",      # dialog container surface
        "taui-field-bg": "#f6f8fa",       # inputs / option lists inside a dialog
        "taui-border": "#d0d7de",         # resting border / keyline
        "taui-border-subtle": "#d0d7de",  # faint frame border / section divider
        "taui-border-focus": "#0969da",   # focused border
        "taui-option-active": "#dde4ec",  # highlighted option row
        "taui-cyan": "#0e7490",           # category/group header accent (mcp, tools)
    },
)

ALL_THEMES: list[Theme] = [TAUI_DARK, TAUI_LIGHT]
