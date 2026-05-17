# Feature Roadmap From Agent Research

Research date: 2026-05-17

This document reviews features from five coding-agent projects and translates the useful
parts into concrete Taui implementation work. It is intentionally Taui-specific: every
recommendation maps back to the current Textual TUI, `Session`, `AgentLoop`,
`ToolExecutor`, extension system, and append-only SQLite store.

## Sources Reviewed

Local shallow clones were made under `/private/tmp/taui-feature-research`.

| Project | Snapshot | Evidence used |
| --- | --- | --- |
| [`anomalyco/opencode`](https://github.com/anomalyco/opencode) | `be6a89a` from 2026-05-16 | `README.md`, `specs/project.md`, `packages/opencode/src/session/session.ts`, TUI sidebar plugin files, TUI tips |
| [`earendil-works/pi`](https://github.com/earendil-works/pi/tree/main) | `734e08e` from 2026-05-17 | `packages/coding-agent/README.md`, `docs/*.md`, session manager and interactive mode files |
| [`openai/codex`](https://github.com/openai/codex) | `4c89772` from 2026-05-16 | `README.md`, `docs/*.md`, TypeScript SDK README, Python SDK README, TUI/app-server protocol tree |
| [`codeaashu/claude-code`](https://github.com/codeaashu/claude-code) | `6a25909` from 2026-04-22 | Repository docs only, especially `docs/tools.md`, `docs/commands.md`, `docs/subsystems.md`, `docs/bridge.md` |
| [`github/copilot-cli`](https://github.com/github/copilot-cli) | `196c5f6` from 2026-05-14 | `README.md`, `changelog.md` |

Note on `codeaashu/claude-code`: its README describes the repository as leaked source.
Do not copy implementation from it. Treat it only as public competitive-feature signal
and use Taui's own architecture for all design.

## What Each Project Contributes

### OpenCode

Best Taui ideas:

- Client/server-shaped session model with project/worktree awareness, while still
  keeping a strong TUI.
- Rich session metadata: parent IDs, titles, token/cost summaries, sharing state,
  revert state, and per-session permission rules.
- Sidebar panels for context usage, MCP status, LSP status, file status, and todo state.
- JSON themes, configurable keybinds, project/global TUI config, and command palette.
- Custom command, agent, tool, plugin, and theme directories.
- Per-agent permission settings and pattern-based command approvals.
- Non-interactive `run`, JSON output, server attach, and debug config commands.

### Pi

Best Taui ideas:

- A minimal core that is made powerful through extensions, skills, prompt templates,
  themes, and shareable packages.
- Session tree navigation, fork, clone, resume, short IDs, labels, and HTML export.
- Clear steering versus follow-up queue semantics.
- First-class print, JSON, RPC, and SDK modes.
- Prompt templates invoked as slash commands.
- Package manager for bundled extensions, skills, prompts, and themes.
- Broad provider registry with thinking-level normalization and custom providers.

### Codex

Best Taui ideas:

- Strong non-interactive and SDK story built around structured JSONL/JSON-RPC events.
- Thread start/resume/run APIs with streaming events and structured output schemas.
- Explicit sandbox and approval concepts.
- App-server protocol types for external clients, without forcing the TUI to own all
  integration needs.
- Robust install/runtime packaging and pinned SDK/runtime versioning.

### Claude Code Repository

Best Taui ideas, treated only as high-level signals:

- Command taxonomy: prompt commands, local text commands, and local UI commands.
- Per-tool schema, permission, concurrency, prompt, and render metadata.
- Doctor/status/stats/usage command family.
- MCP, plugin, skill, memory, task, LSP, and bridge subsystems as separate services.
- Background task visibility and multi-agent coordination concepts.
- Permission modes and rule examples that map well to Taui's permission DSL.

### GitHub Copilot CLI

Best Taui ideas:

- GitHub integration as a default workflow, especially issues, PRs, and GitHub MCP.
- Autopilot mode with a continuation limit.
- Model picker that exposes token prices and limits.
- LSP configuration/status commands.
- Remote/session resume polish, named sessions, fork origin display, and session delete.
- Secure-by-default prompt/headless mode gates for repo hooks and workspace MCP.
- Changelog-driven hardening details: terminal Unicode rendering, MCP cleanup, stale
  session handling, rate-limit pause/retry, and action-specific approvals.

## Fit Summary

Taui already has strong foundations: a full-screen Textual TUI, provider abstraction,
SQLite event store, replay, extensions, skills, MCP, LSP scaffolding, task tool,
sub-agents, permissions, context breakdown, prompt history, image attachments, and
session export. The highest-value improvements are not "more agent core"; they are
better session ergonomics, scriptability, package distribution, observability, and
project workflow commands.

Recommended priority:

1. Session timeline/tree, fork/clone/delete/name/tag.
2. Prompt templates as first-class slash commands.
3. Better command palette, argument completion, keybinding visibility, and themes.
4. Model/provider UX: thinking effort, scoped model cycling, prices, limits.
5. Non-interactive `print`, `json`, and `rpc` modes over the existing store/events.
6. Extension package manager for skills/prompts/themes/extensions.
7. MCP and LSP dashboards with actionable auth/error/status.
8. Git review/diff/PR workflow commands.
9. Autopilot mode with continuation budget and visible live plan.
10. SDK/app-server adapter only after the local TUI surface is solid.

## Current Taui Anchors

Use these existing files as the main integration points:

| Surface | Current location | Notes |
| --- | --- | --- |
| Session lifecycle | `taui/session.py` | Already has `new_session`, `resume_session`, `fork`, `create_sub_session`, `list_sessions` |
| Durable event stream | `taui/store/store.py`, `taui/store/events.py` | Keep all lifecycle data here; do not add a separate bus |
| TUI command dispatch | `taui/tui/app.py` | Handles `CommandResult.metadata["action"]`, Info2 pickers, replay rendering |
| Slash commands | `taui/commands/builtins.py` | Add user commands here unless extension-owned |
| TUI pickers | `taui/tui/widgets/info2.py`, `taui/tui/screens/` | Reuse for session/model/agent/context pickers |
| Tools | `taui/tools/builtins/`, `taui/tools/executor.py` | Preserve `ToolResult.ok/fail` and policy gate |
| Extensions | `taui/extensions/`, `docs/extension-hooks.md` | Prefer extending the existing Python extension surface |
| Skills | `taui/skills/`, `taui/tools/builtins/skills.py` | Already lazy-loaded; needs better command UX |
| Visual harness | `tests/scenarios/`, `tests/test_tui_visual.py` | Use when TUI behavior changes |

## Feature 1: Session Timeline, Tree, Fork, Clone, Delete, Name, Tag

Inspired by:

- Pi: `/tree`, `/fork`, `/clone`, `--fork`, partial session IDs, session JSONL tree.
- OpenCode: session metadata includes parent, summary, tokens, cost, share, title,
  permission, revert, and fork title.
- Copilot CLI: `/fork`, session picker with origin, branch/status display, delete
  subcommands, short ID prefixes.

Why Taui should add it:

Taui already stores streams with `parent_id`, has `Session.fork(at_offset=...)`, and
has session replay. The missing piece is user-facing navigation and metadata. This is
high leverage because it improves every long-running agent workflow.

Implementation:

1. Store metadata:
   - Add nullable columns to `sessions`: `parent_session_id`, `name`, `tags`, `archived_at`,
     `forked_from_offset`, `current_branch_label`.
   - Or derive parent from `streams.parent_id` as today and add only `name`, `tags`,
     `archived_at`. Keep `parent_session_id` derived unless query performance becomes a
     problem.
   - Add migrations in `Store._migrate_schema()`.
2. Session APIs:
   - Extend `Session.fork(at_offset=...)` to set a generated name such as
     `<source name> (fork #N)` and to persist `forked_from_offset`.
   - Add `Session.clone_current()` that copies the active replay path into a new stream
     without selecting an older offset.
   - Add `Session.rename_session(name)`, `Session.tag_session(tag)`,
     `Session.archive_session(session_id)`, and `Session.delete_session(session_id)`.
   - Support short ID prefixes in `resume_session`, but reject ambiguous prefixes.
3. Commands:
   - Extend `/sessions` with subcommands: `list`, `resume <id>`, `fork [id|offset]`,
     `clone`, `rename <name>`, `tag <tag>`, `delete <id>`, `archive <id>`.
   - Add aliases `/resume`, `/fork`, `/clone`, `/rename`.
4. TUI:
   - Upgrade `Info2.show_sessions()` and `SessionPickerScreen` to show tree indentation,
     tags, mode, message count, age, parent/fork origin, and search.
   - Add a timeline modal with filter modes: all, no-tools, user-only, labels.
   - Let selecting a previous user message call `Session.fork(at_offset=event.offset + 1)`
     and place the selected prompt into the editor for editing.
5. Tests:
   - `tests/test_store.py`: migration, parent resolution, archive/delete/list behavior.
   - `tests/test_session.py`: fork at offset, clone, prefix resolution, ambiguous prefix.
   - `tests/test_tui.py`: picker tree ordering, accept/dismiss/delete behavior.
   - Visual snapshots for the session picker if layout changes materially.

Risks:

- Replaying partial streams must not duplicate `STREAM_START` or append events at
  conflicting offsets.
- Do not remove historical stream events when deleting a session unless the command
  explicitly says "purge"; archive should be the default.

## Feature 2: Prompt Templates As Slash Commands

Inspired by:

- Pi: Markdown prompt templates loaded from user, project, and package directories and
  invoked as `/templatename`.
- OpenCode: `.opencode/commands/*.md` custom prompts with `$ARGUMENTS`, `$1`, `$2`, and
  shell interpolation.
- Claude Code docs: command types separate local commands from prompt commands.

Why Taui should add it:

Taui has skills and extensions, but reusable prompts should not require writing Python.
Prompt templates would make Taui easier to customize while preserving the existing
command registry.

Implementation:

1. Create `taui/prompts/registry.py`:
   - Discover `~/.taui/prompts/*.md`, `.taui/prompts/*.md`, `.agents/prompts/*.md`.
   - Parse optional frontmatter: `name`, `description`, `accepts_args`, `tools`,
     `agent`, `model`.
   - Use filename as command name when no frontmatter exists.
2. Add a `PromptTemplateCommand` adapter in `taui/commands/`.
   - Expands `{{arguments}}`, `$ARGUMENTS`, `$1`, `$2`.
   - Returns `CommandResult.ok(expanded_prompt, action="send_prompt")`.
3. Update `TauiApp._handle_command_result()`:
   - If `action == "send_prompt"`, send the expanded prompt through the same path as
     normal user input.
4. Security:
   - Avoid shell interpolation in v1. If added later, it must go through `bash` policy.
5. Tests:
   - Discovery precedence, malformed frontmatter, argument expansion, command conflict
     behavior, `/reload` refresh.

## Feature 3: Better Command Palette, Argument Completion, Keybindings, Themes

Inspired by:

- OpenCode: command palette, configurable keybinds in TUI config, JSON themes.
- Pi: `/hotkeys`, customizable keybindings, path completion, file fuzzy search, theme
  hot reload, startup header listing loaded resources.
- Copilot CLI: slash picker searches descriptions, argument completion, suggested
  similar commands, CJK/emoji rendering fixes.

Why Taui should add it:

Taui already has completions and a compact Info2 panel, but command discovery and
argument completion can become the main control surface.

Implementation:

1. Command registry:
   - Add optional fields to commands: `aliases`, `category`, `usage`,
     `argument_completer`, `search_terms`.
   - Keep backward compatibility with existing dataclass commands.
2. Info2 command palette:
   - Search command names and descriptions.
   - Rank exact prefix before fuzzy matches.
   - Show usage and category in compact rows.
   - For unknown commands, show nearest matches instead of only an error.
3. Argument completers:
   - `/model`: already exists; extend with provider/model metadata.
   - `/sessions`: session IDs, names, tags.
   - `/export`: file paths and format flags.
   - `/skills`: skill names.
   - `/mcp`: server and tool names.
4. Keybindings:
   - Formalize `Config.keybindings` into a typed binding map.
   - Add `/keybindings` or extend `/hotkeys` to show active, overridden, and missing
     bindings.
   - Support project `.taui/keybindings.json` and global `~/.taui/keybindings.json`.
5. Themes:
   - Turn `Config.theme` into named theme discovery from `.taui/themes/*.json` and
     `~/.taui/themes/*.json`.
   - Add `/theme` picker and reload on `/reload`.
6. Tests:
   - `tests/test_commands.py` if added, otherwise `tests/test_tui.py` for command
     matching and completion.
   - Add width/CJK regression tests for `ChatInput` and `Info2` labels.

## Feature 4: Model And Provider UX

Inspired by:

- Pi: broad provider registry, OAuth and API key options, thinking levels, scoped model
  cycling, provider-specific reasoning mappings.
- Copilot CLI: model picker shows actual prices, auto mode, usage limit warnings, model
  and effort notifications.
- OpenCode: provider/model capability schema with context limits, costs, variants, and
  provider enablement.
- Codex SDK docs: per-turn model selection and structured input support.

Why Taui should add it:

Taui supports Copilot and Codex today. The next useful step is not necessarily adding
every provider; it is exposing capabilities clearly and making model switching safer.

Implementation:

1. Extend `taui/llm_provider/models.py` model records with:
   - `provider`, `id`, `display_name`, `context`, `input_modalities`,
     `output_modalities`, `supports_reasoning`, `reasoning_efforts`,
     `input_cost`, `output_cost`, `cache_read_cost`, `cache_write_cost`,
     `subscription_required`, `deprecated`.
2. Add `Config.reasoning_effort` and wire it through providers that support it.
3. Add scoped model cycling:
   - Config: `models = ["copilot/*", "codex/gpt-5*"]`.
   - TUI: binding to cycle forward/backward.
   - Command: `/scoped-models` or `/models`.
4. Add auto model mode later:
   - Start with local policy only: fallback to a cheaper/available configured model on
     known quota/rate-limit errors.
   - Emit a visible event when rerouting happens.
5. TUI model picker:
   - Show context window, price, reasoning support, current marker, auth status.
6. Tests:
   - Provider-neutral model capability fixtures.
   - Model switch updates `Session.config`, `AgentLoop._model`, InfoBar, and store event.
   - Rate-limit fallback tests using `tests/scenarios/`.

## Feature 5: Non-Interactive Print, JSON, And RPC Modes

Inspired by:

- Pi: `--print`, `--mode json`, `--mode rpc`, piped stdin, event JSONL.
- Codex: `codex exec`, TypeScript SDK over JSONL, Python SDK over app-server JSON-RPC v2.
- OpenCode: `run --format json`, `serve`, `run --attach`.

Why Taui should add it:

Taui is explicitly a full-screen Textual TUI product, so these modes should not become a
second primary UI. They are still useful as automation adapters around the same
`Session` and store.

Implementation:

1. CLI:
   - Add `taui -p/--print "prompt"` for one-shot final text.
   - Add `taui --mode json "prompt"` for JSONL event output.
   - Add `taui --mode rpc` for long-lived stdin/stdout JSONL.
2. Event protocol:
   - Use existing `EventType` values. Add missing event types only when needed:
     `queue_update`, `compaction_start`, `compaction_end`, `approval_requested`,
     `approval_resolved`.
   - Serialize events from `StreamClient.tail()`; do not invent a second event model.
3. RPC:
   - Commands: `initialize`, `prompt`, `interrupt`, `resume`, `new`, `list_sessions`,
     `approve`, `answer_question`, `shutdown`.
   - Responses include request IDs and stream offsets.
4. Tests:
   - Unit test protocol parsing with bad JSON, unknown methods, and cancellation.
   - End-to-end tests with mock provider and no real network.
   - Ensure stdout remains machine-readable; logs go to stderr.

## Feature 6: Extension Package Manager

Inspired by:

- Pi packages bundle extensions, skills, prompts, and themes via npm or git.
- Claude Code docs and Copilot changelog mention plugin install/update/reload flows.
- OpenCode supports project plugins, tools, agents, and themes from config directories.

Why Taui should add it:

Taui's extension surface is already powerful, but sharing extensions requires manual file
copying. A package manager would make Taui's "customizable harness" philosophy real.

Implementation:

1. Manifest:
   - Use `.taui-package.json` or `pyproject.toml [tool.taui.package]`.
   - Fields: `name`, `version`, `description`, `extensions`, `skills`, `prompts`,
     `themes`, `permissions`, `entrypoints`.
2. Storage:
   - Global packages: `~/.taui/packages/`.
   - Project packages: `.taui/packages/`.
   - Install by immutable source key and pinned revision.
3. Commands:
   - `/packages list`, `/packages install <git-url-or-path>`, `/packages remove`,
     `/packages update`, `/packages enable`, `/packages disable`.
   - CLI aliases can come later.
4. Loader:
   - Extend `ExtensionRegistry` and skill/prompt/theme discovery to include enabled
     package resource paths.
   - Package code has full local access, so show a clear trust warning before install.
5. Tests:
   - Install from local fixture path first.
   - Enable/disable precedence, duplicate resource names, broken package isolation.
   - No network tests in the default suite.

## Feature 7: MCP And LSP Status Dashboards

Inspired by:

- OpenCode sidebar plugins for MCP and LSP status.
- Copilot CLI changelog: MCP OAuth, failure warnings with stderr, child process cleanup,
  LSP configuration and status.
- Claude Code docs: MCP client/server, MCP auth, LSP service, plugin error display.
- Codex: MCP elicitation/approval handling and trace correlation.

Why Taui should add it:

Taui already has an `mcp` tool and experimental `lsp` tool. The gap is user visibility:
users need to know which servers are connected, failed, disabled, or waiting for auth.

Implementation:

1. MCP manager state:
   - Standardize server status: `disabled`, `starting`, `connected`, `failed`,
     `needs_auth`, `needs_client_registration`.
   - Capture stderr and last error in metadata.
   - Ensure child processes are terminated when a session closes.
2. Commands:
   - `/mcp list`, `/mcp show <server>`, `/mcp auth <server>`, `/mcp restart <server>`.
   - `/lsp list`, `/lsp show <server>`, `/lsp restart <server>`.
3. Sidebar:
   - Add compact MCP/LSP panels to `SessionInfoSidebar` with status indicators and
     error hints.
4. Tooling:
   - Add `list_mcp_resources` and `read_mcp_resource` tools if Taui's current MCP tool
     cannot expose resources cleanly.
   - Add LSP operations for diagnostics, definition, references, hover, symbols.
5. Tests:
   - Fake MCP server lifecycle and auth-required cases.
   - LSP manager tests with mocked subprocess transport.
   - TUI tests for sidebar status rows and failure messages.

## Feature 8: Git Review, Diff, And PR Workflow Commands

Inspired by:

- OpenCode tips: `/review`, GitHub issue/PR triggers, targeted code review comments.
- Claude Code docs: `/commit`, `/diff`, `/review`, `/security-review`,
  `/pr_comments`.
- Copilot CLI: deep GitHub integration via built-in GitHub MCP server.

Why Taui should add it:

Taui already has `git`, `bash`, `read`, `grep`, and provider tools. Review workflows are
mostly prompt and UI composition, not new agent loop machinery.

Implementation:

1. Commands:
   - `/diff [--staged|--ref <rev>]`: local command that renders git diff summary and
     optionally opens a diff panel.
   - `/review [--staged|--ref <rev>|--security]`: prompt command with a restricted
     read/git tool set.
   - `/commit`: prompt command that proposes a commit message and asks before running
     git.
   - `/pr-comments`: optional GitHub-extension command, not core until GitHub auth is
     formalized.
2. Tool policy:
   - Auto-approve read-only git commands such as `status`, `diff`, `show`, `log`.
   - Keep `commit`, `push`, `reset`, `checkout`, `rebase` behind confirmation.
3. TUI:
   - Add a diff viewer modal or reuse markdown rendering first.
   - Add `j/k` navigation only if it fits existing Textual key patterns.
4. Tests:
   - Use temp git repos.
   - Confirm read-only git commands do not prompt; mutating commands do.
   - Snapshot diff output if a new TUI diff screen is added.

## Feature 9: Autopilot With Continuation Budget And Live Plan

Inspired by:

- Copilot CLI: experimental autopilot mode, `/autopilot`, max continuation limit,
  task completion behavior.
- Claude Code docs: plan mode, background tasks, visible task state.
- Pi: explicit message queue semantics for steering versus follow-up.

Why Taui should add it:

Taui already queues steering and has agent variants. Autopilot should be a conservative
mode that asks the agent to continue until a task-complete condition or budget is hit.

Implementation:

1. Config:
   - `autopilot = false`
   - `max_autopilot_continues = 5`
   - `autopilot_completion_markers = ["task_complete"]` if using a tool marker later.
2. Agent loop:
   - Add optional continuation after a final assistant text when autopilot is enabled
     and the assistant did not declare completion.
   - Emit store events for continuation count and stop reason.
3. Commands and UI:
   - `/autopilot on|off|status`.
   - InfoBar segment showing `auto 2/5`.
   - Optional live plan panel using the existing `task` tool state.
4. Safety:
   - Autopilot must not override tool approvals.
   - Stop immediately on denied tool, quota error, repeated identical action, or
     max continuation count.
5. Tests:
   - Scripted provider that returns incomplete then complete.
   - Max continuation stop.
   - Approval still interrupts.

## Feature 10: Background Tasks And Sub-Agent Observability

Inspired by:

- Claude Code docs: task tools for background shell/agent work.
- Copilot CLI: MCP tasks and `/tasks`, moving running tasks to background.
- OpenCode: parent/child session navigation and `@agent-name` invocation.

Why Taui should add it:

Taui has a persistent `task` tool and a `sub_agent` tool, but child work is not easy to
observe from the TUI.

Implementation:

1. Store:
   - Add event types `TASK_STARTED`, `TASK_UPDATED`, `TASK_OUTPUT`, `TASK_ENDED` only
     if the existing task JSON file cannot support replay. Prefer store events for new
     lifecycle data.
2. Commands:
   - `/tasks list`, `/tasks show <id>`, `/tasks stop <id>`.
   - `/agents` already exists for profiles; avoid name collision by using `/workers`
     for running background agents if needed.
3. TUI:
   - Sidebar task panel should show running sub-agents, tool calls, elapsed time, and
     last output.
   - Let users jump to a child stream replay.
4. Tests:
   - Sub-agent stream lineage, task stop behavior, sidebar rendering.

## Feature 11: Doctor, Status, And Debug Bundle

Inspired by:

- Claude Code docs: `/doctor`, `/status`, `/stats`, `/usage`.
- Copilot CLI changelog: debug info, terminal capability checks, actionable MCP/LSP
  warnings, update/deprecation warnings.
- OpenCode: `debug config` and log printing flags.

Why Taui should add it:

Taui has many moving parts: providers, OAuth, terminal, clipboard, MCP, LSP,
extensions, SQLite, and project config. A doctor command will reduce support friction.

Implementation:

1. `/doctor` checks:
   - Python version, Taui version, working dir writability, git status, `.taui/store.db`
     open, WAL mode, provider auth status, selected model availability.
   - Clipboard backend availability for image paste and copy.
   - `rg`, shell, MCP server states, LSP server states.
   - Extension load errors and skill parse errors.
2. `/status`:
   - Current session ID, stream ID, provider/model, agent profile, mode, tokens, cost,
     context percent, queued messages, active tools.
3. `/debug save`:
   - Write a zip or directory under `.taui/debug/` with config redacted, recent logs,
     store metadata, session export, extension errors.
4. Tests:
   - Redaction tests for tokens and API keys.
   - Doctor returns degraded status, not crashes, when dependencies are missing.

## Feature 12: SDK/App-Server Adapter

Inspired by:

- Codex Python SDK over app-server JSON-RPC v2.
- Codex TypeScript SDK over JSONL.
- OpenCode client/server architecture.
- Claude Code bridge docs and Copilot remote/ACP features.

Why Taui should be cautious:

Taui's project guidance says the Textual TUI is the only interface and there is no web
UI or REST API. An SDK/app-server can still be useful if it is explicitly framed as an
automation adapter around the same session/store, not a second product surface.

Implementation:

1. Start with stdio only:
   - `taui --mode rpc`, not a network server.
   - Use JSONL framing and request IDs.
2. Add a Python package API later:
   - `TauiClient.start_session()`, `Session.run()`, `Session.stream()`,
     `Session.resume()`.
   - Internally spawn `taui --mode rpc` or call library APIs directly in-process.
3. Defer HTTP/WebSocket server:
   - Only add if there is a concrete integration requirement.
   - If added, keep it localhost-only by default and authenticated.

## Features To Defer Or Avoid

| Feature | Why |
| --- | --- |
| Desktop/mobile/web UI | Conflicts with Taui's current "full-screen Textual TUI only" direction |
| Copying leaked Claude Code implementation | Provenance risk; use only high-level feature ideas |
| Telemetry/install pings | Not needed for core product value; high trust cost |
| Voice input | Interesting, but lower priority than session, scripting, and package workflows |
| Remote IDE bridge | Large protocol/security surface; revisit after stdio RPC is stable |
| Public session sharing by default | Useful, but privacy-sensitive; local HTML export is enough first |
| ML-based permission auto-classifier | Hard to audit; pattern rules and explicit approvals are clearer |

## Suggested Milestones

### Milestone A: Session Control

Deliver:

- `/sessions` subcommands for resume/fork/clone/rename/tag/archive/delete.
- Tree/timeline picker.
- Short ID prefix resolution.
- Tests for store migration, session fork/clone, TUI picker behavior.

Files likely touched:

- `taui/store/store.py`
- `taui/session.py`
- `taui/commands/builtins.py`
- `taui/tui/widgets/info2.py`
- `taui/tui/screens/session_picker.py`
- `tests/test_store.py`
- `tests/test_session.py`
- `tests/test_tui.py`

### Milestone B: Reusable Workflow Surface

Deliver:

- Prompt template registry and `/template` invocation.
- Command palette search and argument completions.
- `/theme`, `/keybindings`, and `/reload` integration.

Files likely touched:

- `taui/prompts/`
- `taui/commands/`
- `taui/tui/widgets/chat_input.py`
- `taui/tui/widgets/info2.py`
- `taui/config.py`
- `tests/test_tui.py`

### Milestone C: Automation Modes

Deliver:

- `taui --print`, `taui --mode json`, `taui --mode rpc`.
- Stable JSONL event protocol based on `EventType`.
- Mock-provider end-to-end tests.

Files likely touched:

- `taui/main.py`
- `taui/session.py`
- `taui/store/events.py`
- new `taui/rpc/`
- `tests/test_provider_scenarios.py`
- new RPC tests

### Milestone D: Observability And Integrations

Deliver:

- MCP/LSP status panels and commands.
- `/doctor`, `/status`, `/debug save`.
- Review/diff prompt commands.

Files likely touched:

- `taui/tools/builtins/mcp.py`
- `taui/lsp/`
- `taui/tui/widgets/session_info_sidebar.py`
- `taui/commands/builtins.py`
- `taui/tools/builtins/git.py`
- targeted tests under `tests/`

### Milestone E: Distribution

Deliver:

- Taui package manifest.
- Local path package install/remove/list first.
- Git package install after trust prompts and pinning are implemented.

Files likely touched:

- `taui/extensions/`
- `taui/skills/`
- new `taui/packages/`
- `taui/commands/builtins.py`
- package fixture tests

## Completion Criteria For Each Feature

Every feature should meet these gates before merge:

1. The feature stores durable lifecycle state in `.taui/store.db` when replay or
   session history depends on it.
2. The behavior is reachable from the TUI through a slash command, keybinding, or
   existing picker.
3. The behavior has focused tests near the owning module.
4. TUI changes that affect layout have either unit coverage or visual snapshot coverage.
5. New automation surfaces use mock providers in tests and do not require live LLM auth.
6. Dangerous operations keep Taui's `ToolExecutor` policy and approval flow intact.
7. Documentation is updated in `README.md`, `docs/taui.md`, or the relevant
   architecture doc when behavior changes.
