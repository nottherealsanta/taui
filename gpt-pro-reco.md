I inspected the uploaded project. My read: Taui already has the bones of a serious agent harness: async agent loop, durable SQLite event streams, Textual TUI, provider abstraction, approvals, session replay/forking, self-edit mode, MCP/LSP/sub-agent scaffolding, permission DSL, file tracker, truncation/peek, apply_patch, task tool, and a big docs/tests surface.

The next step is not “add more features.” It is to turn this into a reliable, measurable, extensible runtime that people can trust.

My recommended next steps

1. Freeze the product thesis

Position Taui as:

A programmable agent harness for developers: durable, replayable, forkable, observable, and reshapeable.

That is stronger than “another coding agent.” The differentiator should be the harness layer:

Pillar	What it means in Taui
Durable runs	Every run is an append-only event stream that can be replayed, forked, exported, and audited.
Composable agents	Agent variants, sub-sessions, tools, permissions, context strategies, providers, and prompts are swappable.
Trust boundary	File tracking, permission DSL, approvals, secret redaction, sandboxing, and deterministic patching.
Observability	Per-run traces, tool spans, token/cost accounting, replay-based evals, and eventually OpenTelemetry export.
User-shaped interface	Extensions and self-edit mode let users adapt the harness instead of adapting to a fixed assistant.

This aligns with where agent platforms are going: OpenAI’s current Agents docs emphasize orchestration/handoffs, guardrails/human review, results/state, and observability as core agent concerns; the Agents SDK tracing docs also frame LLM generations, tool calls, handoffs, guardrails, and custom events as first-class trace data.  ￼

⸻

2. Do a “Sprint 0” hardening pass before adding anything else

I found a few immediate credibility issues that should be fixed first.

Fix the repo hygiene. There is a checked-in SQLite artifact at taui/tui/.taui/store.db. Add .taui/ and *.db project-state patterns to .gitignore, remove that file from the repo, and add a CI check that fails if runtime state gets committed.

Fix the dev environment. pyproject.toml tells contributors to run tests and ruff, but the dev dependency group does not explicitly include pytest, pytest-asyncio, or ruff. Add them. I could not run the full suite because dependency sync tried to download aiohttp-jinja2 and DNS failed in this environment. Running Python directly also showed missing runtime deps like aiosqlite and textual.

Fix the one concrete test failure I hit. A targeted subset produced 135 passing tests and 1 failure. The failing path is in taui/agent/context.py: compact_messages() imports Message from taui.agent.loop, which drags in store dependencies and causes ModuleNotFoundError: aiosqlite in an otherwise lightweight context test. That import appears unnecessary; use the already-imported taui.agent.types.Message or remove the local import.

Fix the stale roadmap. TODO.md still marks many items unchecked that now appear implemented or partially implemented: file tracker, truncation/peek, agent variants, permission DSL, session fork, task tool, apply_patch, LSP tool, repo overview, resume tests, provider errors, parallel tools, context strategy registry, docs, etc. A stale TODO file is dangerous because it hides the true frontier.

Fix the PyPI/repo version gap. The repo says version 0.4, while PyPI currently shows taui latest as 0.1.1 released February 24, 2026. That is fine during alpha, but before you market this as a serious harness, the public package/version story needs to match the repo story.  ￼

⸻

3. Build a “world-class harness” scorecard

Create a file like docs/world-class-bar.md and make every release prove it. Suggested gates:

Area	Release gate
Install	uvx taui works on a clean machine.
Auth	Copilot and Codex login flows succeed or fail with clear recovery.
Run durability	Every user message, assistant message, tool call, tool result, usage record, approval, and error is replayable from SQLite.
Forking	A session can fork at any offset and continue independently.
Safety	No write occurs outside the workspace unless explicitly approved by a policy rule.
Patch reliability	apply_patch, edit, and write are file-tracked, atomic, path-safe, and diff-visible.
Context reliability	Context overflow auto-recovers and preserves the latest real user request.
Observability	Every run has a trace view with turn/tool/token/cost/error breakdown.
Evals	Core coding tasks run as replayable evals in CI.
Extensibility	A user can add a tool, command, agent variant, context strategy, and provider without touching core.

Do not call a release “world-class” until it passes this scorecard.

⸻

4. Make observability a first-class product surface

This is the highest-leverage differentiator for Taui.

You already have an append-only store. Turn it into a trace system, not just session history. OpenTelemetry is the current vendor-neutral standard for traces, metrics, and logs, so the long-term shape should be compatible with OTel even if you keep your own SQLite-native view first.  ￼

Next implementation steps:

1. Add a stable run_id, turn_id, tool_call_id, parent_id, span_id, and trace_id model.
2. Treat each agent run as a trace.
3. Treat each LLM call, tool call, approval wait, compaction, retry, and provider error as a span/event.
4. Add /trace or a TUI trace panel.
5. Add optional taui[otel] export later.

This gives you a killer debugging loop: run → inspect trace → fork → compare traces → improve agent/tool/prompt → replay eval.

⸻

5. Turn replay into an eval harness

You have session replay pieces already. The next step is to make them useful for quality.

Create taui/evals/ with small fixture repos and tasks:

Eval	Measures
“Fix failing unit test”	Can agent localize, patch, and verify?
“Add CLI flag”	Can it modify code + tests + docs?
“Refactor safely”	Does file tracker prevent stale edits?
“Large output flood”	Does truncation/peek prevent context blowups?
“Ambiguous task”	Does question flow work?
“Forbidden write”	Does permission DSL block correctly?
“Resume after crash”	Can replay reconstruct state?
“Fork and compare”	Can two branches diverge cleanly?

For each eval, record:

success, turn_count, tool_count, approval_count, input_tokens, output_tokens, cost_usd, files_changed, tests_passed, retries, context_compactions, and trace_url/export.

That moves Taui from “seems good” to “measurably improving.”

⸻

6. Tighten the security/trust boundary

This is where agent harnesses win or lose trust.

Immediate fixes I would prioritize:

Make apply_patch as safe as write and edit. It currently builds paths as base / file_path. It should use the same resolve_path() path-escape protection as the file tools, use atomic writes, use file locks, and have tests for ../escape patches.

Wire file tracking everywhere. You already wire read, write, and edit; make sure apply_patch is also wired in Session.create().

Make bash policy more structured. You already filter environment variables and require confirmation by default. Next add policy subjects like command binary, cwd, network intent, and write intent. “git status allowed, curl | sh denied” should be expressible.

Add secret redaction. Add a result processor layer before tool output enters the model context. Redact .env, tokens, private keys, GitHub/OpenAI tokens, and common cloud credentials.

Add a sandbox mode. Even a basic “no network, workspace-only writes, timeout, env allowlist, temp home” mode would be valuable. Full process/container sandboxing can come later.

⸻

7. Reconcile extension promises with actual wiring

The extension story is central to Taui, but a few surfaces need to be made real end-to-end.

I noticed the extension context supports tools, commands, hooks, skills, agents, context strategies, and providers. But in Session.create(), user extensions are loaded after provider creation, which means extension-registered providers cannot be selected during initial provider creation. Also, commands are passed as None when extensions load, while the docs say extensions can register commands.

Next steps:

1. Split extension loading into phases: early providers/config, then runtime tools/hooks/agents/commands.
2. Pass a real CommandRegistry to extensions, or change docs until that is supported.
3. Version the extension API: ctx.api_version, ctx.capabilities, and compatibility warnings.
4. Add an examples/ directory with working extensions:
    * custom read-only reviewer agent
    * team permission policy
    * custom provider
    * custom context strategy
    * custom TUI/command extension
    * secret redactor

MCP should also be part of this strategy. The current MCP spec version is 2025-11-25, and MCP’s core model includes lifecycle/capability negotiation plus server features such as resources, prompts, and tools.  ￼ Taui should not just “call MCP tools”; it should become an excellent MCP host.

⸻

8. Polish the TUI around trust, not decoration

For a world-class agent harness, the UI should answer five questions at all times:

1. What is the agent doing?
2. Why is it doing it?
3. What can it touch?
4. What changed?
5. Can I replay, fork, undo, or export this?

Concrete TUI upgrades:

* Always show active agent/profile, model, provider, permission mode, token/cost, and dirty-file count.
* Add a persistent task/plan panel.
* Show diffs for every write/edit/apply_patch before or after execution.
* Make approvals explain risk: file write, shell, network, external path, secret exposure, etc.
* Add /trace, /fork, /export, /tasks, and /policy as first-class commands.
* Make session tree navigation a major feature, not a hidden session list.

Textual is a good fit for this because it is a Python TUI framework designed for sophisticated terminal UIs, and it also has a path to browser-hosted interfaces if you eventually want that.  ￼

⸻

The next three releases I’d ship

0.4.1 — hardening release

Goal: make the current repo trustworthy.

Ship:

* CI green: ruff, full tests, packaging check.
* Remove checked-in runtime DB.
* Fix compact_messages() import bug.
* Fix dev dependencies.
* Update stale TODO into a true status roadmap.
* Make apply_patch path-safe and file-tracked.
* Fix LSP manager double-wiring risk in Session.create() / built-in extension setup.
* Add README “alpha limitations” and “known risks.”

0.5 — harness release

Goal: prove Taui is more than a TUI.

Ship:

* /trace run viewer.
* Replay-based eval harness.
* Stable run/turn/tool event schema.
* Session fork UX.
* Export JSONL/Markdown/HTML.
* Extension API v1.
* Working examples directory.
* Permission DSL docs with real tested examples.
* taui doctor command for auth/config/deps/store health.

0.6 — trust release

Goal: make users comfortable letting Taui touch real repos.

Ship:

* Secret redaction.
* Sandbox mode.
* Diff viewer for every mutation.
* Stronger bash policy subjects.
* OTel optional exporter.
* MCP resources/prompts support.
* Provider/plugin loading fixed end-to-end.
* Eval dashboard with historical trend.

⸻

My highest-confidence immediate task list

Start here:

1. Clean repo artifacts: remove taui/tui/.taui/store.db, ignore .taui/.
2. Fix dev dependencies: add explicit pytest, pytest-asyncio, ruff; make uv run pytest and uv run ruff check . the canonical check.
3. Fix compact_messages() import: remove from taui.agent.loop import Message.
4. Update TODO.md: mark implemented items done or move to ROADMAP.md with “done / partial / next.”
5. Make apply_patch safe: path resolution, atomic write, file tracker wiring, traversal tests.
6. Add taui doctor: validate Python version, deps, provider auth, config, writable store, extension errors.
7. Define trace schema: write docs/trace-schema.md and map existing store events to it.
8. Create first eval fixture: one tiny repo, one failing test, one expected success criterion.
9. Fix extension phase ordering: early provider registration before provider creation.
10. Ship 0.4.1 publicly: make PyPI, README, and repo version consistent.

The project already has the right architecture. The next move is to make it boringly reliable, then make that reliability visible through traces, evals, and trust-first UX.
