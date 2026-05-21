# World-Class Coding Agent Harness — Gap Analysis & Roadmap

Taui already has the bones of a serious harness: an async think→tool→observe
loop, an append-only SQLite event store with replay/fork, a typed extension and
hook surface, MCP integration, scripted-provider scenarios, and a Textual TUI.
This plan inventories what is missing to move from "solid foundation" to
"world-class" — on par with Claude Code, Cursor CLI, Aider, Codex CLI, and
OpenHands — and groups the gaps into shippable workstreams.

Style notes used throughout:
- Citations are `path:line` against the current tree.
- Each gap section ends with a concrete deliverable list.
- Phasing is by *blast radius*, not calendar time — small foundational
  changes first, large UX/orchestration changes later.

---

## 0. Guiding Principles

1. **Event store is the source of truth.** Every new feature emits and
   replays from `taui/store/store.py:97`. No side-channel state.
2. **Tools fail soft.** Tools return `ToolResult.fail()`; only the loop or
   provider raises. `taui/tools/base.py:10`.
3. **Streaming first.** Anything that can stream — provider deltas, bash
   stdout, sub-agent thoughts, file diffs — must stream end-to-end.
4. **Extension over fork.** New capabilities ship as extensions/skills
   where possible (`taui/extensions/__init__.py:93`) before becoming
   builtins.
5. **Determinism on demand.** Every code path must be drivable by
   `ScriptedProvider` (`tests/scenarios/scripted_provider.py:82`) so visual
   and behavioral regressions are catchable offline.

---

## 1. Tools & Tool Execution

### 1.1 Inventory and what is good

Current builtins (`taui/tools/builtins/`):

- File I/O: `read`, `write`, `edit` (4-level fuzzy match at
  `taui/tools/builtins/edit.py:24`), `apply_patch`, `notebook_edit`.
- Search: `glob`, `grep`, `repo_overview`, `peek` (handle pagination).
- Shell: `bash` (process-group kill, 50 KB cap, env allowlist at
  `taui/tools/builtins/bash.py:19`).
- VCS: `git` (read/write split; read ops auto-approved).
- Web: `webfetch` (1 h cache, 32 KB cap).
- Agentic: `task`, `sub_agent`, `skills`, `mcp`, `memory`, `question`.
- LSP: `lsp` (goto/refs/hover/symbols at `taui/lsp/client.py:15`).

Genuine strengths: edit's resilience chain, peek-handle pagination, MCP
auto-registration, the read-only git split, and the FILE_READ/SEARCH
parallel batch in `taui/agent/loop.py:412`.

### 1.2 Hard gaps

- **Silent truncation.** Bash 50 KB cap (`bash.py:15`), grep 500 matches
  (`files.py:353`), glob 200 (`files.py:283`). Agent rarely realizes it
  has partial data. Need uniform truncation envelope: emit a
  `truncated_at`, `total_hint`, and a `peek_handle` for follow-up.
- **No streaming bash.** Long builds, test runs, dev servers, watchers,
  `npm install`, `cargo build` all hit the 120 s wall-clock timeout
  (`taui/agent/loop.py:161`) or fill memory. Need
  - background tool execution with a process handle,
  - incremental stdout/stderr chunks emitted as observation events,
  - a `bash_status` / `bash_kill` companion tool,
  - a foreground/background flag analogous to Claude Code's
    `run_in_background`.
- **Bash env allowlist is hardcoded.** `bash.py:19` blocks user-set vars.
  Auto-load project `.env` (opt-out), expose a `bash.env` allowlist in
  config, and let extensions extend it.
- **No `Monitor` / `Watch` tool.** No way to subscribe to file changes,
  long-running process events, or PR/CI webhooks without a busy-poll
  bash loop.
- **Glob/grep ergonomics.** No exclude patterns, no `--context`, no
  case-insensitive flag, no ranking by recency. Tighten to ripgrep
  semantics; allow `!pattern` negation.
- **Web search.** Only `webfetch` exists. Need a `web_search` tool with
  pluggable backend (Brave/SerpAPI/Tavily/DuckDuckGo), domain allow/deny,
  and citation capture.
- **No diff/patch preview tool.** Add `diff_preview(path, new_content)`
  that returns a unified diff without writing — critical for approval
  flows and for sub-agent self-review.
- **Advanced git is missing.** No `merge`, `rebase`, `cherry-pick`,
  `reset`, `reflog`, `worktree`, `stash apply`, `bisect`. Surface as
  explicit subcommands so policy can gate each separately.
- **Notebook tool is shallow.** Add cell execution, output capture,
  kernel restart.
- **Tool result caching.** Identical reads in the same turn are re-run
  (`taui/tools/executor.py:312`). Add an LRU keyed on
  `(tool_name, normalized_args, file_mtimes)` — invalidated by the file
  tracker.
- **Retries are flat.** `_RETRY_DELAYS` / `_RETRY_CATEGORIES`
  (`executor.py:20`) retries any failure 3×; we need per-error-class
  policy (auth → no retry, transient I/O → exponential, file-locked →
  short backoff) and a budget cap per turn.
- **No tool versioning / deprecation.** Registry has no schema version
  (`taui/tools/registry.py:27`); cannot safely evolve schemas across
  releases.
- **Argument validation is late.** `executor.py:341` validates after
  policy. Validate first, fail with a structured `tool_arg_error` event
  the agent can self-correct from.
- **No idempotency keys.** Re-issuing a failed `edit` can double-apply;
  re-issuing a `bash` re-runs side effects. Add idempotency tokens for
  the loop to dedupe replays.

### 1.3 New tool surface to add

- `web_search`, `diff_preview`, `monitor`, `bash_status`, `bash_kill`,
  `bash_attach` (for backgrounded shells), `pdf_read`, `image_read`
  (multimodal), `code_index` (LSP-backed symbol/import lookup), `todo`
  (persistent, not session-only as `task` is), `notebook_run`,
  `format` (project-aware formatter dispatch), `lint`, `test`
  (test-discovery + runner with structured output).

### 1.4 Deliverables

- Uniform truncation envelope + `peek` integration across all read-type
  tools.
- Background-process bash with streaming chunks and lifecycle tools.
- Pluggable `web_search` with provider registry and citation events.
- `diff_preview` wired into approval UI.
- Per-error-class retry policy and structured `tool_arg_error`.

---

## 2. Permissions, Policy, Sandbox

### 2.1 Current state

- `PermissionRule` is fnmatch-only (`taui/permissions.py:24`).
- `SandboxPolicy.enabled` defaults to `False` (`taui/sandbox.py:25`).
- Path checks via `relative_to` (`sandbox.py:39`), no symlink/hardlink
  resolution.
- Layers are Agent → Project → Global with first-match wins
  (`permissions.py:79`); no merge semantics across layers.
- Network policy is a single boolean (`sandbox.py:37`).

### 2.2 Gaps

- **Pattern language** — fnmatch cannot express negation (`!**/*.test.*`),
  alternation across deep paths, or path-anchored regex. Move to a
  small typed DSL: glob with `!`, `{a,b}`, optional regex fallback,
  per-rule TTL ("approve once", "approve this session").
- **No real OS sandbox.** Need optional `bwrap`/`firejail`/`sandbox-exec`
  integration for the `bash` tool, with a writable-overlay mount for
  the project root and a read-only mount for `$HOME`. Make sandbox
  enabled-by-default with a documented opt-out.
- **No per-host network policy.** Default-deny for `bash` egress
  except a configured allowlist (github.com, registry.npmjs.org,
  pypi.org). Webfetch should share the same allowlist.
- **No project trust gate.** First time we open a project, prompt the
  user to trust it; cache trust signature in `~/.taui/trust.toml`.
- **No high-risk command class.** Pattern-match destructive commands
  (`rm -rf`, `git push --force`, `kubectl delete`, `terraform apply`,
  `npm publish`, `psql ... DROP`) and require explicit confirmation
  regardless of auto-approve rules.
- **Approval UX gaps.** No "approve all reads under `src/`", no
  "approve this command for 1 hour", no "approve once and review later".
- **No team/workspace layer.** Add a `Workspace` layer above project so
  shared repos can ship default policies.

### 2.3 Deliverables

- New pattern DSL + migration shim for existing TOML.
- Optional bwrap-backed bash sandbox; net-allowlist enforcement in
  `webfetch` and `bash`.
- Project-trust gate + signed trust ledger.
- "High-risk command" class with mandatory confirmation.
- Approval modal extensions for scoped/expiring approvals.

---

## 3. Agent Loop, Context, Reasoning

### 3.1 Current state

- Loop is the canonical think→tool→observe state machine
  (`taui/agent/loop.py:93`).
- Parallel exec only for FILE_READ + SEARCH (`loop.py:412`).
- Compaction triggers at 80 % soft / 90 % hard
  (`taui/agent/context.py:443`), drops oldest non-preserved messages.
- Steering injects mid-loop user messages (`loop.py:402`).
- Sub-agents via `Session.create_sub_session` with bounded turns
  (`taui/tools/builtins/sub_agent.py:104` clamps to 25).

### 3.2 Gaps

- **Loop is rigid.** No graduated retry per tool, no speculative
  branching, no plan-execute-verify cycles, no plan persistence across
  compaction.
- **Parallel writes are blocked.** Even disjoint edits in different
  files serialize. Need a "tool independence" predicate (same file?
  same key? shared resource?) and a parallel-write batch executor.
- **No interleaved thinking.** `ReasoningFormat.EFFORT_LEVELS`
  (`llm_provider/types.py:37`) is declared but unused. Wire
  effort-level configuration into provider calls, surface reasoning
  cost in the cost tracker.
- **Compaction is lossy and unbiased.** Drops oldest first; loses
  todo/plan state mid-task. Need:
  - hierarchical summaries (detailed recent → summarized middle →
    overview oldest),
  - protected sections (active todo list, current diff, current file
    tracker),
  - cost-aware retention (keep things that were expensive to produce),
  - semantic compaction via embeddings or LLM-side rerank.
- **No file tracker dedup.** Re-reading the same file across turns is
  common. Maintain a "file inventory" channel that the loop trims into
  context with `{path, hash, last_read_turn}` instead of repeating
  content.
- **Sub-agent context inheritance.** Children get a fresh prompt;
  there's no read-only ancestor scratchpad. Add a parent-summary slot.
- **No batch / async tool jobs.** Long-running sub-agents block the
  parent. Need `sub_agent.start()`, `sub_agent.join()`,
  `sub_agent.cancel()` semantics for fan-out, plus a worktree
  isolation mode.
- **Steering UX is fire-and-forget.** No confirmation that steering
  took effect, no priority levels, no "abort and replan".
- **Cancellation is all-or-nothing.** Cannot cancel tool A while
  keeping tool B running in the same parallel batch.

### 3.3 Deliverables

- Independence-predicate batcher (parallelize disjoint writes).
- Interleaved-thinking wiring + effort-level config in providers/UI.
- Hierarchical, protected-section compaction with todo persistence.
- File inventory channel + dedup.
- Async sub-agent lifecycle + worktree isolation.

---

## 4. Providers and Models

### 4.1 Current state

- Two providers: GitHub Copilot (`llm_provider/providers/copilot.py:33`),
  OpenAI Codex (`llm_provider/providers/codex.py:26`).
- Registry pattern in `llm_provider/registry.py` makes adding providers
  cheap.
- `models.dev` cache with 24 h TTL (`llm_provider/models.py:22`).
- Pricing hardcoded (`cost.py:15`, `types.py:278`).
- Rate limiting via client-side semaphore only.

### 4.2 Gaps

- **Missing first-party providers.** Direct Anthropic Messages API,
  Direct OpenAI Responses/Chat, Google Gemini, AWS Bedrock, Vertex AI,
  Azure OpenAI, Ollama (local), OpenRouter, Together, Groq.
- **No capability probing.** No way to ask "does this model support
  tools / vision / cache / batch / thinking?" — capabilities are
  hardcoded.
- **Prompt caching is partial.** `_cache=True` on system messages
  (`loop.py:677`) — no TTL, no cache breakpoints around skills/tools,
  no analytics on hit rate.
- **No batch / async submission.** No path to Anthropic's batch API or
  OpenAI's batch endpoint for cheap large jobs.
- **No structured outputs.** No JSON-schema-constrained outputs, no
  Zod-style validation on tool args from the *model* side.
- **No multimodal inputs beyond images.** PDFs, audio, video are
  rejected. Tooling for "read this PDF and summarize" is missing.
- **Auth is one-shot.** `refresh_credentials()` is called once per
  turn (`base.py:216`); long sessions can race past expiry.
- **No provider-side rate-limit awareness.** Reset/limit headers from
  providers are not parsed; we cannot back off intelligently.
- **No fallback chain.** Cannot say "try Sonnet, fallback to Haiku on
  overload" — useful for `/compact` and sub-agents.
- **Pricing drift.** Hand-maintained pricing table; need a fetch step
  with override.

### 4.3 Deliverables

- Add Anthropic, OpenAI direct, Gemini, Bedrock, Ollama providers
  behind the existing registry.
- Capability descriptors + UI surfacing (model picker shows
  caching/tools/thinking/vision).
- Real prompt caching strategy with breakpoints around system / skills
  / file context, cache-hit analytics in `/cost`.
- Provider rate-limit header parser + exponential backoff.
- Fallback chains in `Config.fallbacks`.

---

## 5. System Prompt, Context Strategy, Skills

### 5.1 Current state

- `SystemPromptBuilder` (`prompt_builder.py:149`) discovers AGENTS.md,
  `.taui/instructions.md`, project metadata.
- Skills lazy-loaded from four roots (`taui/skills/__init__.py:91`),
  capped at 8000 chars.
- Hook chain `system_prompt` (`taui/hooks.py`).

### 5.2 Gaps

- **No relevance-ranking of prompt sections.** Sections concat by
  priority but never re-rank against the current task.
- **No few-shot retrieval from prior sessions.** The store is a
  ready-made corpus for "find similar prior tasks" — unused.
- **Skills are atomic.** No skill dependencies, no composition, no
  parameterization.
- **No prompt-injection sanitation** on third-party content (PR bodies,
  web fetches, MCP responses).
- **Developer-role messages declared but not used**
  (`types.py:250`).
- **No persona swap mid-loop** — e.g., `/persona security-auditor`.

### 5.3 Deliverables

- Embedding-backed nearest-skill retrieval (optional, off by default).
- Skill manifests with `requires`, `params`, `provides`.
- Untrusted-content envelope rendered as `<untrusted>` blocks in the
  prompt; tool results from `webfetch` / MCP wrapped automatically.
- `/persona` command + persona registry under
  `.taui/personas/*.toml`.

---

## 6. TUI

### 6.1 Current state

- Single-pane Textual app (`taui/tui/app.py:206`) with streaming chat,
  tool status, approvals, questions, sidebars, session picker, paste
  and image attachments, prompt history, self-edit modal.
- Existing plans `.plans/tui-revamp.md` and `.plans/gamify-ui.md` cover
  modularization and visual polish.

### 6.2 Gaps not covered by the existing plans

- **Diff viewer.** Approvals show raw text; we need a unified-diff
  modal (with `e`/`r` shortcuts to edit or reject) for every
  `edit`/`write`/`apply_patch`.
- **Inline file viewer.** Click a file mention → side panel with
  syntax-highlighted preview anchored at the referenced line.
- **Todo / plan panel.** A first-class persistent todo widget bound to
  a `todo` tool, surviving compaction and restart.
- **Command palette across everything** — tools, commands, models,
  skills, agents, files, prior sessions — with fuzzy match.
- **Image rendering** in chat (terminal-graphics protocol where
  available, ASCII fallback).
- **Integrated terminal pane** for streamed bash output — already in
  `tui-revamp.md` but not yet built.
- **Markdown fidelity.** Better code-block highlighting per language,
  mermaid/PlantUML rendering to ASCII, LaTeX fallback.
- **Accessibility.** High-contrast theme, screen-reader hints,
  keyboard-only flows tested.
- **Notifications.** Desktop / terminal-bell on approval pending,
  long-running task done, sub-agent completed.
- **Layout customization.** Pane sizes, sidebar position, per-project
  layout snapshots.
- **Status line.** Always-visible activity, token %, cost, pending
  approvals, queued steerings.

### 6.3 Deliverables

- Diff viewer modal + approval integration.
- Todo panel bound to persistent `todo` tool.
- Global command palette.
- Image rendering (kitty/iterm/sixel + ASCII).
- Notifications + status line.

---

## 7. Sessions, Store, Replay

### 7.1 Current state

- Append-only SQLite event log with WAL (`store/store.py:97`).
- Fork via `parent_id` linkage; sub-sessions inherit.
- Resume by replaying events (`session_replay.py:48`).

### 7.2 Gaps

- **No tree visualization.** Forks accumulate; users can't see or
  prune them.
- **No portable export.** No "tape file" or JSONL export for sharing,
  bug reports, or browser replay.
- **No selective replay.** Resume always replays the whole stream; no
  checkpointing or cherry-pick.
- **No GC / retention policy.** Long-running projects accumulate
  unbounded SQLite size.
- **Single writer.** Concurrent sessions on the same store work
  because each owns a stream, but there's no cross-session
  coordination primitive.
- **No public stream subscription API** for extensions — e.g., an
  extension that mirrors events to a dashboard.

### 7.3 Deliverables

- `taui sessions tree` and a TUI tree view.
- `taui session export <id>` → portable JSONL.
- Web-replay artifact + minimal browser viewer (HTML+JS, no server).
- Checkpoint API + selective resume.
- Retention policy + `taui sessions prune`.
- Public `Store.subscribe()` extension hook.

---

## 8. Extensions, Hooks, Skills, Self-Edit

### 8.1 Current state

- Python extensions discovered globally and per-project
  (`extensions/__init__.py:169`).
- 12+ hook points (`hooks.py`).
- Self-edit modal scoped to extension/skill/command/agent surfaces
  (`self_edit/factory.py:101`).

### 8.2 Gaps

- **No hot reload.** Restart needed after extension edits — directly
  blocks the self-edit loop's value.
- **No sandboxing.** Extensions run in-process; a bad extension
  crashes the agent if it throws in a non-async path.
- **No declarative tool definitions.** Tool authors must write
  Python; we should accept a TOML/JSON tool descriptor with a shell or
  HTTP backend for low-friction custom tools.
- **No registry / marketplace.** No discovery, versioning, signing.
- **Hook ordering.** Hooks fire in registration order; needs explicit
  priority and dependency declarations.
- **Skill composition.** No `requires` field; no parameterization.
- **Self-edit lacks validation.** No type-check / hook-shape
  validation before save; no smoke test; no rollback.
- **Self-edit cannot reload itself.** Tied to the hot-reload gap.

### 8.3 Deliverables

- File-watcher-driven hot reload for `.taui/extensions/*.py` with safe
  cutover (snapshot, swap, fall back on failure).
- Declarative tool descriptors (`.taui/tools/<name>.toml`) with shell
  or HTTP backends.
- Extension manifest with `priority`, `requires`, `version`,
  `capabilities`.
- Self-edit pre-commit validation (schema check + `ruff` + smoke
  import) + one-click revert from the modal.

---

## 9. MCP

### 9.1 Current state

- Stdio + HTTP/SSE clients (`taui/mcp/__init__.py:71`).
- Tool, resource, prompt, sampling support.
- TOML config (`.taui/mcp.toml`, `~/.config/taui/mcp.toml`).

### 9.2 Gaps

- **No OAuth.** Env vars only; modern MCP servers need OAuth.
- **No credential vault.** Secrets live in TOML / env; we should
  integrate the OS keychain (Keychain / Secret Service / Credential
  Manager).
- **No reconnection / health checks.** Crashed stdio servers don't
  auto-restart.
- **No streaming resources or pagination.**
- **No roots surfaced** — `Workspace/Project` roots aren't passed.
- **No call telemetry.** MCP latency / error rates not in `/cost` or
  OTel traces.

### 9.3 Deliverables

- OAuth client + keychain integration.
- Reconnect with exponential backoff and circuit breaker.
- Roots / resources surfaced in TUI as a tree.
- MCP tool spans in OTel + per-server cost line in `/cost`.

---

## 10. LSP / Semantic Code Index

### 10.1 Current state

- Per-language client (`taui/lsp/client.py:15`).
- Indexer for lightweight symbol extraction (`taui/symbols/indexer.py:27`).
- Tool surface: goto/refs/hover/symbols.

### 10.2 Gaps

- **No rename refactor.** Blocks safe bulk renames.
- **No workspace symbol search** for fuzzy "where is foo defined?"
- **No inlay hints / code lens.**
- **No diagnostics surfaced to the loop.** After every edit, the loop
  should pull diagnostics and surface them as observation.
- **No call hierarchy / type hierarchy.**
- **No semantic index for retrieval.** The indexer is unused by
  context strategies.

### 10.3 Deliverables

- `code_index` tool wrapping LSP `workspaceSymbol`,
  `references`, `prepareRename`, `rename`.
- Post-edit diagnostics observation injected automatically.
- Optional embeddings index over symbols for "find similar function"
  use cases.

---

## 11. Multi-Agent & Orchestration

### 11.1 Gaps

- **No fan-out primitive.** Cannot launch N sub-agents in parallel,
  collect results, route best one back.
- **No worktree isolation.** Sub-agents share the working tree; safe
  parallel exec requires per-agent worktree (mirroring Claude Code's
  `isolation: "worktree"`).
- **No supervisor pattern.** No "planner-executor", "critic-actor",
  or "ensemble" templates.
- **No queue / scheduler.** No max-concurrent-agents, no priority.

### 11.2 Deliverables

- `sub_agent.start/join/cancel` with worktree option.
- Built-in orchestration playbooks (planner→executor→critic).
- Concurrency cap in config; `/agents queue` view.

---

## 12. Cost, Telemetry, Observability

### 12.1 Current state

- `CostTracker` (`cost.py:61`); per-turn token + cost.
- OTel spans for agent/provider/tool when `TAUI_OTEL=1`
  (`otel.py:20`).
- Structured contextvar logging (`observability.py:16`).

### 12.2 Gaps

- **No per-tool cost attribution.**
- **No cache-hit analytics.** Cache tokens are tracked but not
  surfaced in `/cost`.
- **No forecasting.** No "you'll hit context limit in ~3 turns".
- **No OTel exporter wired by default.** Off-by-default with no
  example configs.
- **No Prometheus / metrics exporter.**
- **No request/response capture toggle** for provider debugging
  (with redaction).
- **No flamegraph / py-spy integration story.**

### 12.3 Deliverables

- Per-tool, per-skill cost lines in `/cost`.
- Cache-effectiveness panel.
- Forecast band in the status line.
- OTel-collector example + Grafana dashboard.
- `TAUI_DEBUG_PROVIDER=1` with auto-redaction.

---

## 13. Evaluation & Benchmarks

### 13.1 Current state

- `taui/eval.py` exists as a skeleton; `run_eval()` is incomplete
  (`eval.py:115`).
- Strong scripted-provider scenarios
  (`tests/scenarios/scenarios.py:25`) but no task-grade evals.
- 25 visual snapshots; 1138 test functions.

### 13.2 Gaps

- **No golden-task suite.** SWE-bench Verified, terminal-bench, or a
  curated taui-specific corpus.
- **No multi-model bake-off.** Same task across providers/models
  with comparative scoring.
- **No latency / throughput benchmarks.** No tokens/s, no time-to-first-token,
  no per-tool latency histogram.
- **No property-based tests.** Truncation, compaction, fuzzy edit are
  prime targets for `hypothesis`.
- **No replay-as-test.** Recorded sessions should be runnable as
  regression tests.
- **No scheduled eval runs.**

### 13.3 Deliverables

- Wire `eval.py` end-to-end with a `tasks/` corpus, scoring harness,
  HTML report.
- `taui eval --model X --task Y` CLI.
- Hypothesis property tests for context compaction, edit fuzzing,
  truncation envelopes.
- Nightly GitHub Action that runs evals against a small task set.

---

## 14. CI/CD, Packaging, Release

### 14.1 Current state

- `pyproject.toml` with Ruff (`E`, `F`, `I`, `UP`, line 100), Python
  `>=3.13`.
- Manual publish via `PUBLISHING.md`.
- No `.github/` workflows.

### 14.2 Gaps

- **No CI.** No lint/test/security workflow on push or PR.
- **No release automation.** No tag-triggered PyPI publish, no
  changelog generation.
- **No coverage reporting.**
- **No dependency security scan** (pip-audit / Dependabot).
- **No platform matrix.** macOS-arm64, Linux-x86_64 untested in CI.
- **No Docker image** for cloud / CI agent usage.
- **No `entry_points` for third-party plugins.** Forces file-based
  extension drop-in only.

### 14.3 Deliverables

- `.github/workflows/ci.yml` — Ruff + pytest + coverage + pip-audit.
- `.github/workflows/release.yml` — tag → build → twine upload.
- `entry_points` in `pyproject.toml` for skills, tools, providers.
- Optional Docker image with `uvx taui` baked in.

---

## 15. Documentation & DevEx

### 15.1 Gaps

- **No CONTRIBUTING.md** with dev loop, architecture map, test
  expectations.
- **No "build your own tool" tutorial** — `examples/custom_tool.py`
  exists but isn't promoted.
- **No "extend taui" book** that covers extensions + skills + hooks
  + agents end-to-end with a single worked example.
- **No replay-as-debugger** UX — should be a documented flow:
  "reproduce a bug from a session id".
- **No profiling guide.**
- **No error attribution.** When a test fails, link the failure to a
  specific turn / tool / provider event.

### 15.2 Deliverables

- CONTRIBUTING.md.
- A single end-to-end tutorial that builds a custom tool, a skill, a
  command, and a hook in one project.
- `taui session debug <id>` — open a session in step-through mode in
  the TUI.

---

## Prioritized Roadmap

Each phase is independently shippable; each ends with green tests and
updated docs.

**Phase 1 — Reliability (foundational, low blast radius)**
1. Uniform truncation envelope + peek across read tools (§1.2).
2. Per-error-class retry policy + structured tool-arg errors (§1.2).
3. Pattern DSL with negation/scoped/expiring approvals (§2.2, §2.3).
4. CI workflow with Ruff + pytest + pip-audit (§14.3).
5. Property tests for compaction, edit fuzz, truncation (§13.3).

**Phase 2 — Capability (high impact, additive)**
6. Streaming/background bash + `bash_status`/`bash_kill`/`monitor`
   (§1.2, §1.3).
7. `diff_preview` tool + diff viewer modal in TUI (§1.3, §6.3).
8. `web_search` pluggable backend + citation events (§1.3).
9. `todo` persistent tool + TUI todo panel (§1.3, §6.3).
10. Code index / LSP refactor surface, post-edit diagnostics (§10.3).

**Phase 3 — Providers & Reasoning**
11. Anthropic + OpenAI direct + Gemini + Ollama providers (§4.3).
12. Interleaved thinking wiring + effort-level config (§3.3, §4.3).
13. Real prompt-caching strategy with cache analytics (§4.3, §12.3).
14. Fallback chains and provider-rate-limit-aware backoff (§4.3).

**Phase 4 — Context & Orchestration**
15. Hierarchical, protected-section compaction + file-inventory
    dedup (§3.3).
16. Independence-predicate parallel writes (§3.3).
17. Async sub-agents with worktree isolation + supervisor playbooks
    (§3.3, §11.2).

**Phase 5 — UX, Sessions, Extensibility**
18. Global command palette + image rendering + status line + accessibility
    pass (§6.3).
19. Session export + browser replay + tree view + retention (§7.3).
20. Extension hot reload + declarative tool descriptors + manifest
    fields (§8.3).
21. MCP OAuth + keychain + reconnect + telemetry (§9.3).

**Phase 6 — Hardening & Polish**
22. OS sandbox for bash with bwrap/sandbox-exec + network allowlist
    (§2.3).
23. Cost forecasting + per-tool cost lines + Prometheus exporter
    (§12.3).
24. Golden-task eval harness + nightly multi-model bake-off (§13.3).
25. Docker image + `entry_points` plugin distribution (§14.3).
26. CONTRIBUTING + end-to-end "extend taui" tutorial + replay-as-debugger
    (§15.2).

---

## Acceptance criteria for "world-class"

A user should be able to, without leaving taui:

- Trust a new repo on first open, run a multi-step refactor across files
  with streamed bash output, review each diff before applying, and
  approve or reject in two keystrokes.
- Launch four sub-agents in parallel against isolated worktrees, watch
  their progress in a tree view, merge the best result.
- Hot-swap a hook or skill mid-session and see it take effect on the
  next turn.
- Switch between Anthropic, OpenAI, Gemini, and a local Ollama model
  with no config changes, with cache analytics visible in `/cost`.
- Replay any past session deterministically as a regression test,
  scrub between turns, drop a breakpoint on a tool call.
- Hand a colleague a single JSONL file that reconstructs the entire
  session in a browser viewer.
- Run the eval harness against a model + task set and get an HTML
  report.

Every item above maps to a deliverable in this document.
