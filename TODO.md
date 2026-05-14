# TODO — Roadmap to a world-class coding agent harness

Taui is a customizable agentic coding interface. The thesis: **managing
context is what separates a good harness from a great one**. Everything
in this roadmap exists to make context handling more honest, more
adaptive, or more user-controlled — and to keep the surface composable
enough that users can replace any layer without forking.

This roadmap is *not* about adding more providers. Today's two
(`copilot`, `codex`) are sufficient until the harness itself is great.

References studied:
- `opencode/packages/opencode/src/{session,permission,agent,tool}` — agent
  variants (build/plan), permission ruleset DSL, structured summary template
- `pi/packages/coding-agent/src/core/{compaction,agent-session,session-manager}` —
  branch summarization, session tree navigation, file-operation tracking
- `codex/codex-rs/core/src/{context_manager,compact,tools}` — pre-turn vs
  mid-turn compaction, truncation policy, contextual user messages
- `codeaashu/claude-code/src/{tools,memdir,coordinator,skills}` — rich
  tool catalog (Task/Skill/NotebookEdit), memdir, multi-agent coordinator
- `../yoqe/{TODO.md,yoqe/agent}` — pluggable `ContextStrategy`, file-state
  tracker, peek/handle truncation, prompt-caching markers (already shipped)

Legend: **[P0]** must-have, **[P1]** strong, **[P2]** polish.

---

## 1. Context Management — the thesis

The current `agent/context.py` uses `len // 4` and drop-oldest. Every
serious harness studied does better. This is the headline rebuild.

- [x] **[P0] Real tokenizer per provider.**
  Replace `estimate_message_tokens` with a provider-supplied tokenizer
  (`tiktoken` for codex, copilot's published heuristic for copilot).
  Fall back to char/4 only if no tokenizer is registered. Drive
  compaction off the *measured* `Usage.input_tokens` from the previous
  turn plus a per-message estimate for the pending delta. Today's
  drift on code-heavy turns is the single biggest source of mid-turn
  context overflows.

"""- [ ] **[P0] Pluggable `ContextStrategy`.**
  Pull the inline `_maybe_compact` out of `AgentLoop` into a strategy
  object with `prepare(messages) -> messages` and
  `on_turn_result(usage)`. Ship three strategies, switchable per
  session and per agent (see §2):
    1. `DropOldest` — current behavior (keep as fallback)
    2. `Summarize` — opencode's structured template (Goal /
       Constraints / Progress / Decisions / Next / Critical Context /
       Relevant Files), replacing the oldest contiguous run of
       assistant+tool messages, tagged `role="system"`
    3. `Hybrid` — `Summarize` at soft (80%), `DropOldest` at hard (90%)"""
  contextstrategy is always compactions, so this is not required. 

- [x] **[P0] File-state tracker.**
  Track every file the agent has Read in the current session
  (path → mtime + sha). `EditTool`/`WriteTool` refuse to mutate a file
  whose on-disk state changed since the last Read, returning a
  structured `ToolResult.fail` the agent can act on (re-Read, then
  retry). This is the single biggest source of bad edits in naive
  harnesses; opencode and codex both enforce it, taui currently does
  not.

- [x] **[P0] Output truncation with `peek` handle.**
  When a tool returns more than N bytes (default 8 KiB), store the
  full output in the stream, truncate the inline copy with a footer
  like `[truncated; 234 KiB more — peek(handle="tr_abc", offset=…)]`,
  and ship a built-in `peek` tool that retrieves a window. Today a
  single `bash find /` or `grep -r` can blow the budget in one turn.
  Codex's `truncate_function_output_payload` is the model.

- [x] **[P1] Pre-turn vs mid-turn compaction split.**
  Codex distinguishes `BeforeLastUserMessage` (mid-turn) from
  `DoNotInject` (pre-turn / manual). Mid-turn replacement must keep
  the trailing user message verbatim or the model loses the request.
  Today `compact_messages` runs once per turn before the LLM call;
  add an explicit `manual` entry point bound to `/compact`.

- [x] **[P1] Per-section budget telemetry.**
  `SystemPromptBuilder` already has `_budget_fit_sections` infra.
  When `TAUI_DEBUG_PROMPT=1`, emit a structured log per render:
  what fit, what was dropped, by how much. Surface a snapshot in the
  Ctrl+X context breakdown screen (which today only shows role
  totals).

- [x] **[P1] Prompt-caching markers in provider request builders.**
  Mark the system prompt + tool schemas block cacheable for both
  providers. Expose `Usage.cache_read_tokens` and
  `cache_write_tokens` in `TurnResult.usage` and surface them in
  `/cost` so users can see when the cache is paying off. Dev
  workflows have huge stable system prompts — typical 40-60% cost cut.

- [x] **[P1] Contextual messages distinct from user messages.**
  Codex separates `is_contextual_user_message_content` from real user
  input so it can be safely dropped during compaction. Today taui
  injects steering and `@file` expansions as plain `role="user"`
  messages — they get preserved as "the latest user message" even
  when they're just file content the user injected ten turns ago.
  Add a `Message.kind: Literal["user","contextual","steer"]` field.

- [x] **[P2] Reference context diffing.**
  Codex tracks a `reference_context_item` and only re-injects what
  changed (cwd, branch, recent commits). Today taui rebuilds the
  full `ProjectContext` block every turn. After §1.6 lands, only
  re-emit the diff in mid-conversation system messages.

---

## 2. Composability — the lever

Most patterns users want (plan mode, accept-edits, sub-agents,
specialist agents, skills-as-agents) are trivial *if* the agent and
session APIs compose cleanly. Today they don't quite.

- [x] **[P0] Named agent variants.**
  Borrow opencode's `Agent.Info`: a named bundle of `(model, prompt,
  tool subset, permission ruleset, context strategy)`. Ship `build`
  (default), `plan` (read-only + write to a plan file), and let users
  define their own in `.taui/agents/<name>.toml` or as Python in an
  extension. `/agent <name>` switches; `Ctrl+A` opens the picker.
  Today `self_edit` is a one-off; this generalizes it.

- [x] **[P0] Permission ruleset DSL.**
  Replace the flat `tool_policy` map with opencode's
  `tool : pattern → action` ruleset:
  ```toml
  [taui.permission]
  read       = { "*" = "allow", "*.env" = "ask", ".env.example" = "allow" }
  bash       = { "git status" = "allow", "git push" = "ask", "*" = "ask" }
  edit       = { "src/**" = "allow", "*" = "ask" }
  external_directory = { "*" = "ask", "/tmp/*" = "allow" }
  ```
  Patterns evaluated longest-prefix-first. Per-agent overrides
  (§2.1) layered on top of project on top of global.

- [x] **[P0] `Session.fork(at_offset=None)`.**
  Branch a session at any offset to explore an alternative path
  without mutating the original stream. Pi's `navigateTree` is the
  reference: each fork gets its own stream id with `parent_id` set,
  and the picker (`/sessions`) shows the tree. Combined with §1.2
  this is how users do "what if" debugging.

- [x] **[P0] Composable `Session.create()` overrides.**
  Today `Session.create(config)` and `new_session()` rebuild
  everything from config. Expose a `session(name=, tools=,
  tool_names=, system_prompt=, max_turns=, context_strategy=,
  permission=, model=)` factory on the running app so an extension
  can spawn a sub-session in ten lines without touching `Session`'s
  internals. Reuses the parent's store (with parent_id link).

- [x] **[P1] Parallel tool execution within a turn.**
  Add `is_parallel_safe: bool = True` to the `Tool` protocol
  (defaults: `FILE_READ`/`SEARCH` = True, `FILE_WRITE`/`SHELL` =
  False). In `_think_and_act`, group consecutive parallel-safe calls
  and `asyncio.gather` them; serialize the rest. Today every tool
  runs sequentially even when six grep calls are independent.

- [x] **[P1] Tool result post-processors.**
  `Session.add_result_processor(fn)` runs on every `ToolResult`
  before it hits the stream. Lets users do secret redaction, content
  tagging, file-tracking updates, etc. in user-land instead of
  forking the executor. Pair with a built-in `redact_secrets`
  example.

- [x] **[P1] Optional tool output schema.**
  `output_schema: dict | None = None` on the `Tool` protocol so the
  TUI can render diffs / line-numbered reads / table results without
  sniffing strings. The `edit` tool already produces a diff
  internally; expose it as structured output.

- [x] **[P2] `extension_dirs` config.**
  Today extension lookup is hard-coded to `~/.taui/extensions/` and
  `.taui/extensions/`. Let users add a `extension_dirs = ["…"]`
  config for shared team extensions in a separate repo.

---

## 3. Tools — fill the catalog gaps

The current built-ins cover the basics. The reference repos suggest
a handful of additions that pay for themselves immediately. Most can
be built on the existing extension surface; the ones below are
primitives that need core access or are common enough to ship built-in.

- [x] **[P0] `Task` / `TodoWrite` tool.**
  A persistent in-session task list the agent reads and updates. Pi
  and codeaashu/claude-code both ship this; it makes long-horizon
  work coherent and gives the user a visible plan. Render as a panel
  in the TUI. Backed by a file in `.taui/sessions/<id>/tasks.json`.

- [x] **[P0] `webfetch` + `websearch` tools.**
  Read-only context-gathering tools the agent can use to pull docs.
  Already hinted at in opencode (`mcp-websearch.ts`, `webfetch.ts`).
  `webfetch` defaults to caching responses to `.taui/cache/web/`.

- [x] **[P0] `apply_patch` tool.**
  Multi-hunk unified-diff edits in one tool call. Today `edit` is
  one search/replace at a time, which costs many turns on big
  refactors. Codex's `apply_patch` and opencode's `apply_patch.ts`
  are mature references. Falls back to `edit` if the patch doesn't
  apply cleanly.

- [x] **[P0] LSP-backed `goto_def` / `find_refs` / `hover`.**
  `taui/lsp/` already has client + manager scaffolding marked
  experimental. Wire it to a tool surface. Symbol-aware lookups beat
  grep on a large codebase by 10×, and the tokens-per-answer ratio is
  much better than dumping a whole file.

- [x] **[P1] `repo_overview` tool.**
  One-shot project survey: language, framework, entry points, top
  packages, recent commits. Opencode's `repo_overview.ts` is the
  reference. Pre-computed and cached, refreshed on git HEAD change.
  Replaces the agent's first three "let me explore" turns.

- [x] **[P1] `notebook_edit` tool.**
  Cell-aware edits for `.ipynb` files. Existing `read` already
  understands notebooks (claude-code reference shows this); add the
  inverse.

- [x] **[P1] `subagent` tool that uses §2.4.**
  Reimplement `taui/tools/builtins/sub_agent.py` on top of the
  composable `session()` factory. Today it's a parallel code path
  that drifts; after §2.4 it's a thin wrapper.

- [x] **[P2] `peek` tool.**
  Required by §1.4. Retrieves a window from a truncated tool output
  by handle.

- [x] **[P2] `git_status` / `git_diff` as first-class tools.**
  Today `git.py` exists but is a thin shell wrapper. Expose
  structured outputs (file lists, hunk counts) so the agent doesn't
  have to parse porcelain.

---

## 4. Persistence, Replay, Observability

The store is solid. The pieces that read from it lag.

- [x] **[P0] `harness.resume_session(stream_id)` end-to-end.**
  Today `--session <id>` exists but session reconstruction lives in
  `session_replay.py` and is fragile around tool-call/result pairing.
  Property test: for any recorded stream, `resume → run one more
  turn → assert messages and stream are consistent`.

- [x] **[P0] `RunResult.total_usage` + `RunResult.cost_usd`.**
  `TurnResult.usage` exists; roll up to `RunResult`. Per-model
  pricing in `taui/llm_provider/pricing.py`; user override in
  config. Surface in `/cost` and the InfoBar.

- [x] **[P0] Session tree picker (Ctrl+S or `/sessions`).**
  Today `/sessions` lists flat. After §2.3 lands, render the tree
  with parent links and the branch summary (§1.2 surfaces this) so
  users can navigate forks visually.

- [x] **[P1] Structured logging with `contextvars`.**
  `taui.observability.configure_logging()` switches to JSON logs and
  propagates `session_id`, `turn`, `tool_call_id` through
  `contextvars`. No new dep.

- [x] **[P1] OpenTelemetry hooks behind `taui[otel]` extra.**
  Spans for `agent.turn`, `provider.create_turn`, `tool.run`. Off
  by default; `init(otel_enabled=True)`. Lets teams ship taui usage
  to their existing observability stack.

- [x] **[P1] `session.export(format="markdown"|"jsonl"|"html")`.**
  Replace ad-hoc `/export`. Markdown for code review, JSONL for
  evals, HTML for sharing. Pi's `export-html/` is a good reference.

- [x] **[P2] `store.subscribe(stream_id)` async iterator.**
  External observers (a second TUI watching a headless run, a CI
  dashboard) tail the live stream without polling.

---

## 5. Reliability

- [x] **[P0] Idempotent-tool retries.**
  For `FILE_READ` / `SEARCH`, bounded exponential retry (3 tries,
  0.25 / 1 / 4 s) before surfacing failure to the model. Mutators
  (`FILE_WRITE`, `SHELL`, `GIT`) never retry automatically.

- [x] **[P0] Typed provider error taxonomy.**
  Map the regex-driven error detection in `llm_provider/base.py` to
  typed errors: `ContextOverflowError`, `QuotaExceededError`,
  `TransientProviderError`, `AuthExpiredError`. Loop branches on
  type, not string.

- [x] **[P0] Auto-recovery on `ContextOverflowError`.**
  When the LLM call fails with overflow, run a manual compaction
  pass and retry once before surfacing to the user. Today the loop
  raises and the user has to `/compact` manually.

- [x] **[P1] Per-vendor rate-limit semaphore.**
  Two sessions sharing a harness shouldn't stampede the same
  provider. Token bucket + semaphore in
  `llm_provider/registry.py`.

- [x] **[P1] Crash-safe stream writes.**
  Already half-there with WAL. Audit `Store.append` for
  `flush()` per write so a crash mid-turn loses ≤1 event.

- [x] **[P2] Tool execution sandbox.**
  For `bash`, optional `bwrap` (Linux) / `sandbox-exec` (macOS)
  wrapper that blocks network + restricts writes to the workspace.
  Codex has both (`bwrap/`, `landlock.rs`, `sandboxing/`) — port
  the policy file format, defer the implementation to opt-in.

---

## 6. MCP

The MCP layer is in `taui/mcp/`. It works for tools. Round it out:

- [x] **[P1] MCP resources & prompts.**
  Surface `resources/list` and `prompts/list` so users can pin a
  resource into their system prompt or invoke a server-defined
  template. `Skill` already has the right shape — reuse it.

- [x] **[P1] MCP sampling callbacks.**
  When a server requests sampling from the host LLM, route through
  the harness's provider with optional smaller-model override.

- [x] **[P2] HTTP/SSE transport** in addition to stdio.

- [x] **[P2] Per-server prefix override.**
  Today every MCP tool is `mcp__<server>__<name>`. Trusted servers
  should be able to expose native names.

---

## 7. TUI Polish

The TUI is already strong. These are the rough edges that show up
in real use.

- [x] **[P1] Diff viewer for every write/edit.**
  `DiffViewScreen` exists but is only triggered on demand. After
  §3.3 lands, every `edit`/`write`/`apply_patch` tool result should
  expand into an inline collapsed diff with `Enter` to view full.

- [x] **[P1] Per-tool output formatters.**
  After §2.7 lands (output schema), add formatters: line-numbered
  read, table for grep, diff for edit, tree for repo_overview.
  Today every tool result is a markdown blob.

- [x] **[P1] First-class plan-mode UI.**
  When the active agent variant (§2.1) is read-only, show a banner
  + a "Switch to build" button on the InfoBar. Mirror opencode's
  plan/build agent flow.

- [x] **[P2] Inline `/` slash-command help.**
  Tab completion on `/` shows the description column. Today the
  dropdown shows only names.

- [x] **[P2] Persistent task panel.**
  After §3.1 lands, render the todo list as a collapsible panel in
  the sidebar with click-to-expand task details.

- [ ] **[P2] Voice input.**
  codeaashu/claude-code has `voice/`. Optional, behind extra. Not
  core but a fun extension example.

---

## 8. Extensions Surface — make user-land win

The customizability story works only if users can build the next
feature without us. Today extensions can register tools, commands,
hooks, and skills — that's most of the way. Gaps:

- [x] **[P0] Extension can register an agent variant.**
  After §2.1 lands, `ctx.agents.register(AgentVariant(name="review",
  tools=["read","grep"], system_prompt=…))` from any extension.

- [x] **[P0] Extension can register a context strategy.**
  After §1.2 lands, `ctx.context.register(MyStrategy())` and use it
  by name in config. This is the single hook that proves "managing
  context" is a user-extensible concern, not a hardcoded one.

- [x] **[P0] Extension can register a provider.**
  Despite "no new providers" being scope-limited for *us*, third
  parties wanting Anthropic, Bedrock, vLLM, Ollama should be a
  ten-line extension. `ctx.providers.register(...)` already
  half-exists in `llm_provider/registry.py` — formalize.

- [x] **[P1] Extension lifecycle hooks.**
  `on_session_start`, `on_session_end`, `on_compaction`,
  `before_tool_call`, `after_tool_result` already exist as hooks.
  Document them in one place; today they're scattered.

- [x] **[P1] Self-edit playbooks for the new surfaces.**
  After §1, §2, §3 land, add `taui/self_edit/playbooks/` entries
  that show `/i` how to scaffold a new agent variant, a new
  context strategy, a new permission rule.

~~- [ ] **[P2] Extension marketplace listing.**~~
  Not required — the extension surface is sufficient without a marketplace.
  A `taui-extensions` GitHub topic + a `taui ext list/install/remove`
  CLI that fetches from a curated index. Defer; first prove the
  surface is rich enough that anyone wants to publish.

---

## 9. Tests

- [x] **[P0] Property tests for `compact_messages` (all strategies).**
  For any message list with valid tool-call/tool-result pairing,
  post-compaction every assistant `tool_calls` entry still has its
  matching tool result. Already half-asserted in `test_context.py`;
  extend to `Summarize` and `Hybrid`.

- [x] **[P0] File-state tracker test matrix.**
  Read → external mutation → Edit must fail with structured error.
  Read → Edit (no external change) must succeed. Read → Read → Edit
  must succeed even if mtime is the same.

- [x] **[P0] End-to-end resume test.**
  Record a session, resume it, run another turn. Assert messages
  and stream are consistent. Currently fragile in `session_replay`.

- [x] **[P1] Snapshot tests of `SystemPromptBuilder.render()`.**
  Lock down the prompt for a fixed `ProjectContext`. Catches
  unintended drift.

- [x] **[P1] Sandbox tests for permission ruleset.**
  Pattern matching, longest-prefix evaluation, layer cascade
  (agent → project → global).

- [x] **[P2] Replay-based eval harness.**
  `taui eval <fixture-dir>` replays recorded sessions against the
  current build, diffs the tool-call sequence, flags regressions.
  Ten golden tasks beats nothing; the store already has the data.

---

## 10. Docs

- [x] **[P0] `docs/build-your-harness.md`.**
  Six numbered steps with real code per step: register a tool, an
  agent variant, a context strategy, a permission rule, a hook, a
  command. Mirrors yoqe's `docs/build-your-harness.md`.

- [x] **[P0] `docs/context-strategies.md`.**
  Document `DropOldest` / `Summarize` / `Hybrid`. Show how to write
  a custom one. This is the headline page — it's the thesis.

- [x] **[P1] `docs/agents.md`.**
  Document agent variants after §2.1 lands. Show a `review`,
  `commit`, `pair` variant in the recipe collection.

- [x] **[P1] `docs/permission-dsl.md`.**
  Pattern syntax, evaluation order, common recipes (e.g. "allow git
  read, ask for git write, deny anything touching prod").

- [x] **[P2] `examples/` directory.**
  - `examples/plan_mode.py` — agent variant with read-only tools
  - `examples/sub_agent.py` — `subagent` tool via §2.4
  - `examples/skills_as_agents.py` — skill bundled with a session
    config
  - `examples/persistent_memory.py` — cross-session memory using
    the existing memory tool
  - `examples/secret_redaction.py` — result post-processor (§2.6)
  - `examples/peek.py` — using the truncation handle

---

## Sequencing

1. **§2 (composability)** P0s first — until `session()` takes
   overrides and agent variants exist, every other roadmap item is
   awkward to build.
2. **§1 (context)** P0s — the headline thesis. Real tokenizer +
   pluggable strategy + file-state tracker + truncation handle.
3. **§3 (tools)** P0s in parallel with §1 — `Task`, `apply_patch`,
   `webfetch`, LSP unblock long sessions.
4. **§4 (persistence)** P0 — resume + cost roll-up.
5. **§5 (reliability)** P0 — typed errors + auto-recover on overflow.
6. **§7 (TUI), §8 (extensions surface)** as the underlying primitives
   land.
7. **§9 (tests), §10 (docs)** in parallel with everything — examples
   are how we validate the surface is actually composable.
8. Everything else as it earns its place.

---

## Out of Scope (intentionally)

These are deliberately *not* in this roadmap:

- **More providers.** Two is enough until the harness is great.
  After §8.3, anyone can add their own as an extension.
- **A web UI / dashboard / hosted service.** Taui is a TUI. If you
  want web, fork the `Session` API.
- **A workflow graph language.** Composing sessions and tools in
  Python is the workflow language.
- **Automatic context summarization in the *background*.** Compaction
  runs synchronously before the LLM call where it's needed. Background
  summarization is a complexity tax with no measured win.
- **Anything that hides the context from the user.** The Ctrl+X
  breakdown screen is sacred. Everything we add must remain
  inspectable.

If a pattern shows up in three different example files with the same
shape, that's a signal a small primitive might be missing — *not* a
signal to add the pattern as core API.
