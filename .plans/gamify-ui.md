# Gamify UI Plan

Make taui feel like a game — without making it gimmicky, and without spending
a single extra millisecond per frame to do it. The TUI keeps its role as a
serious coding tool; every interaction now has weight, feedback, and
progression. Think *Vim meets Hades*: minimal chrome, satisfying micro-
feedback, optional progression, and a palette that looks like a CRT shrine.

The work lands in three layers — **Look**, **Feel**, **Progression** — that
can ship independently. Layer 1 is reversible cosmetic polish; Layer 2 adds
motion and audio-less juice; Layer 3 adds an opt-in progression/HUD system.

**No emojis anywhere.** All glyphs are box-drawing, geometric shapes, or
plain ASCII. Terminals render them faster, screen readers tolerate them, and
SSH/tmux sessions stay aligned.

---

## Performance budget (applies to every layer)

These are hard rules — if a feature can't be built inside them, it doesn't ship.

- **No new per-frame work.** No timers under 250ms. No polling. All updates
  are event-driven from the existing agent loop / tool lifecycle hooks.
- **Idle = silent.** When the agent is not running and the user is not
  typing, zero widgets refresh. No "ambient" animation loops.
- **One timer per animation, shared.** A single 250ms tick on the active
  spinner/cursor drives every pulse — we do not spin up a Textual `set_interval`
  per widget.
- **No widget rebuilds for state changes.** Counters update via
  `Reactive` + targeted `refresh(layout=False)`; never a `recompose`.
- **Animations are CSS classes, not Python loops.** Border pulses, flashes,
  and "shakes" are toggled via add_class/remove_class with a single
  `call_later` to remove. No `await asyncio.sleep` chains.
- **Glyph cost = zero.** All upgrades are pure character substitutions in
  existing `render()` paths; no extra `Text` allocations per frame.
- **Scrollback is append-only.** No retroactive rerenders of past turns
  (no "decorate all old turn dividers"). Past widgets stay frozen.
- **Layer 3 is opt-in and lazy.** HUD widgets, XP counters, and stats
  imports are only loaded when `[taui.hud] enabled = true`. The default
  build path imports zero new modules.

Regression gate before each phase merges:
- `pytest tests/ -q` passes
- `taui` cold-start time (measured via `time taui --version` and a smoke
  startup script in `tests/`) is within ±5% of pre-change baseline.
- A 10-minute idle session shows no measurable CPU usage (sample with
  `py-spy top` for 30s — must report <0.5% in the TUI thread).

---

## Layer 1 — Look: "Synthwave Console"

The current theme (`taui/tui/theme.py`) is a flat GitHub-dark with one orange
accent. We add two new game-inspired themes and upgrade existing widgets to use
them — no behavior changes, no new render paths.

### 1.1 Two new themes (`taui/tui/theme.py`)

- `taui-arcade` — neon synthwave: deep indigo background, hot magenta primary,
  cyan secondary, lime success, amber warning. Bright on dark, high contrast.
- `taui-terminal` — phosphor green CRT: near-black background, classic phosphor
  green (#33ff66) primary, dim green secondary, amber alerts. One-color UI.
- Keep `taui-dark` / `taui-light` as defaults; arcade/terminal opt-in via
  `/theme` command or config.

*Cost: zero. Theme objects are static; Textual swaps palette without
re-mounting widgets.*

### 1.2 Themed status bar (`taui/tui/widgets/status_bar.py`)

Replace the plain `[####....] 42%` bar with a segmented HUD bar:

```
< claude-sonnet-4.5 > copilot     [||||||....]  42% ctx   T:23  X:41  A:12
```

- Segmented bar uses `|` / `.` (filled/empty pip glyphs) with color ramp
  green > yellow > red as before.
- Add slanted brackets `<` `>` around model name (CSS-styled text, not
  background fills, so no extra cells to paint).
- Add three live counters next to the bar: turns (`T:`), tools (`X:`),
  approvals (`A:`). Counters come from session state already tracked in
  `taui/tui/session_state.py`; bound to `Reactive` so only the changed
  segment of the bar re-renders.

*Cost: same number of `render()` calls as today; only the format string
differs. Reactive updates are coalesced by Textual.*

### 1.3 Themed footer / key legend (`taui/tui/widgets/footer.py`)

- Key chips rendered as `[Ctrl+B] Sidebar` style — chip-like, not flat text.
- On press, the chip briefly inverts via a CSS class added on key event
  and removed on a single `set_timer(0.05, ...)`. No per-frame loop.

### 1.4 Tool status as "ability cards" (`taui/tui/widgets/tool_status.py`)

Each running tool currently shows a one-line spinner. Upgrade to a compact card:

```
+- Bash ------------------------- 0.42s -+
| rg --files -g "*.py" | wc -l           |
+--------------- running -----------------+
```

- Border color = tool category (read=cyan, write=magenta, exec=amber) via
  CSS class set once at mount.
- On completion: border flashes green/red for ~200ms via class toggle,
  then settles. The "duration" text updates on tool_end only — not while
  running, except the existing spinner tick (no extra timers).
- On failure: card gains a `.failed` class that nudges margin by 1 cell
  one time (CSS transition, no Python animation).

*Cost: replaces one `Static` with one `Static` + CSS border. No new widgets,
no new event subscriptions. The "tick" is the existing spinner — we do not
add a duration counter that re-renders mid-run.*

### 1.5 Turn dividers (`taui/tui/widgets/turn_container.py`)

Replace the plain horizontal rule between turns with a "round divider":

```
----------- < TURN 7 | 1.4s | 2 tools > -----------
```

- Centered, compact, includes elapsed time and tool count for the turn.
- Rendered once on turn_end (already an event we receive). Never updated
  after — scrollback stays frozen.

### 1.6 Spinner upgrades (`taui/tui/widgets/spinner.py`)

- Cycle through a tasteful sequence — not just braille — that fits the theme:
  arcade: bar-fill `[|.....]` -> `[||....]` -> ... (8 frames, 125ms each, same
  cadence as today's braille);
  terminal: quadrant cycle `'`,`.`,`,`,`-` (4 frames).
- One spinner per theme, picked from the active theme's variables.
- Spinner runs **only while a tool or agent turn is active**. Today's
  spinner already follows that rule — we do not extend its lifetime.

---

## Layer 2 — Feel: Micro-feedback ("Juice")

Small, instant reactions that make the UI feel alive. No sound (TUI). No
celebratory popups. Every effect below is a one-shot CSS class toggle driven
by an event that we already handle — no new timers, no new background tasks.

### 2.1 Key-press feedback

- Every footer chip flashes its background on key press (50ms). Implemented
  via `add_class("pressed")` + `set_timer(0.05, lambda: remove_class)`.
- The active pane gets a 1-cell glow border (CSS) when focused. Focus events
  are free — Textual emits them anyway.

### 2.2 Tool lifecycle animations

- **Start**: card mounts with a `.entering` class; CSS transitions
  `margin-left` from 2 to 0 over 120ms. Class removed on first refresh.
- **No mid-run tick.** The existing spinner is enough; we do not add a
  duration counter that re-renders the card.
- **End**: short border-pulse via class toggle + `set_timer(0.2, ...)`,
  then the card collapses to one line if output is empty/short. Collapse
  is a one-time CSS height transition.

### 2.3 Streaming response cursor

`agent_response.py` already streams markdown fragments. Append a single
caret glyph `|` to the visible text only at stream-tail and only while
the stream is active. **No blink timer** — we drop the blink. A static
caret reads as "still typing" without any per-frame cost. Removed on
stream end via the same hook that finalizes the message.

### 2.4 Approval "decision moment"

When an approval prompt appears (`taui/tui/widgets/approval.py`):

- The prompt pane gains a `.pulse` class once on mount (CSS keyframes
  fire once, then idle).
- Approve = green flash + check glyph `[v]`; Deny = red flash + X glyph
  `[x]`. Both are one-shot class toggles on the existing widget.
- A subtle 1-line "decision recap" stays in scrollback:
  `[v] Approved Bash | git status` / `[x] Denied Write | /etc/passwd`.
  Written once to the scrollback log on the approval event — no rerender.

### 2.5 Context bar "danger zone"

When context usage crosses 75% / 90%, the segmented bar:

- 75%: bar gains `.warn` class (color shift only, no pulse).
- 90%: gains `.danger` class — single slow CSS keyframe pulse (1.5s loop),
  active **only while the bar widget is visible and over threshold**. Removed
  the instant usage drops back below or the widget hides.
- 99%: text turns red, pulse class removed — the alarm is over.

*Cost: one CSS animation, scoped to one element, only active in the danger
band. Pulsing is the GPU/terminal compositor's job, not Python's.*

### 2.6 Cancel feedback (Ctrl+C)

Today cancellation is silent. Add a one-line scrollback marker on the
existing cancel event:

```
-- [x] cancelled | 3 tools in flight --
```

Written once; never re-rendered.

---

## Layer 3 — Progression: "Coding HUD" (opt-in, lazy-loaded)

The optional layer that makes it actually "gamified". Off by default. Enable
via `[taui.hud] enabled = true` in config or `/hud on`. **When disabled, no
HUD code is imported and no counters are computed.**

### 3.1 Session HUD widget (`taui/tui/widgets/session_hud.py` — new)

Docked just above the status bar, one line tall when collapsed:

```
LVL 4  [||||||....]  642/1000 XP   streak 12   23m
```

- **XP** is derived purely from session events already emitted by the
  agent loop (no extra instrumentation):
  - +5 XP per agent turn
  - +2 XP per successful tool call (cap 10/turn)
  - +20 XP per approved diff that the user accepts (file actually written)
  - -10 XP per cancellation
- **Level curve**: triangular, `xp_for(n) = 100 * n * (n+1) / 2`.
- **Streak**: consecutive non-cancelled turns this session.
- **Timer**: wall time since session start, updated **only on turn boundary
  events** — not on a wall-clock timer. The displayed minute is stale
  between turns; that's fine and intentional.

*Cost: one extra `Static` widget, one extra Reactive value per event we
already receive. Idle CPU stays at zero because there's no clock loop.*

### 3.2 (removed)

Achievements are not part of this plan.

### 3.3 End-of-session scorecard

When the user quits (`Ctrl+Q`), if HUD is on, the goodbye screen replaces the
plain shutdown message with:

```
   -- session complete --

   23m 14s         18 turns
   42 tools        39 ok / 3 fail
   7 files edited, 142 lines net
   +315 XP

   thanks for playing.
```

Pulled from session_state + a single `git diff --shortstat` against the
session-start ref captured at startup. Runs once on quit; no impact on
session runtime.

### 3.4 `/hud` slash command (`taui/commands/builtins.py`)

- `/hud` — show current state
- `/hud on|off` — toggle (mounts/unmounts the widget, no orphan timers)
- `/hud reset` — clear XP

### 3.5 Hard rules: progression never blocks work, never costs idle CPU

- No modal popups.
- HUD widget can be `Ctrl+H` toggled away even when enabled.
- Disabling the HUD unmounts the widget and drops all references — no
  ghost space, no lingering subscribers.
- HUD module imports are gated behind a config check at app startup;
  users with the HUD off pay zero import cost.

---

## Implementation Order

Each phase is independently shippable; each commit must pass the
performance gate before merging.

1. **L1.1 + L1.2** — themes + status bar HUD (visible win, no behavior risk)
2. **L1.4** — tool status cards (touches the busiest widget, isolate early)
3. **L1.3 + L1.5 + L1.6** — footer, turn dividers, spinners (cosmetic sweep)
4. **L2.1 + L2.3** — key feedback + streaming caret (small, additive)
5. **L2.2 + L2.4 + L2.6** — tool/approval/cancel feedback
6. **L2.5** — context danger zone (depends on status bar from L1.2)
7. **L3.1** — Session HUD widget, off by default, lazy-imported
8. **L3.4** — `/hud` command wiring
9. **L3.3** — scorecard on quit

---

## Files Touched (summary)

**Modify**
- `taui/tui/theme.py` — add `taui-arcade`, `taui-terminal` themes
- `taui/tui/widgets/status_bar.py` — segmented HUD bar, counters
- `taui/tui/widgets/footer.py` — chip-style keys + one-shot press flash
- `taui/tui/widgets/tool_status.py` — ability-card layout, CSS lifecycle anims
- `taui/tui/widgets/turn_container.py` — round dividers (one-shot)
- `taui/tui/widgets/spinner.py` — themed spinners (same cadence as today)
- `taui/tui/widgets/agent_response.py` — static streaming caret (no blink)
- `taui/tui/widgets/approval.py` — decision-moment CSS pulse
- `taui/tui/session_state.py` — XP/stats accumulators (additive, gated)
- `taui/tui/app.py` — wire HUD widget conditionally, theme registration
- `taui/commands/builtins.py` — `/hud` command
- `taui/config.py` — `[taui.hud]` config block

**Create (only loaded when HUD enabled)**
- `taui/tui/widgets/session_hud.py` — HUD widget
- `taui/tui/hud/xp.py` — XP curve + event handlers

**No changes** to agent loop, providers, tools, permissions, or session
storage. The entire plan lives in the TUI layer plus one config block.

---

## What we deliberately *don't* do

- No emojis. No sound. No animated mascots, popups, confetti, or full-
  screen takeovers.
- No achievements system.
- No network calls — XP is local-only, never leaderboarded.
- No background timers, polling loops, or wall-clock refreshes. Every
  effect is driven by an event we already handle.
- No retroactive rerenders of past scrollback.
- No "daily challenges" or anything that pulls the user out of their work.
