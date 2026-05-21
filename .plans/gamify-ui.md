# Gamify UI Plan

Make taui feel like a game — without making it gimmicky. The TUI keeps its role
as a serious coding tool, but every interaction now has weight, feedback, and
progression. Think *Vim meets Hades*: minimal chrome, satisfying micro-feedback,
optional progression, and a palette that looks like a CRT shrine.

The work lands in three layers — **Look**, **Feel**, **Progression** — that
can ship independently. Layer 1 is reversible cosmetic polish; Layer 2 adds
motion and audio-less juice; Layer 3 adds an opt-in progression/HUD system.

---

## Layer 1 — Look: "Synthwave Console"

The current theme (`taui/tui/theme.py`) is a flat GitHub-dark with one orange
accent. We add two new game-inspired themes and upgrade existing widgets to use
them — no behavior changes.

### 1.1 Two new themes (`taui/tui/theme.py`)

- `taui-arcade` — neon synthwave: deep indigo background, hot magenta primary,
  cyan secondary, lime success, amber warning. Bright on dark, high contrast.
- `taui-terminal` — phosphor green CRT: near-black background, classic phosphor
  green (#33ff66) primary, dim green secondary, amber alerts. One-color UI.
- Keep `taui-dark` / `taui-light` as defaults; arcade/terminal opt-in via
  `/theme` command or config.

### 1.2 Themed status bar (`taui/tui/widgets/status_bar.py`)

Replace the plain `[████░░░░] 42%` bar with a segmented HUD bar:

```
◤ claude-sonnet-4.5 ◢ ⚡copilot     ▰▰▰▰▰▰▱▱▱▱  42% ctx   23 ↑ 41 ↓ 12 ⚙
```

- Segmented bar uses `▰`/`▱` (filled/empty pip glyphs) with color ramp
  green → yellow → red as before.
- Add slanted parallelogram brackets `◤ ◢` around model name (CSS only).
- Add three live counters next to the bar: turns (`↑`), tools used (`↓`),
  approvals (`⚙`). Counters come from session state already tracked in
  `taui/tui/session_state.py`.

### 1.3 Themed footer / key legend (`taui/tui/widgets/footer.py`)

- Key chips rendered as `▸Ctrl+B◂ Sidebar` style — chip-like, not flat text.
- On press, the chip briefly inverts (Layer 2 picks this up).

### 1.4 Tool status as "ability cards" (`taui/tui/widgets/tool_status.py`)

Each running tool currently shows a one-line spinner. Upgrade to a compact card:

```
┌─ ⚡ Bash ──────────────────────── 0.42s ─┐
│ rg --files -g "*.py" | wc -l            │
└──────────────── ⠼ running ──────────────┘
```

- Border color = tool category (read=cyan, write=magenta, exec=amber).
- On completion: border flashes green/red for ~200ms, then settles to a
  thin success/failure rule. Title bar shows the tool icon + name.
- On failure: card shakes (1-frame horizontal jitter) — implemented as a
  CSS class toggle, not actual movement, just margin nudges.

### 1.5 Turn dividers (`taui/tui/widgets/turn_container.py`)

Replace the plain horizontal rule between turns with a "round divider":

```
─────────── ◆ TURN 7 · 1.4s · 2 tools ◆ ───────────
```

Compact, centered, includes elapsed time and tool count for the turn.

### 1.6 Spinner upgrades (`taui/tui/widgets/spinner.py`)

- Cycle through a tasteful sequence — not just braille — that fits the theme:
  `▰▰▰▰▰▰` → `▰▰▰▰▰▱` → … (loading bar feel) for arcade;
  `▘▝▗▖` (quadrant cycle) for terminal.
- One spinner per theme, picked from the active theme's variables.

---

## Layer 2 — Feel: Micro-feedback ("Juice")

Small, instant reactions that make the UI feel alive. No sound (TUI). No
celebratory popups. Just feedback you'd miss if it wasn't there.

### 2.1 Key-press feedback

- Every footer chip flashes its background on key press (50ms).
- The active pane gets a 1-cell glow border (CSS) when focused.

### 2.2 Tool lifecycle animations

- **Start**: card slides in from the right (1 frame: indent → flush).
- **Tick**: cost/duration counter updates every 250ms in dim color.
- **End**: short border-pulse animation, then collapse to one line if the
  output is empty/short — keeps the scrollback dense.

### 2.3 Streaming response cursor

`agent_response.py` currently writes markdown via stream. Add a blinking caret
glyph `▌` at the tail while streaming; remove on completion. Implemented as a
suffix the markdown renderer appends, toggled by a 500ms interval.

### 2.4 Approval "decision moment"

When an approval prompt appears (`taui/tui/widgets/approval.py`):

- The prompt pane pulses its border color once (warning → primary).
- Approve = green flash + check glyph; Deny = red flash + X glyph.
- A subtle 1-line "decision recap" stays in scrollback:
  `✓ Approved Bash · git status` / `✗ Denied Write · /etc/passwd`.

### 2.5 Context bar "danger zone"

When context usage crosses 75% / 90%, the segmented bar:

- 75%: pips switch from steady to slow pulse (every 1.5s).
- 90%: faster pulse + the bar gains a `⚠` prefix.
- 99%: text turns red, no pulse — the alarm is over, you're already on fire.

### 2.6 Cancel feedback (Ctrl+C)

Today cancellation is silent. Add a one-line scrollback marker:

```
── ✗ cancelled · 3 tools in flight ──
```

So you can see in history *where* you bailed.

---

## Layer 3 — Progression: "Coding HUD" (opt-in)

The optional layer that makes it actually "gamified". Off by default. Enable
via `[taui.hud] enabled = true` in config or `/hud on`.

### 3.1 Session HUD widget (`taui/tui/widgets/session_hud.py` — new)

Docked just above the status bar, one line tall when collapsed:

```
LVL 4  ▰▰▰▰▰▰▱▱▱▱  642/1000 XP   🔥 12 turn streak   ⏱ 23m
```

- **XP** is derived purely from session events (no network, no accounts):
  - +5 XP per agent turn
  - +2 XP per successful tool call (cap 10/turn)
  - +20 XP per approved diff that the user *accepts* (file actually written)
  - −10 XP per cancellation
- **Level curve**: triangular, `xp_for(n) = 100 * n * (n+1) / 2`.
- **Streak**: consecutive non-cancelled turns this session.
- **Timer**: wall time since session start.

### 3.2 Achievements (in-memory + persisted to `~/.taui/achievements.json`)

Quiet, discoverable, mostly self-referential — never a popup that blocks input.
Shown as a one-line slide-in above the HUD that auto-dismisses in 3s:

```
🏆 First Light · sent your first message
```

Starter set:
- *First Light* — first message in any session
- *Tool Belt* — used 5 distinct tools in one session
- *Surgeon* — accepted a write/edit without modification
- *Skeptic* — denied an approval
- *Long Haul* — session over 30 minutes
- *Refactor Rampage* — 10 edits in one turn
- *Speed Run* — turn under 3 seconds end-to-end
- *Context Crunch* — used `/compact` while over 80%

All gated behind `[taui.hud]` — silent if HUD is off.

### 3.3 End-of-session "scorecard"

When the user quits (`Ctrl+Q`), if HUD is on, the goodbye screen replaces the
plain shutdown message with:

```
   ── session complete ──

   ⏱ 23m 14s        💬 18 turns
   🔧 42 tools      ✓ 39 ok  ✗ 3 fail
   📝 7 files edited, 142 lines net
   ⚡ +315 XP       🎯 3 achievements

   thanks for playing.
```

Pulled from session_state + git diff against session-start ref.

### 3.4 `/hud` slash command (`taui/commands/builtins.py`)

- `/hud` — show current state
- `/hud on|off` — toggle
- `/hud reset` — clear XP/achievements
- `/hud achievements` — list earned + locked (locked shown as `???`)

### 3.5 Hard rule: progression never blocks work

- No modal popups for achievements.
- No "are you sure" on level up.
- HUD widget can be `Ctrl+H` toggled away even when enabled.
- Disabling the HUD removes the widget entirely — no ghost space.

---

## Implementation Order

Each phase is independently shippable; each commit should be runnable.

1. **L1.1 + L1.2** — themes + status bar HUD (visible win, no behavior risk)
2. **L1.4** — tool status cards (touches the busiest widget, isolate early)
3. **L1.3 + L1.5 + L1.6** — footer, turn dividers, spinners (cosmetic sweep)
4. **L2.1 + L2.3** — key feedback + streaming caret (small, additive)
5. **L2.2 + L2.4 + L2.6** — tool/approval/cancel feedback
6. **L2.5** — context danger zone (depends on status bar from L1.2)
7. **L3.1** — Session HUD widget, off by default
8. **L3.4** — `/hud` command wiring
9. **L3.2** — achievements system
10. **L3.3** — scorecard on quit

---

## Files Touched (summary)

**Modify**
- `taui/tui/theme.py` — add `taui-arcade`, `taui-terminal` themes
- `taui/tui/widgets/status_bar.py` — segmented HUD bar, counters
- `taui/tui/widgets/footer.py` — chip-style keys + press flash
- `taui/tui/widgets/tool_status.py` — ability-card layout, lifecycle anims
- `taui/tui/widgets/turn_container.py` — round dividers
- `taui/tui/widgets/spinner.py` — themed spinners
- `taui/tui/widgets/agent_response.py` — streaming caret
- `taui/tui/widgets/approval.py` — decision-moment feedback
- `taui/tui/session_state.py` — XP/stats accumulators (additive)
- `taui/tui/app.py` — wire HUD widget, hotkey, theme registration
- `taui/commands/builtins.py` — `/hud` command
- `taui/config.py` — `[taui.hud]` config block

**Create**
- `taui/tui/widgets/session_hud.py` — HUD widget
- `taui/tui/hud/xp.py` — XP curve + event handlers
- `taui/tui/hud/achievements.py` — achievement definitions + storage

**No changes** to agent loop, providers, tools, permissions, or session
storage. The entire plan lives in the TUI layer plus one config block.

---

## What we deliberately *don't* do

- No sound (it's a TUI; SSH sessions, screen readers).
- No animated mascots, popups, confetti, or full-screen takeovers.
- No network calls — XP/achievements are local-only, never leaderboarded.
- No forced opt-in — every Layer 3 feature is gated behind `[taui.hud]`.
- No emoji-by-default in scrollback unless the active theme enables it
  (the arcade theme does; taui-dark stays text-only).
- No "daily challenges" or anything that pulls the user out of their work.
