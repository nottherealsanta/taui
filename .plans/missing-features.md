# Missing Features in Taui

Comparison of important features from `tmp/claude-code`, `tmp/opencode`, and
`tmp/pi` that are not yet present in taui, with rationale and concrete
integration notes for each.

Priority tags:

- **P0** — core capability gaps; ship-blocking for parity with peer agents
- **P1** — high-value features users notice quickly
- **P2** — quality-of-life / power-user features
- **P3** — niche, experimental, or product-specific

Each entry has three parts:

1. **Where it lives** in the reference codebases
2. **Why it's useful and valuable** — the user/product benefit
3. **How to integrate with taui** — concrete files, registries, and event hooks

The taui anchors used throughout:

- Composition root: `taui/session.py:139`
- Agent loop: `taui/agent/loop.py:93`
- Event store: `taui/store/store.py:97`, `taui/store/events.py:10`
- Tool registry / executor: `taui/tools/registry.py:10`, `taui/tools/executor.py:42`
- Tools dir: `taui/tools/builtins/`
- Commands: `taui/commands/builtins.py:858`, `taui/commands/registry.py`
- TUI: `taui/tui/app.py:206`, widgets in `taui/tui/widgets/`, screens in
  `taui/tui/screens/`
- Extensions: `taui/extensions/__init__.py:66`
- Permissions: `taui/permissions.py:38`
- Sandbox: `taui/sandbox.py`
- Skills: `taui/skills/__init__.py:91`

---

## P0 — Core Capability Gaps

### 1. Plan mode (read-only / propose-then-execute)

**Where it lives**

- claude-code: `src/tools/EnterPlanModeTool`, `src/tools/ExitPlanModeTool`,
  `src/commands/plan/`
- opencode: `packages/opencode/src/tool/plan.ts`, `plan-enter.txt`,
  `plan-exit.txt`

**Why it's useful and valuable**

Plan mode is the single biggest trust-builder in modern coding agents. The agent
explores the codebase, drafts a step-by-step plan, and presents it to the user
*before* a single mutating tool runs. The user reads the plan, redirects if it's
wrong, and only then is the agent allowed to write files or run bash. This
collapses two big risk classes that plague unconstrained agents: silent scope
creep ("I also refactored your auth layer") and wasted tool budget on the wrong
approach. For complex tasks, the plan also doubles as a commit-message draft and
a review artifact.

Plan mode is also a primitive that other features build on: ultraplan, autofix
loops, and review/security-review commands are all variants of "produce a plan,
gate it, then execute or hand off."

**How to integrate with taui**

- Add a new session-level mode flag on `Session` (alongside the existing
  self-edit mode): `Session.mode: Literal["build", "plan"]`.
- In `taui/tools/executor.py:42`, short-circuit any tool whose `category` is in
  `{WRITE, EDIT, BASH, MUTATE}` while `session.mode == "plan"`, returning
  `ToolResult.fail("blocked by plan mode")`. Read-only tools (`read`, `grep`,
  `glob`, `repo_overview`, `lsp`, `webfetch`, `question`) stay enabled.
- Two new builtin tools in `taui/tools/builtins/`: `plan_enter.py` and
  `plan_exit.py`. `plan_exit` takes the full plan as an argument, persists it
  via a new `EventType.PLAN` event in `taui/store/events.py:10`, prompts the
  user for approval through the existing `ApprovalController`
  (`taui/tui/approval_controller.py`), and flips the mode back to `build`.
- Slash command `/plan [message]` in `taui/commands/builtins.py:858` enters
  plan mode and sends the initial prompt.
- TUI: a banner in `taui/tui/widgets/status_bar.py` showing "PLAN MODE" in a
  distinct color; reuse `theme.py` accent.
- Bundle a system-prompt overlay loaded by `taui/prompt_builder.py` when mode is
  `plan` (e.g. `prompts/plan_mode.md`) instructing the model to call
  `plan_exit` rather than mutating tools.

---

### 2. Background / long-running tasks

**Where it lives**

- claude-code: `TaskCreateTool`, `TaskGetTool`, `TaskListTool`, `TaskOutputTool`,
  `TaskStopTool`, `TaskUpdateTool`, `hooks/useTasksV2.ts`,
  `useBackgroundTaskNavigation.ts`
- opencode: `packages/opencode/src/background/job.ts`

**Why it's useful and valuable**

A coding agent's biggest dead time is waiting on slow operations: test suites,
builds, deploys, large refactors. Background tasks let the agent fire off a
sub-agent, keep the foreground conversation responsive, and return when the job
finishes (with a notification). This unlocks three patterns:

1. **Parallel sub-tasks**: "fix all three failing tests in parallel" instead of
   sequentially.
2. **Long polls**: "watch the CI run and tell me when it goes green."
3. **Speculative work**: "while we discuss the API, draft the migration in the
   background."

Without it, the user is blocked staring at a spinner, or the agent fakes
progress.

**How to integrate with taui**

- New module `taui/tasks/` with `TaskManager` that owns an asyncio task pool.
  Each task is a `Session` sub-instance running in a child task, sharing the
  parent's store but with its own `stream_id`.
- Persist tasks as a new `EventType.TASK` event on the parent stream so they
  survive restarts. State transitions (`queued → running → done/failed`) emit
  `EventType.STATE_CHANGE` on the child stream.
- Six new tools in `taui/tools/builtins/tasks/`: `task_create`, `task_get`,
  `task_list`, `task_output`, `task_stop`, `task_update`. These wrap
  `TaskManager` calls. They are sub-agent-dispatch tools, mirroring the
  existing `sub_agent.py` but async/non-blocking.
- TUI: a "Tasks" sidebar pane (extend `taui/tui/widgets/sidebar.py`) showing
  live task list, status, last output line. Reuse `tool_status.py` rendering.
- Notification hook: when a task transitions to `done`, fire a hook through
  `taui/hooks.py` so extensions (or a desktop-notify extension) can surface it.
- Slash command `/tasks` to list/inspect; `/task stop <id>` to cancel.
- Cancellation: the existing `Ctrl+C` cancel flow already cancels the active
  request; extend `taui/tui/app.py` to route cancellation to a specific task id.

---

### 3. Worktree management

**Where it lives**

- claude-code: `EnterWorktreeTool`, `ExitWorktreeTool`
- opencode: `packages/opencode/src/worktree/`

**Why it's useful and valuable**

Worktrees give the agent a sandboxed copy of the repo on a fresh branch without
disturbing the user's working state. This is the right substrate for two
common scenarios:

1. **Risky multi-file refactors** — bail out by deleting the worktree, no
   `git stash` dance.
2. **Parallel sub-agents** — each background task gets its own worktree so
   they don't fight over the index or scratch files.

It also turns "let me try an approach" into a cheap operation. Users approve
risky work more readily when they know it's quarantined.

**How to integrate with taui**

- New module `taui/worktree.py` wrapping `git worktree add/remove` via
  `asyncio.create_subprocess_exec`. Worktrees live under
  `~/.taui/worktrees/<session_id>/<branch>/`.
- Two tools in `taui/tools/builtins/worktree.py`: `worktree_enter(branch,
  base)` and `worktree_exit(keep: bool)`. `worktree_enter` rebinds the
  session's `cwd` for subsequent tool calls; `worktree_exit` either merges back
  or deletes.
- Track worktree state on `Session`: `Session.worktree: WorktreeHandle | None`.
  `taui/tools/executor.py` passes `worktree.cwd if worktree else session.cwd`
  as the working directory to every tool.
- Persist the handle as `EventType.WORKTREE` so resumes (`--session`) restore
  the cwd.
- TUI: badge in `status_bar.py` showing the active worktree branch; warn on
  exit if the worktree has uncommitted changes.
- Permissions: add a `worktree` policy in `Config.tool_policy` (default
  `confirm`) since this touches git state.

---

### 4. Rewind / checkpoint / snapshot

**Where it lives**

- claude-code: `src/commands/rewind/`, `hooks/useFileHistorySnapshotInit.ts`
- opencode: `packages/opencode/src/snapshot/index.ts`

**Why it's useful and valuable**

The agent loop already has every prompt and every tool call durably stored —
but the *files on disk* drift forward irreversibly. Rewind closes that loop:
snapshot affected files before each mutating tool, and let the user roll back
to "right before turn N" with one command. This is the difference between an
agent you trust to write code unattended and one you have to babysit.

The snapshot store also makes diff views, undo-of-undo, and "show me what the
agent changed" trivial — features that pile on top once the substrate exists.

**How to integrate with taui**

- New `taui/snapshot.py` using a content-addressed blob store under
  `~/.taui/snapshots/<session_id>/`. Each blob is a gzipped copy keyed by sha1.
  Snapshots persist a mapping `{turn_id: {path: sha1}}`.
- Hook into the existing `taui/tools/file_tracker.py`: every file the tracker
  marks as "about to be written" gets snapshotted *before* the write. This
  centralizes the trigger and avoids per-tool wiring.
- New `EventType.SNAPSHOT` records `{turn_id, paths_changed, blob_refs}`.
- Slash command `/rewind [N]` (or `/rewind <turn_id>`): reads the snapshot
  manifest, restores files, appends a `SYSTEM_MESSAGE` event noting the rewind,
  and re-projects the stream so the TUI shows the truncated state.
- TUI: integrate with `taui/tui/screens/git_diff.py` to show "what would be
  restored" before confirming.
- Defaults: only snapshot files inside `session.cwd` and under a size cap
  (e.g. 1 MB) to keep the store bounded.

---

### 5. Scheduled / cron agents

**Where it lives**

- claude-code: `ScheduleCronTool`, `useScheduledTasks.ts`,
  `src/commands/teleport/`

**Why it's useful and valuable**

Some agent jobs are inherently periodic: "every 10 min, check if my PR's CI
passed", "every morning, summarize new issues", "before each commit, run
review." Without scheduling, the user has to manually re-trigger or leave a
shell loop running. With scheduling, the agent becomes ambient — it works
while the user is away and surfaces results in the next session.

This also opens the door to event-triggered runs (file watcher, webhook, git
hook) once the scheduling abstraction exists.

**How to integrate with taui**

- New `taui/scheduler.py` with a small cron-like daemon that runs alongside
  the TUI (asyncio task started in `Session.create()`). Use croniter for parsing.
- Schedules persist in a new SQLite table next to `events`
  (`taui/store/store.py`): `schedules(id, cron_expr, prompt, agent, next_run)`.
- Two builtin tools: `schedule_create(cron, prompt, agent?)` and
  `schedule_delete(id)`; a `/schedules` slash command lists/edits.
- On fire, spawn a background task (reusing the Tasks system above) and route
  its result to a "Notifications" pane in the TUI.
- For long-running TUI sessions only: optionally write a `launchd` plist /
  systemd unit so schedules survive when taui isn't open. Gate behind an
  explicit opt-in command (`/schedule install-daemon`) to keep installs clean.

---

### 6. Headless / server / SDK mode

**Where it lives**

- opencode: `packages/opencode/src/server/server.ts`, `server/routes/`, `sdks/`,
  `acp/`
- pi: `packages/coding-agent/src/modes/rpc/`, `modes/print-mode.ts`
- claude-code: `src/bridge/`, `src/remote/`

**Why it's useful and valuable**

Taui's TUI-only stance is great for the primary user, but it locks out three
audiences who otherwise drive serious adoption:

1. **CI / automation** — "run this prompt non-interactively, exit with the
   diff" enables agents in pipelines.
2. **IDEs / external UIs** — VS Code panels, Slack bots, in-house tools all
   need a programmable surface.
3. **Power users scripting taui** — Bash pipelines like `taui run -p "fix
   lints" --json | jq`.

Even a minimal `--print` one-shot mode covers most of (1), and a local HTTP/JSON
server covers (2) and (3) without compromising the TUI's primacy.

**How to integrate with taui**

- **Print mode** (smallest, do first): add `taui --print "prompt"` to
  `main.py:29`. It instantiates `Session` exactly like the TUI but drives the
  loop directly without `TauiApp.run()`, streaming JSON events to stdout.
  Exit code reflects success/error. Tool approvals default to deny unless
  `--allow-tool foo` flags are passed.
- **Local server**: new `taui/server.py` exposing `aiohttp` routes:
  `POST /sessions`, `POST /sessions/{id}/messages`, `GET /sessions/{id}/events`
  (SSE), `POST /sessions/{id}/approvals/{tool_call_id}`. Reuse `Session` and
  the store directly. Bind to `127.0.0.1:<port>` by default; require a session
  token in `Authorization`.
- **SDK**: a thin Python client in `taui/sdk.py` plus a TypeScript client
  generated from event schemas. The Python TUI can use the same client for
  testing.
- All three modes share `Session.send()` and the event stream — there is no
  parallel runtime, which keeps the invariants documented in `docs/taui.md`
  intact.

---

### 7. Plugin / marketplace system

**Where it lives**

- claude-code: `src/commands/plugin/` (BrowseMarketplace, DiscoverPlugins,
  ManageMarketplaces, PluginTrustWarning, ValidatePlugin, …)
- opencode: `packages/plugin/`, `packages/opencode/src/plugin/`

**Why it's useful and valuable**

Taui already supports Python extensions under `~/.taui/extensions/`, but
distribution is hand-rolled (clone, copy, restart). A marketplace converts
extensions from "things you write" into "things you install." Three orders of
magnitude more users will *use* an extension than will *author* one.

The marketplace also forces good hygiene: signed manifests, declared
permissions, trust prompts on first run, version pinning. These are exactly the
guardrails an agent-extending system needs.

**How to integrate with taui**

- Use the existing extension API as the runtime surface; add a thin packaging
  layer on top:
  - `taui-extension.toml` manifest: `{name, version, entry, permissions,
    homepage, signature}` lives at the root of each extension.
  - Distribution via PyPI (`pip install taui-ext-foo`) and/or a static JSON
    index URL (`marketplace.taui.dev/index.json`) configurable in
    `taui/config.py`.
- New CLI surface: `taui ext list / search / install / uninstall / enable /
  disable`. Implementations live in `taui/extensions/marketplace.py`; reuse
  the loader at `taui/extensions/__init__.py:169`.
- TUI: new `/plugins` screen in `taui/tui/screens/` showing installed +
  available, with trust-warning modal on first enable (mirrors permission
  approval flow).
- Validation: on install, parse the manifest, refuse extensions that request
  permissions outside their declared list, sandbox imports via a restricted
  runpy environment.
- Out of scope at v1: a hosted index. Start with a static JSON URL the user
  can override; ship a curated set of first-party extensions.

---

### 8. Web search tool

**Where it lives**

- claude-code: `src/tools/WebSearchTool`
- opencode: `packages/opencode/src/tool/websearch.ts`,
  `tool/mcp-websearch.ts`

**Why it's useful and valuable**

`webfetch` (already in taui) requires the agent to know the URL. Real coding
questions don't start with a URL — they start with "how do I do X in
framework Y, version Z?" The agent needs a way to find the right page, then
fetch it. Without search, the agent hallucinates API signatures or asks the
user to paste docs.

Beyond docs lookups, web search powers: dependency vulnerability checks, error
message lookups, release-notes diffs, latest-version queries. It's the single
biggest "the agent knows current information" upgrade.

**How to integrate with taui**

- New tool `taui/tools/builtins/websearch.py` with pluggable backends:
  - SerpAPI / Brave / Tavily as primary (require API key in
    `~/.taui/credentials/`)
  - DuckDuckGo HTML scrape as zero-config fallback
  - Optional: MCP-backed search (mirroring opencode's `mcp-websearch.ts`) so
    users can wire their own provider through MCP.
- Result shape: `{title, url, snippet}[]` with a small top-K (5–10). Agent
  follows up with the existing `webfetch` to read full pages.
- Permission: gated by a new policy `Config.tool_policy.websearch` with default
  `allow` (it's read-only and outbound, but no local effect).
- Privacy note in docs: search queries leave the machine — surface this in the
  first-run onboarding (see Feature 21).

---

## P1 — High-Value Gaps

### 9. Output styles (persona / response shape)

**Where it lives**

- claude-code: `src/outputStyles/`, `src/commands/output-style/`

**Why it's useful and valuable**

Same agent, same tools, different *voice*. A junior engineer wants verbose
explanations; a staff engineer wants terse diffs. A code-review pass wants
nitpicky, an exploratory session wants speculative. Output styles let the user
pick the tone without re-prompting every turn, and let teams ship house styles.

**How to integrate with taui**

- Output styles are markdown files with frontmatter, loaded from
  `~/.taui/output-styles/*.md` (mirrors how skills are loaded at
  `taui/skills/__init__.py:91`).
- Splice the active style into the system prompt builder
  (`taui/prompt_builder.py`) as a dedicated section.
- Slash command `/output-style [name]` with a picker screen in
  `taui/tui/screens/`. Persist choice in `Session` state and as a config
  default.
- Ship 3–4 built-ins: `concise`, `explain`, `review`, `learning`.

---

### 10. Statusline customization

**Where it lives**

- claude-code: `src/commands/statusline.tsx`

**Why it's useful and valuable**

The status bar is prime real estate — users glance at it constantly. Letting
them pin model, branch, cost-so-far, git status, or arbitrary shell output
turns the bar from cosmetic into a control panel. It also lets teams enforce
visibility (e.g. show the prod-vs-staging env you're operating in).

**How to integrate with taui**

- Extend `taui/tui/widgets/status_bar.py` and `info_bar.py` to render from a
  list of "segment" callables.
- Built-in segments: `model`, `provider`, `cwd`, `branch`, `cost_session`,
  `cost_today`, `tokens`, `mode` (plan/build).
- Custom segments: a config block
  `[[taui.statusline.segment]] command = "..."` runs a shell command and
  caches the result for N seconds. Reuse `taui/sandbox.py` for the spawn.
- Slash command `/statusline` opens an editor (`taui/tui/screens/`) to
  reorder/toggle segments.

---

### 11. Vim mode in input

**Where it lives**

- claude-code: `src/commands/vim/`, `hooks/useVimInput.ts`

**Why it's useful and valuable**

A non-trivial slice of taui's target audience lives in vim. Sending a 200-word
prompt with arrow keys is painful; modal editing makes it tolerable. Adding
this once costs less than answering the same feature request fifty times.

**How to integrate with taui**

- Textual supports custom input handling via `Input` subclasses. Build
  `taui/tui/widgets/vim_input.py` as a `ChatInput` subclass that maintains a
  `mode: normal|insert|visual` and rewrites the keypress dispatch
  (`taui/tui/widgets/chat_input.py:64`).
- Toggle with `/vim on|off` (persistent in config) and `Ctrl+\\` as a runtime
  toggle.
- Cover the 80%: motions (`hjkl wb ge $0`), edits (`dd cc x yy p`),
  visual selection, `/`-search in input history. Macros and registers out of
  scope at v1.

---

### 12. Image / clipboard paste support

**Where it lives**

- claude-code: `hooks/useClipboardImageHint.ts`, `usePasteHandler.ts`
- opencode: `packages/opencode/src/image/`

**Why it's useful and valuable**

Screenshots are the fastest way to communicate UI bugs, error overlays, design
mocks, and terminal output the agent didn't see. With paste support, the user
hits `Cmd+V` on a screenshot and the agent sees the image alongside the text.
Without it, the user describes the image in prose — slow, lossy, and a major
friction point for frontend work.

**How to integrate with taui**

- New module `taui/attachments.py` storing images under
  `~/.taui/attachments/<session_id>/<sha>.png`. Hash and dedupe.
- Detect clipboard images on paste via OSC-52 / iTerm protocol where
  available; fall back to a slash command `/paste-image` that reads from
  `pbpaste -Prefer image` (mac) or `xclip -o -t image/png` (linux).
- Surface attached images in `taui/tui/widgets/attachments_bar.py` (the
  widget already exists — extend it for images).
- Provider wiring: pass images as multimodal parts in
  `taui/llm_provider/providers/*.py` when the provider supports them.
  Currently codex (GPT-5) and copilot both have vision; gate behind a model
  capability flag.

---

### 13. IDE integration

**Where it lives**

- claude-code: `hooks/useIDEIntegration.tsx`, `useIdeConnectionStatus.ts`,
  `useIdeAtMentioned.ts`, `useIdeSelection.ts`, `useDiffInIDE.ts`,
  `src/commands/ide/`
- opencode: `packages/opencode/src/ide/`

**Why it's useful and valuable**

The TUI is excellent for chat and approvals; the IDE is excellent for reading
code and reviewing diffs. The agent should be able to:

- Read the user's current selection without the user pasting it
- Open a file at a specific line in the user's editor
- Show a diff in the IDE's native diff UI for approval
- Receive `@file` mentions from an editor command

This bridges the natural division of labor and avoids context-switching.

**How to integrate with taui**

- Build on the Server mode (Feature 6). Ship two thin clients:
  - **VS Code extension** that exposes `taui.openFile`, `taui.showDiff`,
    `taui.sendSelection` and connects to the local taui HTTP server.
  - **Neovim plugin** doing the same via the same JSON API.
- Selection sync: when an IDE client posts the current selection, store it as
  a session-level "ambient context" attached to the next user prompt.
- Diff approval: when a write tool fires, post a diff event over SSE; the IDE
  shows it natively; user approves/rejects in IDE, taui hears the response.
- Status: `/ide status` reports connection. Status bar segment too.

---

### 14. Multi-account / multi-provider auth dashboard

**Where it lives**

- opencode: `packages/opencode/src/account/`, `auth/`
- claude-code: `src/commands/oauth-refresh/`, `login/`, `logout/`,
  `mock-limits`, `rate-limit-options`

**Why it's useful and valuable**

Users routinely have personal + work accounts on the same provider, multiple
orgs (different rate limits, different paid tiers), and several providers
(Copilot + Codex + Anthropic + local). Today `taui --login` is single-slot
per provider. A dashboard lets users:

- See which account is active per provider
- Switch without re-auth
- See remaining quota / rate limits per account
- Detect and recover from expired tokens cleanly

**How to integrate with taui**

- Storage: extend `taui/llm_provider/config.py:15` to keep
  `accounts: dict[provider, list[Account]]` with `Account = {id, label,
  credentials, last_used}`.
- Per-provider `LoginFlow` already exists; add `LogoutFlow` and `SwitchAccount`.
- Slash command `/accounts` opens a TUI screen
  (`taui/tui/screens/accounts.py`) showing the list with rate-limit/quota
  fetched from each provider's `me`-style endpoint.
- Update `/provider` and `/model` flows to scope by active account.
- Persist `active_account_id` in the session so resumes pick the right creds.

---

### 15. Cost / usage UI

**Where it lives**

- claude-code: `cost-tracker.ts`, `costHook.ts`, `src/commands/cost/`,
  `src/commands/usage/`, `src/commands/extra-usage/`, `src/commands/stats/`

**Why it's useful and valuable**

`taui/cost.py` already records spend, but if it isn't visible the user can't
self-regulate. Visible cost changes user behavior — they shorten prompts,
choose cheaper models for trivial work, and stop runaway loops earlier. For
teams, per-session/per-day rollups are essential for chargeback and quota
planning.

**How to integrate with taui**

- Surface session cost in the existing `info_bar.py` and as a status-bar
  segment (Feature 10).
- New `/cost` slash command — opens a screen with: session totals, today,
  this week, this month, breakdown by model and by tool category (input
  tokens, output tokens, cache hits).
- Read directly from the existing `EventType.USAGE` events in the store;
  there's no need for a parallel ledger.
- Hooks: a `cost_threshold_exceeded` hook fires when a configured ceiling is
  crossed (extensions can pause the loop, notify, etc.).
- Optional `/budget set <amount>` to block further tool calls past a ceiling.

---

### 16. Auto-memory / persistent project memory

**Where it lives**

- claude-code: `src/memdir/`, `src/commands/memory/`,
  `hooks/useAssistantHistory.ts`

**Why it's useful and valuable**

Sessions die; memory persists. Across-session memory captures things the agent
*shouldn't* re-discover every time: user role, preferred style, project
conventions, "we tried X and it didn't work." Without it, every session starts
cold and the user re-explains.

This is also where personalization compounds — the longer the user runs taui,
the better it tailors. That's the kind of stickiness that turns a tool into a
habit.

**How to integrate with taui**

- Storage: a `~/.taui/memory/` directory with per-memory markdown files plus
  a `MEMORY.md` index — exactly the same shape as Claude Code's "auto memory"
  spec (see system prompt). Reuse that shape so users can move files between
  tools.
- Loader: `taui/memory.py` reads `MEMORY.md` into the system prompt under a
  dedicated section in `taui/prompt_builder.py`. Token-budget cap with LRU
  eviction.
- Write path: a `memory_write` builtin tool that the agent can call to save
  facts. Auto-categorize into `user / feedback / project / reference`.
- Slash commands: `/memory` to view, `/memory edit`, `/memory forget <slug>`.
- Scope: per-project memory lives at `<project>/.taui/memory/`; global at
  `~/.taui/memory/`. Both load; project memory wins on conflict.

---

### 17. Onboarding flow

**Where it lives**

- claude-code: `src/commands/onboarding/`, `projectOnboardingState.ts`

**Why it's useful and valuable**

First-run is when users decide whether to stick with the tool. A wizard that
walks through auth, picks a default provider, asks a "what kind of work do
you do" question (used to set output style), and confirms permissions
defaults turns a 50% drop-off into 90% activation. Skipping onboarding is the
single most common reason power tools fail to scale.

**How to integrate with taui**

- New flag `~/.taui/.onboarded`. If absent on launch, route through
  `taui/tui/screens/onboarding.py`.
- Steps: welcome → provider auth (reuse existing login flows) → model pick →
  permissions defaults → output style → "try a prompt" → done. Each step is
  cancellable; partial progress is saved.
- Per-project onboarding triggered on first launch in a new cwd: detect
  missing `AGENTS.md`/`CLAUDE.md`, offer to generate one via the agent.

---

### 18. Plugin / extension marketplace UI surface

**Where it lives**

- claude-code: `hooks/usePluginRecommendationBase.tsx`,
  `useOfficialMarketplaceNotification.tsx`

**Why it's useful and valuable**

Even with a marketplace (Feature 7), discovery is the bottleneck. Surface
recommended plugins contextually — when the agent invokes a tool, when the
user opens a new language project, when an LSP error suggests a workflow.
Contextual recommendations have ~10× install rates over a search-only model.

**How to integrate with taui**

- A simple `recommendations.json` shipped with each release and refreshable on
  schedule. Rules like `{ "if": "language=rust && no_ext=rust-analyzer",
  "suggest": "taui-ext-rust" }`.
- Surface as a non-modal toast (`taui/tui/widgets/`) the first time a
  trigger fires per session.
- Dismissible globally and per-recommendation.

---

### 19. Doctor / diagnostics

**Where it lives**

- claude-code: `src/commands/doctor/`
- pi: `core/diagnostics.ts`

**Why it's useful and valuable**

When something breaks, the user's first question is "what is wrong?" Doctor
gives a deterministic answer: provider auth status, MCP server reachability,
LSP health, sandbox config, disk space for snapshots, model cache freshness,
extension load errors. Triage time drops from minutes to seconds.

**How to integrate with taui**

- `/doctor` slash command runs a checklist:
  - Provider auth (ping `me`-endpoint)
  - MCP servers connect + handshake
  - LSP binaries present (`taui/lsp/`)
  - Sandbox runtime available
  - `~/.taui/` writable, snapshot dir size
  - Extension load report from
    `taui/extensions/__init__.py:169`
- Output as a stream of checks with green/red/yellow, plus a final "report
  bundle" that copies sanitized logs to clipboard.

---

### 20. Update notifier / version check

**Where it lives**

- claude-code: `hooks/useUpdateNotification.ts`, `src/commands/upgrade/`

**Why it's useful and valuable**

Users on stale versions hit fixed bugs and miss new features. A quiet check on
launch + a status-bar nudge gets them current without nagging.

**How to integrate with taui**

- Check PyPI for `taui` once per day, store result in `~/.taui/state.json`.
- If newer version available, show a one-line hint in status bar and a
  `/upgrade` command that prints the `uv tool upgrade taui` command (don't
  run package management for the user without consent).

---

### 21. Export session

**Where it lives**

- pi: `core/export-html/` (ansi-to-html + template)
- claude-code: `src/commands/share/`, `src/commands/export/`

**Why it's useful and valuable**

Sharing a session is how learning, debugging, and review actually happen.
HTML export with preserved ANSI colors, tool collapse/expand, and rendered
markdown is the right shape — copyable, archivable, viewable without taui.

Taui has `/copy` and `/export` (per README), but the experience of
ansi-faithful HTML export is the polish missing.

**How to integrate with taui**

- New `taui/export/html.py` that reads events for a session_id and renders
  via a Jinja template. Inline CSS, single self-contained file.
- Use a minimal `ansi-to-html` Python implementation (or `rich`'s
  `Console.export_html`).
- `/export html [path]` writes the file and prints the path. `/export json`
  for raw event dump.
- Optional `share` step: POST to a configured share endpoint and return a URL
  (gated, opt-in).

---

### 22. Session sharing / cloud

**Where it lives**

- opencode: `share/session.ts`, `share/share-next.ts`, `sync/`
- claude-code: `src/commands/share/`

**Why it's useful and valuable**

The team-collaboration version of export. Hand a teammate a URL, they see the
full conversation with tool outputs. Useful for postmortems, training, and
async pairing.

**How to integrate with taui**

- Out of scope for a self-hostable v1 unless taui ships a SaaS. Recommended
  middle ground: define a sharing protocol (signed JSON dump + index) and let
  users post it to a gist, S3, or a self-hosted endpoint via an extension.
- Provide `/share gist` as a first-party convenience.

---

### 23. Compaction with branch summarization

**Where it lives**

- pi: `core/compaction/branch-summarization.ts`

**Why it's useful and valuable**

Full-transcript compaction (taui's `/compact`) destroys nuance — tool-call
detail collapses into prose. Branch summarization keeps the conversation
structure but summarizes *sub-trees* (e.g. a sub-agent's full back-and-forth
becomes "sub-agent X completed Y with files Z"). Token savings without losing
shape. This is the standard for serious long-running sessions.

**How to integrate with taui**

- Extend `taui/agent/context_strategy.py`: add a `BranchSummarizationStrategy`
  alongside the current one.
- Identify branches from existing event metadata — sub-agent calls already
  carry a parent/child relationship via tool calls.
- Summarize a branch using a cheap model (e.g. haiku) with a structured
  prompt that emits `{goal, outcome, files_touched, key_observations}`.
- Persist as `EventType.SUMMARY` events so re-runs reuse them.
- `/compact branches` flag selects this strategy.

---

### 24. Notifications / push / inbox

**Where it lives**

- claude-code: `hooks/useNotifyAfterTimeout.ts`, `useInboxPoller.ts`,
  `hooks/notifs/`

**Why it's useful and valuable**

The agent runs for minutes; the user goes for coffee. A notification when the
job finishes (or asks a question) reclaims that time. Inbox aggregates
notifications across sessions so nothing gets lost when the user closes the
terminal.

**How to integrate with taui**

- Cross-platform notifier: `pync` (macOS), `notify-send` (linux), `win10toast`
  (windows). Detect at runtime.
- Trigger on: agent asks a question (existing `EventType.QUESTION`), task
  completes (Feature 2), stream errors, long-running tool exceeds a threshold.
- `/notify on|off` to gate; per-event-type opt-out in config.
- Inbox: a screen showing recent notifications across sessions, sourced from
  the store directly.

---

### 25. Voice input

**Where it lives**

- claude-code: `src/commands/voice/`, `hooks/useVoice.ts`,
  `useVoiceIntegration.tsx`

**Why it's useful and valuable**

Hands-free prompts during code-review sessions or when reading a screen full
of context. Lower frequency than other features, but a small group of users
will lean on it heavily.

**How to integrate with taui**

- Push-to-talk via a hotkey (`Alt+V`). Stream microphone to a STT provider
  (OpenAI Whisper API or local `whisper.cpp` if installed).
- Insert transcript into the chat input as if typed; user reviews and sends.
- Optional auto-send on silence.

---

### 26. Tool search (deferred tools)

**Where it lives**

- claude-code: `ToolSearchTool`

**Why it's useful and valuable**

Beyond ~30 tools, including every tool schema in the system prompt eats
thousands of tokens per turn. Deferred tools advertise *names only* and load
the full schema on demand via a search tool. The agent uses fewer tokens per
turn but retains access to a much larger library — especially MCP tools, which
can number in the hundreds.

**How to integrate with taui**

- Add a `deferred: bool` flag on `Tool` in `taui/tools/base.py`.
- `taui/tools/registry.py` exposes two listings: `schemas_eager()` (default)
  and `names_deferred()` (just `{name, description}` lines).
- `tool_search` builtin tool: takes a query, returns matching deferred
  schemas. Once returned, mark them active for the session so the next prompt
  rebuild includes them.
- Mark MCP-discovered tools as deferred by default; built-in tools eager.
- Document this in `docs/tools.md`.

---

### 27. Brief / context tool

**Where it lives**

- claude-code: `src/tools/BriefTool`, `src/commands/brief.ts`

**Why it's useful and valuable**

Sub-agents need *context*, not the full parent transcript. A `brief` tool
constructs a tight handoff (task statement, relevant files, prior
observations) for delegation. Without it, sub-agents either get too little
(re-explore) or too much (waste tokens).

**How to integrate with taui**

- Add `brief.py` to `taui/tools/builtins/`. The agent calls
  `brief(task, files=[], notes=[])` and gets back a structured payload
  formatted as the sub-agent's initial user message.
- `taui/tools/builtins/sub_agent.py` accepts a `brief_id` parameter that
  references a previously-built brief.
- Persist briefs as `EventType.BRIEF` so they're inspectable.

---

### 28. Mode system (plan / build / chat / review)

**Where it lives**

- pi: `modes/index.ts`, `modes/interactive/`, `modes/print-mode.ts`,
  `modes/rpc/`
- opencode: subagent permissions per mode

**Why it's useful and valuable**

Plan mode (Feature 1) is the prototype. Once that lands, the same primitive
generalizes: review mode (no writes, only commentary), chat mode (no tools at
all), pair mode (writes go to a side branch). Each mode is a permission
profile + prompt overlay. Users switch modes mid-session as the task changes.

**How to integrate with taui**

- Promote `Session.mode` to a registry-backed enum: each mode is a config
  bundle `{name, prompt_overlay, tool_policy, ui_theme_tint}`.
- Modes live in `~/.taui/modes/*.toml`; ship `plan`, `build`, `chat`,
  `review` defaults.
- `/mode <name>` to switch; persist in session.

---

## P2 — Quality-of-Life / Power-User

### 29. Theme system with in-app selector

**Where it lives**

- pi: `modes/interactive/theme/`, `components/theme-selector.ts`
- claude-code: `src/commands/theme/`, `src/commands/color/`

**Why & how**

Personalization matters more in tools users live in. Taui has `taui/tui/theme.py`;
add `~/.taui/themes/*.toml`, a `/theme` picker screen, and live reload via the
existing extension hot-reload path.

### 30. Customizable keybindings

**Where it lives**

- claude-code: `src/keybindings/`, `src/commands/keybindings/`
- pi: `core/keybindings.ts`

**Why & how**

Hardcoded chords lose to user habit. Add `~/.taui/keybindings.toml` parsed at
launch in `taui/tui/app.py:399`, override `BINDINGS` from that file. `/keys` already
exists — extend it to edit.

### 31. Custom editor / multi-line editor in TUI

**Where it lives**

- pi: `components/custom-editor.ts`

**Why & how**

Long prompts in a one-line input are painful. Add `Ctrl+E` (currently
self-edit — rename) to spawn `$EDITOR` on a temp file, read the result back
into `chat_input.py`. Same pattern as git's commit message editor.

### 32. Session search

**Where it lives**

- pi: `components/session-selector-search.ts`
- claude-code: `useSearchInput.ts`, `useHistorySearch.ts`

**Why & how**

After a month of use, `/sessions` is a wall. Add fuzzy search across session
titles, first-message, and recent files touched. Index lives in the store
(virtual column or sidecar FTS5 table on the events table).

### 33. Differential / virtual rendering

**Where it lives**

- pi: `packages/tui` (differential rendering)
- claude-code: `useVirtualScroll.ts`

**Why & how**

Long sessions get janky to scroll. Textual supports lazy `Static` widgets;
virtualize `turn_container.py` to render only on-screen turns and a small
overscan. Big perf win at zero feature cost.

### 34. Turn-level diffs

**Where it lives**

- claude-code: `useTurnDiffs.ts`, `useDiffData.ts`

**Why & how**

After a multi-edit turn, the user wants "what did you actually change?" in one
view. Aggregate all `file_tracker` writes within a turn boundary and render in
`taui/tui/screens/git_diff.py` accessed via a turn's footer.

### 35. Init verifiers / project init

**Where it lives**

- claude-code: `src/commands/init/`, `src/commands/init-verifiers.ts`

**Why & how**

`/init` writes/updates an `AGENTS.md` after running a project-survey agent:
list languages, build commands, test commands, conventions. Verifiers (lint
config exists, tests can run, lockfile present) gate the AGENTS.md and surface
warnings. Add as a slash command that drives the agent loop with a fixed
prompt.

### 36. Review / security-review commands

**Where it lives**

- claude-code: `src/commands/review.ts`, `src/commands/security-review.ts`

**Why & how**

Bundled prompts: `review` for code-review of the current diff,
`security-review` for OWASP-style scan of recent changes. Ship as
prompt templates that the slash command stuffs into the agent loop.

### 37. Autofix-pr / commit-push-pr

**Where it lives**

- claude-code: `src/commands/autofix-pr/`, `src/commands/commit-push-pr.ts`

**Why & how**

`taui/commands/git_workflows.py` already exists — extend it with two macros:
`/autofix` (read CI logs, propose patches, apply, push) and `/commit-push-pr`
(stage, commit with generated message, push, open PR via `gh`).

### 38. Heap dump / perf-issue / debug-tool-call

**Where it lives**

- claude-code: `src/commands/heapdump/`, `src/commands/perf-issue/`,
  `src/commands/debug-tool-call/`

**Why & how**

Self-debugging hooks: dump Python heap to file, time-profile a slow tool
call, replay a recorded tool call with verbose logging. Useful for
maintainers and power users; cheap to ship as slash commands wrapping
`tracemalloc`, `cProfile`, and an event-replay helper.

### 39. Feedback collection

**Where it lives**

- claude-code: `hooks/useSkillImprovementSurvey.ts`, `src/commands/feedback/`

**Why & how**

`/feedback "<message>"` POSTs to a configured endpoint (or opens a GitHub
issue via `gh issue create`). Optional inline thumbs-up/down on assistant
messages writes to a local log for the user's own retrospectives.

### 40. Bash sandbox toggle

**Where it lives**

- claude-code: `src/commands/sandbox-toggle/`
- pi: `core/bash-executor.ts`

**Why & how**

`taui/sandbox.py` already exists; surface its on/off + level as `/sandbox
status|on|off|strict`. Persist in session.

### 41. Output guard / streaming truncation

**Where it lives**

- pi: `core/output-guard.ts`, `tools/output-accumulator.ts`

**Why & how**

`taui/tools/truncation.py` truncates post-hoc; the guard caps streaming bash
output mid-flight (kill process if it dumps a binary). Add a per-tool
`max_bytes` and a watcher coroutine in `executor.py` that signals SIGTERM on
overflow.

### 42. File mutation queue

**Where it lives**

- pi: `tools/file-mutation-queue.ts`

**Why & how**

Multiple background agents writing to the same file is a race. Serialize
through a path-keyed asyncio lock in `taui/tools/file_tracker.py`. Background
tasks (Feature 2) need this to be safe.

### 43. Visual truncate component

**Where it lives**

- pi: `components/visual-truncate.ts`

**Why & how**

Long tool outputs eat the screen. Render with a fold marker ("... 412 lines
elided, expand") that toggles via mouse/keyboard in
`taui/tui/widgets/tool_status.py`.

### 44. Richer apply-patch tool

**Where it lives**

- opencode: `tool/apply_patch.ts`, `tool/apply_patch.txt`

**Why & how**

Taui has `apply_patch.py`; opencode's variant has a dedicated prompt
(`.txt` sidecar) and is preferred over `edit` for multi-file edits. Add a
sidecar prompt and wire `prompt_builder.py` to include it when the tool is
present.

### 45. Repo clone tool

**Where it lives**

- opencode: `tool/repo_clone.ts`

**Why & how**

Let the agent clone a repo into a scratch dir to inspect dependencies or
forks. New `repo_clone.py` builtin; clones go under
`~/.taui/scratch/<session_id>/<repo>` with size and bandwidth limits.

### 46. Reference system (`@file`, `@symbol`)

**Where it lives**

- opencode: `reference/`
- taui: `taui/tui/widgets/at_completer.py` exists

**Why & how**

Taui has `@` completion in the TUI. Add a parser in `taui/prompt_builder.py`
that expands `@path/to/file` and `@symbol` (via `taui/symbols/`) into the
prompt context rather than just a token. Big context-quality win.

### 47. mDNS / local discovery

**Where it lives**

- opencode: `server/mdns.ts`

**Why & how**

Advertise the local server (Feature 6) over mDNS so an IDE plugin or another
machine on the LAN can discover it. `python-zeroconf` is the easy path.

### 48. Format command

**Where it lives**

- opencode: `format/`

**Why & how**

Detect formatter (`ruff format`, `prettier`, `gofmt`, `cargo fmt`) and expose
as a tool the agent can call after edits. Reuses sandbox.

### 49. PTY tool for interactive bash

**Where it lives**

- opencode: `packages/opencode/src/pty/`

**Why & how**

The current bash tool is one-shot. A PTY-backed variant supports interactive
sessions (REPLs, ssh, `python`, `node`). Add `bash_pty` builtin using
`ptyprocess`; render output through the existing `taui/tui/widgets/terminal.py`.

### 50. Multi-question / multi-select question tool

**Where it lives**

- claude-code: `AskUserQuestionTool`

**Why & how**

Taui's `question.py` is single-question. Extend to accept a list of questions
and a `multiSelect: bool` per question, mirroring claude-code's
`AskUserQuestion`. Update `taui/tui/widgets/questions_panel.py` to render.

### 51. MCP resource listing + auth tools

**Where it lives**

- claude-code: `ListMcpResourcesTool`, `ReadMcpResourceTool`, `McpAuthTool`

**Why & how**

Taui has MCP tools; resources (the read-only side of MCP) are missing. Wrap
the MCP client's `list_resources` / `read_resource` as builtins.

### 52. Remote env / remote setup / SSH

**Where it lives**

- claude-code: `src/commands/remote-env/`, `remote-setup/`, `teleport/`,
  `useSSHSession.ts`

**Why & how**

`taui --remote user@host` opens an SSH connection, syncs the local taui
binary, and runs against the remote repo. Heavier lift; deferrable until the
Server mode (Feature 6) exists, then this becomes "client-mode taui talking
to a server-mode taui over SSH-tunnelled HTTP."

### 53. Cosmetic / fun commands

**Where it lives**

- claude-code: `src/commands/stickers/`, `release-notes/`

**Why & how**

`/release-notes` reads `CHANGELOG.md`. `/stickers` is brand-specific —
skip unless taui has a brand to push. Low priority but cheap morale wins.

---

## P3 — Niche / Experimental / Product-specific

Brief Why/How for each. Skip unless taui's product direction calls for them.

### 54. Chrome extension / mobile bridge
- **Why**: capture prompts from outside the terminal (browser, phone).
- **How**: Server mode (Feature 6) + a tiny relay app. Out of scope until
  there's a hosted backend.

### 55. Slack integration
- **Why**: agent-in-channel for team workflows.
- **How**: a Slack bot that proxies to the local/server taui. Build as an
  extension.

### 56. Desktop / Electron app
- **Why**: users who want a window instead of a terminal.
- **How**: wrap the Server mode + a web frontend. Not aligned with taui's
  "TUI is the product" stance per `docs/taui.md`.

### 57. Web app
- **Why**: zero-install onboarding.
- **How**: same Server mode + web frontend.

### 58. Storybook / UI library
- **Why**: for a web UI, not a TUI.
- **How**: N/A unless 56/57.

### 59. Enterprise / identity
- **Why**: SSO, audit logs, RBAC.
- **How**: a separate auth provider layer; defer to a hosted offering.

### 60. HTTP recorder
- **Why**: record/replay provider traffic for tests.
- **How**: a transport-wrapping extension; useful for the
  `taui/eval.py` harness.

### 61. x402 / payments
- **Why**: agent-driven micropayments. Niche.
- **How**: skip.

### 62. Swarm orchestration
- **Why**: many agents coordinating on one task.
- **How**: emerges from Background Tasks (Feature 2) + Brief (Feature 27);
  no dedicated subsystem needed at v1.

### 63. Teammate view
- **Why**: pair-programming with a human teammate watching.
- **How**: Server-mode + read-only client. Defer.

### 64. Ultraplan / thinkback
- **Why**: meta-agents that critique plans before execution.
- **How**: build as Skills (`~/.taui/skills/ultraplan/SKILL.md`).

### 65. Bug hunter / advisor / good-claude
- **Why**: opinionated prompt bundles for specific workflows.
- **How**: ship as Skills + Output Styles (Features 9, 16).

### 66. Insights / privacy settings UI
- **Why**: opt-in telemetry and consent.
- **How**: tied to onboarding (Feature 17) and observability
  (`taui/observability.py`).

### 67. Containers (sandboxed exec)
- **Why**: stronger isolation than `taui/sandbox.py`.
- **How**: Docker-in-the-loop bash variant; gate by a config flag.

### 68. Subagent permission negotiation
- **Why**: sub-agents request narrower permissions than the parent.
- **How**: extend `taui/permissions.py:38` to accept per-sub-session policies
  computed at spawn.

### 69. OSS session sharing (HF dataset)
- **Why**: contribute sessions to public corpora for training.
- **How**: an exporter extension that uploads sanitized session JSON to a
  configurable destination.

### 70. Pi web-ui / pi differential TUI library
- **Why**: their tech, not directly applicable.
- **How**: borrow ideas (differential rendering — Feature 33) without taking
  the dep.

---

## Notes

- `tmp/codex` was empty in this checkout; only claude-code, opencode, and pi
  were surveyed.
- Taui already has: SQLite event store, sessions, sub-agents, MCP, LSP,
  skills, Python extensions, hooks, permission DSL, sandbox module, OTel,
  self-edit, approvals, context tree, two providers (copilot, codex), and
  most file/bash tools. Items above are deltas relative to that baseline.
- A pragmatic ship order: Server mode (6) → Plan mode (1) → Snapshot/Rewind
  (4) → Background tasks (2) → Worktrees (3) → Web search (8) → Output styles
  (9) → Memory (16) → Plugins (7) → everything else. Many P1/P2 items
  collapse to "small commits" once the P0 substrate exists.
