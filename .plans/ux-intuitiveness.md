# Making taui intuitive — a complete UX audit

This document enumerates every way taui can be made more intuitive to a user
who has just opened it for the first time, all the way up to a power user
who has been living in it for months. Each item has a priority level so we
can ship the high-leverage fixes first.

Priority legend:

- **P0** — broken or actively confusing today; first-run users hit it
- **P1** — high impact, matches user expectations from peer tools
- **P2** — discoverability and polish; reduces friction
- **P3** — power-user affordances and long-tail nice-to-haves

The audit is organized into eight surfaces: **first run**, **chat input**,
**keyboard**, **slash commands**, **command palette**, **sidebars and
panes**, **agent loop & approvals**, **sessions**, **tools & files**,
**status & feedback**, **theming**, **errors**, **configuration**, **help &
docs**, **extensions/skills/agents**, and **accessibility**.

---

## 1. First run

The first 60 seconds determine whether a user keeps the app open.

| # | Priority | Item |
|---|---|---|
| 1.1 | **P0** | Detect first run (no `~/.taui/`, no provider auth) and show a single welcome screen with three actions: *Sign in (Copilot)*, *Sign in (Codex)*, *Use locally with config file*. Today users have to know `--login`. |
| 1.2 | **P0** | If launched without auth, do not drop the user at a chat prompt that silently fails on send — print a clear inline call-to-action and a button to invoke `/login`. |
| 1.3 | **P1** | Show a 4–6 line "you can…" cheat sheet on the first session: `Enter` to send, `Ctrl+B` for sidebar, `/` for commands, `@` for files. Auto-dismiss on first interaction, never show again. |
| 1.4 | **P1** | Detect that the working directory is not a project root (no `.git`, no `pyproject.toml`/`package.json`) and surface a non-blocking banner: *"You're in $HOME — open a project with `taui -d <path>` for better results."* |
| 1.5 | **P1** | On first launch ship one starter `.taui/extensions/` example and one starter agent profile so users can see how customization looks without needing to read docs. |
| 1.6 | **P2** | A `taui --tour` flag that walks through sidebar / commands / approvals as an interactive demo backed by `tests/scenarios/scripted_provider.py`. |
| 1.7 | **P2** | Print the resolved provider + model + working dir on the first line of the chat log, so users can confirm they are in the right place before sending anything expensive. |
| 1.8 | **P3** | Detect terminals that don't forward `Super`/`Alt` correctly (Apple Terminal, some Windows shells) and show a one-time hint about enabling the keys taui relies on. |

---

## 2. Chat input — the place users actually live

`taui/tui/widgets/chat_input.py` already does a lot right (word/line nav,
history). Remaining gaps:

| # | Priority | Item |
|---|---|---|
| 2.1 | **P0** | Make the input border or caret color change visibly when the agent is **busy** vs **idle**. Today `Enter` does two completely different things (send vs steer) and the only cue is the footer text. |
| 2.2 | **P0** | When a user types `/` show the slash-command dropdown *immediately* with the same widget that the command palette uses, not as a separate completer surface. One mental model, not two. |
| 2.3 | **P1** | `@` completion should rank by **recently-touched files** first, then by `git ls-files`, then by raw FS walk. The current at-completer is mostly alphabetical. |
| 2.4 | **P1** | When the input contains an `@file` reference that does not resolve, underline it in red **before** submit, not after — silent ignores are confusing. |
| 2.5 | **P1** | Multi-line prompts: show line numbers in a thin gutter once the input exceeds 3 lines so users know where their cursor is. |
| 2.6 | **P1** | Paste handling: when a large block is pasted (>500 chars), automatically collapse it into a `[pasted 4.2 KB · click to expand]` chip — keeps the input scannable. The `pasted_content.py` screen already exists; wire it into the inline input. |
| 2.7 | **P2** | Persistent draft: if the user closes the tab/session with text in the input, restore it on reopen of the same session. |
| 2.8 | **P2** | History: `Up`/`Down` already navigate; add fuzzy reverse-search bound to `Ctrl+R` *only when input is empty* (avoid clashing with the info-sidebar toggle). If input has text, `Ctrl+R` stays the sidebar toggle. |
| 2.9 | **P2** | Visible token counter next to the prompt while typing so the user can sense how big their message is before it costs money. |
| 2.10 | **P3** | Smart enter: if the input ends with an unclosed code fence or open bracket, `Enter` inserts a newline; otherwise it sends. Removes the constant `Shift+Enter`/`Enter` confusion. |
| 2.11 | **P3** | Slash command argument hints inline (`/model copilot ▮claude-…`) the same way fish shell does it. |

---

## 3. Keyboard

App-level bindings live in `TauiApp.BINDINGS` at `taui/tui/app.py:424`. The
existing set is fine; the problems are **consistency**, **discoverability**,
and **conflicts**.

### 3.1 Conflicts to resolve

| # | Priority | Item |
|---|---|---|
| 3.1.1 | **P0** | `Ctrl+C` does three different things depending on state (cancel request, cancel approval, copy selection in some terminals). Document and enforce a single semantic: *cancel anything in flight; never quit*. Quit is only `Ctrl+Q` / `Ctrl+D` double. |
| 3.1.2 | **P0** | `Ctrl+R` collides with reverse-history-search muscle memory. Either rebind to `Ctrl+I` for info, or apply the conditional rule from §2.8. |
| 3.1.3 | **P1** | `Alt+Left/Right` for pane focus conflicts with word-cursor movement on the input. The current code already routes correctly when input is focused, but the footer should say *"Alt+←/→ word"* when input is focused and *"Alt+←/→ pane"* otherwise. |
| 3.1.4 | **P2** | `Ctrl+PageUp/Down` for tab switching is hard to reach. Add `Ctrl+Tab` / `Ctrl+Shift+Tab` and `Cmd+{`/`Cmd+}` mirrors when the terminal forwards them. |

### 3.2 Missing bindings users expect

| # | Priority | Item |
|---|---|---|
| 3.2.1 | **P1** | `Ctrl+K` — opens the command palette. Universal across VS Code/Slack/Linear and zero cost to add. |
| 3.2.2 | **P1** | `Ctrl+P` — opens the file/`@` picker as a modal. Mirrors VS Code "go to file". |
| 3.2.3 | **P1** | `Ctrl+L` — clear the visible chat log (does not delete events from the store). |
| 3.2.4 | **P1** | `Ctrl+/` — focus the input from any pane. |
| 3.2.5 | **P2** | `?` (when input is empty) — opens the hotkeys overlay. |
| 3.2.6 | **P2** | `g g` / `G` — top / bottom of the chat scroll (vim-style) when the scroll pane has focus. |
| 3.2.7 | **P2** | `Ctrl+S` — save/export current session as markdown (`/export` exists, just bind it). |
| 3.2.8 | **P2** | `Ctrl+,` — open settings/config. |
| 3.2.9 | **P3** | `Ctrl+Shift+P` mirror of `Ctrl+K` for users coming from VS Code. |

### 3.3 Universal rules

| # | Priority | Item |
|---|---|---|
| 3.3.1 | **P1** | Every binding shown in `/hotkeys` must also appear in the footer at the moment it is actually usable. Footer is real estate; populate it contextually. |
| 3.3.2 | **P1** | `Escape` should always work the same way: *pop the topmost dismissible thing* (modal → completion → mode → defocus). It almost does today; audit every screen for `action_escape` coverage. |
| 3.3.3 | **P2** | A keymap file at `~/.taui/keymap.toml` so users can rebind anything. Several users have asked for this in similar tools; building it in early is cheap. |

---

## 4. Slash commands

Registered in `taui/commands/builtins.py:863`. Solid coverage, but the **UX
around them** is where most friction lives.

| # | Priority | Item |
|---|---|---|
| 4.1 | **P0** | Every command should show its usage on `/<command> ?` (or `--help`). Several commands today either silently no-op or print a one-line error when args are wrong. |
| 4.2 | **P0** | Aliases should appear in the dropdown next to their canonical command, not as separate entries (`/h` listed below `/help` with the same description currently feels duplicated). |
| 4.3 | **P1** | Group commands by purpose in the help screen: *Session*, *Models & agents*, *Customize*, *Context*, *Git*, *Debug*. The flat list grows past discoverability. |
| 4.4 | **P1** | Confirm-before-destruct on `/clear`, `/new` (when conversation has unsent state), `/logout`. A typed `y/n` is enough. |
| 4.5 | **P1** | `/model` and `/provider` should land on a *picker UI*, not just text output. Pickers already exist (`taui/tui/screens/model_picker.py`); route the bare command to them. |
| 4.6 | **P1** | `/sessions` should open the picker too (`session_picker.py`). Today `/sessions` and `Ctrl+B` show different surfaces of the same data — pick one canonical view. |
| 4.7 | **P2** | `/cost` should render a small inline panel with totals + per-model breakdown + remaining budget, not just a number. |
| 4.8 | **P2** | `/compact` should preview what will be removed and require confirmation if it would lose >X% of context. Today it just runs. |
| 4.9 | **P2** | `/i` rename: `/edit` (mode) or `/customize` reads more naturally than the abbreviation. Keep `/i` as an alias for users who learned it. |
| 4.10 | **P2** | Add `/undo` that reverts the last tool side-effect when reversible (writes/edits with stored before-state). |
| 4.11 | **P3** | Add `/share` to publish a session as a read-only artifact (a static HTML render of the SQLite stream). |
| 4.12 | **P3** | Allow user-defined `/<name>` aliases in `~/.taui/aliases.toml` that expand to a prompt template — power users love this in Aider/Claude Code. |

---

## 5. Command palette

CSS for `CommandPalette` is already defined in `taui/tui/app.py:382`-ish.
Treat it as a first-class entry point.

| # | Priority | Item |
|---|---|---|
| 5.1 | **P0** | Bind `Ctrl+K` (and `Cmd+K` where forwarded) to open it from anywhere. Currently there is no global shortcut. |
| 5.2 | **P1** | Palette should search across **commands**, **sessions**, **agents**, **files**, and **skills** — one fuzzy box. Distinguish results with a prefix glyph (▶ command, ◧ session, ⌥ agent, ⌘ file, ★ skill). |
| 5.3 | **P1** | Recent-first ranking with a small "you just used this" boost. |
| 5.4 | **P2** | Show the keybinding (if any) on the right side of each entry — teaches shortcuts passively. |
| 5.5 | **P2** | Allow `>` prefix to scope to commands only, `@` to files, `#` to sessions — same scoping convention as VS Code. |
| 5.6 | **P3** | Allow extensions to register palette providers (e.g. a search-issues provider for a Linear extension). |

---

## 6. Sidebars and panes

Left sidebar = sessions/files (`sidebar.py`). Right = info (`info_bar.py`,
`info2.py`). Layout already supports two panes.

| # | Priority | Item |
|---|---|---|
| 6.1 | **P0** | First-launch the left sidebar should be **collapsed** if the terminal is narrow (<120 cols), expanded otherwise. Cramming both sidebars on an 80-col terminal makes the chat unusable. |
| 6.2 | **P0** | The sidebar tab strip (Sessions/Files) is not obviously interactive. Make the active tab use the primary color + underline, inactive tabs dimmed; add `Tab`/`Shift+Tab` to switch within the sidebar. |
| 6.3 | **P1** | Session rows should show the **agent color** indicator (already computed in `info_bar.AGENT_COLORS`) so users see at a glance which profile each session belongs to. |
| 6.4 | **P1** | A drag-resize affordance on the sidebar divider, plus keyboard resize (`Ctrl+Alt+←/→` when focused). |
| 6.5 | **P1** | Right info panel should be **layered**: top = provider/model/tokens, middle = current tool status (live), bottom = pinned context summary. Today information is dense and undifferentiated. |
| 6.6 | **P1** | Make the context meter update in near real time as tokens stream — already listed in `todo.md:3`. Animate the bar; never let it visibly lag. |
| 6.7 | **P2** | A "what's in my context" toggle that highlights the chat messages that are inside the next-turn context vs the ones that compaction will drop. |
| 6.8 | **P2** | Files tab should support: pin to top, recently-modified sorting, hidden-file toggle, and a small badge showing files already referenced via `@`. |
| 6.9 | **P3** | A third optional pane for an embedded terminal (`widgets/terminal.py` already exists) so users don't have to context-switch out of taui. |

---

## 7. Agent loop, approvals, and questions

The agent loop is correct; the **perception** of what's happening can be
improved a lot.

| # | Priority | Item |
|---|---|---|
| 7.1 | **P0** | Fix tool/thought ordering (listed in `todo.md:2`). When reasoning streams and a tool call arrives, render them in true temporal order, not in two parallel streams that visually interleave wrong. |
| 7.2 | **P0** | Approval prompts should never look like ordinary assistant output. Wrap them in a colored border, anchor them to the bottom-of-view, and steal focus. Today's inline approval can scroll off screen. |
| 7.3 | **P0** | Questions should be inline panels with focused input, not notification toasts (matches `todo.md:1`). |
| 7.4 | **P1** | Show a one-line "what the agent is doing right now" status above the input. Examples: *"reading 3 files"*, *"running bash: pytest -q"*, *"thinking…"*. Reduces the "is this thing alive?" anxiety. |
| 7.5 | **P1** | Steering vs queue is currently distinguished only by `Enter` vs `Alt+Enter`. Add a visible chip in the input area when the agent is busy: `▷ steer` and a second pill `▷+ queue (alt+enter)`. |
| 7.6 | **P1** | Cancel feedback: when `Ctrl+C` cancels, render a single visible *"cancelled"* line in the chat, not just a silent return to idle. |
| 7.7 | **P1** | Approval should show: tool name, parameters with diff-style highlights of dangerous fields (paths outside cwd, network URLs), and three buttons: **Allow once / Allow always (project) / Deny**. The persistent-allow path already exists; surface it as a first-class choice not a follow-up modal. |
| 7.8 | **P2** | Tool output that is large (>50 lines) should auto-fold with a `[+ 312 lines]` chip and `o` to open in pager. |
| 7.9 | **P2** | Reasoning blocks should be collapsible per turn, with a global setting *"show reasoning by default"*. |
| 7.10 | **P2** | Visually distinguish *sub-agent* turns from main-agent turns (color the gutter with the sub-agent's color). |
| 7.11 | **P3** | Slow-tool warning: if a tool has been running >30s, show an inline *"still running… [c] cancel"*. |

---

## 8. Sessions and tabs

Sessions live in SQLite at `.taui/store.db`. The tab bar exists
(`session_tab_bar.py`).

| # | Priority | Item |
|---|---|---|
| 8.1 | **P0** | Auto-name new sessions from the first user message after the first agent response — never show a session called *(unnamed)* once it has content. The fallback exists in `sidebar._fallback_name`; promote the description as soon as it's available. |
| 8.2 | **P1** | A visible "session has unsaved changes / dirty buffers" indicator if a tool modified files. Not blocking, just a dot. |
| 8.3 | **P1** | `Ctrl+W` to close the current tab with a confirmation if there is queued/streaming work. |
| 8.4 | **P1** | Resume across reboots: if `taui` is relaunched in the same working dir, default to *resume most recent session*, with a flag/setting to always start new. |
| 8.5 | **P2** | Right-click / context menu on a session row: rename, duplicate, delete, export, copy id. Today only delete is reachable via command. |
| 8.6 | **P2** | Pin sessions to keep them at the top of the sidebar across compaction-by-time. |
| 8.7 | **P2** | Search sessions: a `/` shortcut inside the sidebar filters the session list by description and first-message contents. |
| 8.8 | **P3** | Branching: "fork from here" on any turn — creates a new session sharing the prefix, useful when exploring alternatives without spoiling the main session. |

---

## 9. Tools, files, and permissions

| # | Priority | Item |
|---|---|---|
| 9.1 | **P0** | When a tool is denied by policy, the agent receives a `ToolResult.fail`; users see nothing helpful. Add a visible *"you denied this tool — agent will work around it"* line so the user understands what happened. |
| 9.2 | **P0** | Permission DSL today supports per-pattern rules but the **error messages** when a pattern doesn't match are opaque. Show the matching rule in the approval panel: *"this fell through to default `ask`"*. |
| 9.3 | **P1** | The two-scope tool policy (project + global) is confusing per `todo.md:4`. Consider: one scope by default, with an opt-in *advanced* toggle to split. Or rename the scopes to *this project* vs *all projects* — concrete language always wins. |
| 9.4 | **P1** | File writes should show a diff preview in the approval, not just the path + content size. The `git_diff.py` screen already renders diffs. |
| 9.5 | **P1** | `bash` approval should explicitly call out side effects: writes to `$HOME`, network, sudo, `rm`, package managers. Static analysis of the command line is enough. |
| 9.6 | **P2** | Tool catalog viewer (`/tools`) that lists every registered tool with description, current policy, and toggle. |
| 9.7 | **P2** | Per-session tool overrides: temporarily switch a tool to `allow`/`deny` for *just this session* without writing to disk. |
| 9.8 | **P3** | "Recent tool calls" sidebar tab — replay a tool call (deterministic ones like `read`) for inspection. |

---

## 10. Status, feedback, and footer

The footer at `taui/tui/widgets/footer.py` already adapts to busy state.

| # | Priority | Item |
|---|---|---|
| 10.1 | **P0** | The status bar must always tell the user three things at a glance: **provider/model**, **token usage / context %**, **agent state** (idle / thinking / running tool / awaiting approval). Half of these are scattered today. |
| 10.2 | **P1** | Footer chip colors: green when idle, amber when busy, red when awaiting approval. Color is faster than reading. |
| 10.3 | **P1** | Spinner copy should be honest: *"thinking…"*, *"reading 4 files…"*, *"running bash…"* — the `spinner.py` widget already exists; feed it the current activity from the loop. |
| 10.4 | **P1** | Bell / OSC 9 / `terminal-notifier` on **approval needed** and **turn complete** when the terminal is unfocused (`self._window_focused` is already tracked). |
| 10.5 | **P2** | A subtle progress bar at the very top edge of the chat pane when the model is streaming — gives a sense of "we are alive". |
| 10.6 | **P2** | Cost meter co-located with token meter; clicking either opens `/cost`. |
| 10.7 | **P3** | Sparkline of tokens-per-turn over the last 10 turns — helps users see when a session is bloating. |

---

## 11. Theming and visuals

| # | Priority | Item |
|---|---|---|
| 11.1 | **P1** | Detect dark vs light terminal at startup (query `COLORFGBG` or background OSC) and pick the corresponding theme. Today it always starts dark. |
| 11.2 | **P1** | High-contrast theme for accessibility. |
| 11.3 | **P2** | `/theme` command with live preview. |
| 11.4 | **P2** | Consistent semantic colors: success/warn/error/info/muted defined once, used everywhere. Right now hex literals are scattered across widgets (e.g. `#3fb950`, `#6e7681`). |
| 11.5 | **P2** | Avoid double borders inside dense panels — collapse to one. |
| 11.6 | **P3** | A truecolor fallback path that degrades gracefully on 256-color terminals. |

---

## 12. Errors and recovery

| # | Priority | Item |
|---|---|---|
| 12.1 | **P0** | Auth expiry today surfaces as a generic provider error; route it to a dedicated banner with a *"Re-authenticate"* button that invokes `/login`. |
| 12.2 | **P0** | Rate-limit errors should be visible, not just rolled into a generic failure. Show the retry window and an *"Auto-retry in 14s"* countdown. |
| 12.3 | **P1** | Context-overflow recovery (`context_overflow_then_recover` scenario exists) should be visible: the user should see *"context too big — compacted automatically"* not silent shrinkage. |
| 12.4 | **P1** | Crash recovery: if a session crashed mid-tool, on relaunch offer to *Resume* / *Discard partial turn* / *View error*. |
| 12.5 | **P2** | A `/diag` command that prints provider connectivity, model availability, store path, extension load errors. |
| 12.6 | **P3** | Send-error feedback inside the input: if the message couldn't be sent, leave it in the input with an error tooltip rather than losing it. |

---

## 13. Configuration

`taui/config.py:33`. TOML, multi-file. Good foundation.

| # | Priority | Item |
|---|---|---|
| 13.1 | **P1** | Show the **effective resolved config** somewhere users can read it (`/config` or a screen). Today users can't easily tell which file won. |
| 13.2 | **P1** | A `/set` command for transient overrides — toggles a value at runtime (`/set verbose_tools true`) without editing files. |
| 13.3 | **P1** | When a config file fails to parse, show a non-fatal banner with the line and column; don't silently fall back to defaults. |
| 13.4 | **P2** | A scaffolded `.taui/config.toml` written on first project-mode launch with sensible defaults, commented-out examples, and a link to the docs. |
| 13.5 | **P2** | Env-var-to-config mapping (`TAUI_PROVIDER`, `TAUI_MODEL`) documented in one place. |
| 13.6 | **P3** | Hot reload of config without restart — `/reload` already reloads extensions; extend it. |

---

## 14. Help and discoverability

| # | Priority | Item |
|---|---|---|
| 14.1 | **P0** | `/help` should default to a *getting-started* layout, not a flat command list. Two columns: *I want to…* (do thing) → *try this* (command/shortcut). |
| 14.2 | **P1** | Contextual help: pressing `?` while a modal is open shows help for that modal, not the global help. |
| 14.3 | **P1** | Every error message that references a command should hyperlink (OSC 8) to that command — many terminals will let users click it. |
| 14.4 | **P2** | A `/tutorial` that runs a 5-step scripted scenario inside the real TUI (use the existing scenario harness). |
| 14.5 | **P2** | Inline tips: rotate one short tip per startup, dismissable forever. *"Did you know `@dir/` pulls in a folder?"* |
| 14.6 | **P3** | Telemetry-free heuristic that watches for patterns (e.g. user always types `/model` after `/sessions`) and suggests a chord. Strictly local. |

---

## 15. Extensions, skills, agents

These are taui's superpower — they should feel like a first-class part of
the UI, not a config-file thing.

| # | Priority | Item |
|---|---|---|
| 15.1 | **P1** | Sidebar tab *Extensions* that lists loaded extensions with status (ok/error), source path, and an enable/disable toggle that writes a per-project override file. |
| 15.2 | **P1** | Skills picker on `/skills` (or `Ctrl+J`) that shows discovered skills and lets the user pin one to the next turn. |
| 15.3 | **P1** | Agent picker (`/agents` already exists) should preview the agent's system prompt, tools, color, and recent sessions. |
| 15.4 | **P2** | One-click *"create extension from this conversation"* — bundles the last few user/assistant turns into a self-edit-mode prompt that produces a `.taui/extensions/*.py` file. |
| 15.5 | **P2** | A live console for extension `stdout`/`stderr` so misbehaving extensions are visible, not silent. |
| 15.6 | **P3** | Marketplace-style discovery: `/extensions search <q>` that fetches a curated index. Out of scope for v0.6 but worth marking. |

---

## 16. Accessibility and inclusivity

| # | Priority | Item |
|---|---|---|
| 16.1 | **P1** | All color-coded states must also be distinguishable by **shape or text** (●/○ already used for active session — apply consistently to busy/idle/error). |
| 16.2 | **P1** | Screen-reader friendly: every widget that conveys state should expose a textual label (Textual supports this; audit each custom widget). |
| 16.3 | **P1** | Avoid relying on `Alt`/`Super` shortcuts alone. Provide a `Ctrl`-based fallback for every essential action — many terminals don't forward modifier-rich keys. |
| 16.4 | **P2** | Font-size-aware layout: don't hard-code `_ROW_WIDTH = 32`; compute from sidebar width. |
| 16.5 | **P2** | Reduced-motion mode that disables the spinner/animation. |
| 16.6 | **P2** | i18n-ready: extract user-facing strings into a single place. Even if only English ships, this clears the path. |

---

## 17. Performance & responsiveness

Perceived intuitiveness is largely perceived latency.

| # | Priority | Item |
|---|---|---|
| 17.1 | **P1** | Render the first stream token within ~50ms of receipt — measure end-to-end via the scenario harness. |
| 17.2 | **P1** | The context meter, cost meter, and footer must never block the input. Update them off the input's render path. |
| 17.3 | **P2** | Sidebar session list should virtualize after ~100 sessions. |
| 17.4 | **P2** | Avoid full-tree re-renders on every event; diff and patch. |

---

## 18. The single biggest intuition wins (top 10)

If only ten items shipped, these would move the needle most:

1. **P0** First-run welcome screen with one-click sign-in (1.1, 1.2)
2. **P0** Visible busy/idle distinction on the input + clear cancel feedback (2.1, 7.6, 10.1)
3. **P0** Approvals as anchored modals, not scrolling inline output (7.2)
4. **P0** Questions as inline panels, not toasts (7.3, matches `todo.md:1`)
5. **P0** Fix tool/thought ordering (7.1, matches `todo.md:2`)
6. **P0** Real-time context meter (6.6, matches `todo.md:3`)
7. **P1** `Ctrl+K` command palette as a unified entry point (3.2.1, §5)
8. **P1** Pickers (model, provider, sessions, agents) instead of text-only outputs (4.5, 4.6)
9. **P1** Sidebar collapsed by default on narrow terminals (6.1)
10. **P1** Auto-name sessions immediately after first response (8.1)

---

## Cross-cutting principles

A few rules that, if applied consistently, prevent regressions:

- **One mental model per surface.** If `/sessions` and `Ctrl+B` show
  sessions, they must show the *same* view. Two views of the same data is
  two things to learn.
- **Visible state changes.** Anything that changes behavior of a key
  (idle→busy on `Enter`) must change something visible at the same moment.
- **Cancel is sacred.** `Esc` and `Ctrl+C` always cancel the smallest thing
  in flight, never quit, never lose work.
- **Destructive actions confirm once.** Approvals, deletions, logouts.
- **Don't hide errors.** Every silent fallback is a future bug report.
- **Customization is a feature, not a fallback.** The self-edit / extension
  path should be visibly inviting, not buried.
- **Trust the terminal width.** Adapt layouts; never overflow horizontally.
