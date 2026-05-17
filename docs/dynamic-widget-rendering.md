# Dynamic Widget Rendering

Status: design + prototype + initial implementation
Branch: `worktree-dynamic-widgets`
Tracks: TODO.md → "research dynamic rendering with widgets"

## 1. Motivation

Today taui renders a conversation as a flat stack of widgets inside a single
`VerticalScroll` chat log:

```
user-message (Static)        ← turn 1 header
AgentResponse (Markdown)     ← turn 1 body
ToolStatusWidget …           ← turn 1 body
ReplyFooter                  ← turn 1 trailer
user-message (Static)        ← turn 2 header
AgentResponse                ← turn 2 body
ReplyFooter                  ← turn 2 trailer
…
```

There is no structural notion of a *turn* — `ReplyFooter` is the only soft
delimiter, and it is mounted via `_mount_in_reply` in `taui/tui/app.py`. Two
ergonomic problems fall out:

1. **No way to fold a long turn.** A multi-paragraph assistant message or a
   verbose tool call dominates the viewport indefinitely, even when the user
   has moved on to a new question and only cares about the *current* exchange.
2. **No way to peek deeper into a tool output.** `ToolStatusWidget` truncates
   tool output to ~150 chars; the full output is not reachable from the TUI.

Both stem from the same architectural gap: turns are not first-class
containers, so they cannot host UI affordances (a chevron, a focus binding,
a collapsed/expanded state).

This document proposes the missing structure, the widget choices, and the
auto-collapse policy.

## 2. Goals & non-goals

**Goals**

- Each user → assistant exchange becomes a *turn* with a single
  collapsible body.
- Clicking a chevron (or pressing a key) toggles the body.
- Turns older than `current - 1` auto-collapse so the viewport stays focused
  on the active exchange and the immediately preceding one.
- Tool rows gain a "peek" affordance: clicking expands the full tool output
  inline, below the one-line summary.
- The change must not regress streaming responsiveness — `AgentResponse`'s
  per-frame flush must still work unchanged.
- Existing visual snapshots (`tests/__snapshots__/test_tui_visual/`) either
  pass or are intentionally refreshed with an explanation.

**Non-goals**

- Re-skinning markdown, reasoning blocks, or the reply footer.
- Persisting expanded/collapsed state across sessions.
- Replacing the existing `ToolStatusWidget` text/colour scheme — only
  expansion is added.
- Touching the `Self-edit hotreload`, `Color tweaks`, or `Smart notifications`
  TODO entries (separate workstreams).

## 3. Widget choices

| Concern | Widget | Rationale |
|---|---|---|
| Turn container | Custom `TurnContainer(Vertical)` | We need the user message itself to be the visible "header" (not hidden behind a generic title bar), so the built-in `Collapsible` is the wrong primitive — its title is a single line of `Static`. A small custom container keeps the existing user message styling intact. |
| Chevron | `Static` with `▶ ` / `▼ ` glyphs, clickable | Cheap and themeable via Rich markup. No extra dependency. |
| Body | `Vertical` with `display: none` toggled via CSS class | Avoids re-mounting children when toggling — preserves AgentResponse state and any scroll position inside long bodies. |
| Tool expansion | Extend `ToolStatusWidget` with an optional `Static` body that is mounted on first toggle (lazy) | Cheap on the common path: only tools whose output the user actually expands pay the rendering cost. |

Textual 8.2.4 ships `Collapsible` (`textual.widgets.Collapsible`) — we deliberately
*don't* use it for the turn container (see above) but we model the `expanded` /
`collapsed` reactive pattern after it.

## 4. Data model

`SessionState` gains a single list:

```python
turns: list[TurnContainer] = field(default_factory=list)
```

A new turn is created in `handle_input` *before* the user message is mounted.
All subsequent assistant content for that turn is mounted via
`_mount_in_reply`, which is updated to mount *inside the active turn's body*
instead of directly into `chat_log` (with `ReplyFooter` still being the
in-body sentinel).

The list is bounded — we don't need to keep more than `current + 1` turns
hot; older turns stay mounted but collapsed.

## 5. Auto-collapse policy

> "auto collapsing for any message older than current_message - 2"
> — TODO.md

Interpretation:

- The *current* turn (the one being streamed or just finished) is expanded.
- The immediately preceding turn is expanded too — users typically want
  one-back context after sending a follow-up.
- Anything older (index ≤ `len(turns) - 3`) is collapsed by default.
- A user-initiated expand *sticks* until the page changes (no fighting the
  user). Internally we set a `sticky_expanded` flag on the `TurnContainer`
  and the auto-collapser skips sticky turns.

Trigger point: when a new turn is created, walk the existing turn list and
apply the rule. This is O(n) but n is small (we re-render on each new user
turn at most once).

```python
def _autocollapse_old_turns(self, state):
    keep_expanded = set(state.turns[-2:])   # last two
    for t in state.turns:
        if t in keep_expanded or t.sticky_expanded:
            t.expand()
        else:
            t.collapse()
```

## 6. Tool "peek-more"

`ToolStatusWidget` today:

```
✦ read note.txt    read me
```

After the change, the row becomes clickable. On click (or `Enter` when
focused), a child `Static` is lazily mounted directly below the row showing
the *full* tool output, rendered as plain monospaced text wrapped to the
chat-log width. A second click collapses it. The collapsed/expanded state
is local to the widget — no global registry.

For tools that have already provided rich formatted bodies in the
chat-log (e.g. read with a multi-line preview), this is a no-op — the
preview itself is the expansion. The implementation uses an explicit
`set_full_output(text)` API called by the tool completion path; if no full
output is stored, the row is *not* made interactive (no misleading chevron).

## 7. Streaming + container interaction

`AgentResponse.append_text` is called from `handle_stream_text` once per
delta. Today it's mounted directly into the chat log via `_mount_in_reply`.
After the change, `_mount_in_reply` mounts into the active turn's body — the
streaming code path is unchanged because all it does is call
`st.current_response.append_text`, and the widget can stream regardless of
whether it sits in a `VerticalScroll` or a `Vertical` inside one.

The scroll-anchor behaviour is preserved because the chat log itself is
still the only scrollable region; turn bodies are pure flex containers.

## 8. CSS

```css
TurnContainer {
    height: auto;
    margin: 0;
}
TurnContainer > .turn-header {
    height: auto;
    layout: horizontal;
}
TurnContainer > .turn-header > .chevron {
    width: 2;
    color: $text-muted;
}
TurnContainer.collapsed > .turn-body { display: none; }
ToolStatusWidget.expandable .tool-icon { color: $accent; }
ToolStatusWidget > .tool-output-full {
    color: $text-muted;
    padding: 0 0 0 4;
    margin: 0;
}
ToolStatusWidget.collapsed-output > .tool-output-full { display: none; }
```

## 9. Risks

- **Visual snapshot churn.** Any change to the DOM tree breaks
  `pytest --snapshot-update`-style baselines. The migration intentionally
  *wraps* existing widgets rather than replacing them, so the visual output
  for the most-recent-two turns is byte-identical when collapsed turns are
  absent. Snapshots for `test_multi_turn_conversation` will need to be
  refreshed.
- **Focus management.** Clicking a chevron must not steal focus from the
  chat input. Mitigation: `can_focus = False` on the chevron and on
  `TurnContainer`; rely on event-bubbling.
- **AgentResponse rendering glitch.** Markdown widgets re-layout when their
  ancestor's size changes. Collapsing a previous turn shrinks the chat log
  but not the current turn — verified safe in the prototype.

## 10. Implementation plan

1. ✅ Build a standalone prototype (`scripts/widget_rendering_prototype.py`)
   that mounts a fake conversation and validates the collapse/expand and
   tool-peek behaviour.
2. ✅ Visually snapshot the prototype via a tiny pytest harness
   (`tests/test_widget_rendering_prototype.py`).
3. Land `TurnContainer` in `taui/tui/widgets/turn_container.py`.
4. Extend `ToolStatusWidget` with `set_full_output` + click handler.
5. Update `SessionState.turns`, `_mount_in_reply`, and `handle_input` in
   `taui/tui/app.py` to push assistant content into the active turn body.
6. Hook `_autocollapse_old_turns` into the turn-creation path.
7. Refresh visual snapshots and add one new snapshot test for the
   collapsed/expanded state across three turns.

## 11. Out of scope (future)

- A keyboard binding to fold all but the active turn (`Ctrl+\\` style).
- Per-turn copy-as-markdown action.
- Persisting fold state in `session_replay` so resumed sessions open with
  the same layout the user left them in.
