# Gamify UI Plan

Make taui feel like a game without spending extra cycles to do it. Three
layers, each shippable on its own. No emojis (Unicode geometric/box-drawing
glyphs like `▰▱◆◤◢` are fine).

## Performance budget (hard gate, every phase)

- No new per-frame work. No timers under 250ms. No polling.
- Idle = zero CPU. All updates event-driven from existing agent/tool hooks.
- Animations are one-shot CSS class toggles + `set_timer`, not Python loops.
- No widget rebuilds for state changes — Reactive + `refresh(layout=False)`.
- Scrollback append-only; never re-render past turns.
- Layer 3 lazy-imported when disabled (zero cost if HUD off).
- Gate: pytest green, cold-start ±5%, `py-spy` <0.5% on 10-min idle session.

## Layer 1 — Look

- **1.1 Theme** (`taui/tui/theme.py`): darken default `taui-dark` to a
  near-black neutral palette (no blue tint). No additional themes.
- **1.2 Status bar** (`taui/tui/widgets/info_bar.py`): keep existing
  `model / provider / Nk/Nk` format. No segmented bar, no brackets.
- **1.3 Footer** (`taui/tui/widgets/footer.py`): chip-style keys `[Ctrl+B]`,
  press-flash via CSS class.
- **1.4 Tool cards** (`taui/tui/widgets/tool_status.py`): bordered card per
  tool, category-colored border, one-shot pulse on end. No mid-run ticks.
- **1.5 Turn dividers** (`taui/tui/widgets/turn_container.py`):
  `───── ◆ TURN 7 │ 1.4s │ 2 tools ◆ ─────`, rendered once on turn_end.
- **1.6 Spinners** (`taui/tui/widgets/spinner.py`): theme-aware glyph
  sequences, same cadence as today.

## Layer 2 — Feel

- **2.1 Key feedback**: footer chips flash (50ms class toggle); focused pane
  gets glow border (CSS, focus events are free).
- **2.2 Tool lifecycle**: CSS slide-in on start, one-shot pulse on end,
  collapse to one line if output empty. No mid-run timers.
- **2.3 Streaming caret**: static `▌` at stream tail (no blink).
- **2.4 Approval moment**: one-shot CSS pulse on prompt; `[v]/[x]` recap line
  in scrollback on decide.
- **2.5 Context danger**: 75% `.warn` color shift; 90% single CSS keyframe
  pulse (active only in band); 99% steady red.
- **2.6 Cancel marker**: `── [x] cancelled │ N tools ──` written once.

## Layer 3 — Progression (opt-in, lazy-loaded)

- **3.1 Session HUD** (`taui/tui/widgets/session_hud.py`): one-line widget
  above status bar: `LVL 4  ▰▰▰▰▰▰▱▱▱▱  642/1000 XP  streak 12  23m`.
  XP from events already emitted (+5/turn, +2/tool, +20/accepted-edit,
  -10/cancel). Triangular curve. Timer updates only on turn boundaries.
- **3.3 Scorecard on quit** (Ctrl+Q): one-time summary using session_state
  + `git diff --shortstat`.
- **3.4 `/hud` command**: `on|off|reset`. Unmount drops all references.
- All HUD imports gated by config — zero cost when disabled.

## Implementation order

1. L1.1 + L1.2 — themes + status bar
2. L1.4 — tool cards
3. L1.3 + L1.5 + L1.6 — footer, dividers, spinners
4. L2.1 + L2.3 — key feedback + caret
5. L2.2 + L2.4 + L2.6 — tool/approval/cancel feedback
6. L2.5 — context danger zone
7. L3.1 + L3.4 — HUD widget + command
8. L3.3 — scorecard

## Don't

- No emojis. No sound. No achievements. No popups.
- No network calls. No background timers or polling.
- No retroactive scrollback rerenders.
