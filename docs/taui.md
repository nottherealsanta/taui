# Taui Overview

Taui is a programmable coding-agent harness with one interface: a full-screen Textual
TUI. The current product does not include a web UI or REST API.

## Product Shape

- CLI entry and launch: `taui/main.py:29`, `taui/main.py:90`
- TUI app: `taui/tui/app.py:206`
- Session composition root: `taui/session.py:139`
- Agent loop: `taui/agent/loop.py:93`
- Tool policy and execution: `taui/tools/executor.py:42`, `taui/tools/executor.py:180`
- Durable event store: `taui/store/store.py:97`, `taui/store/events.py:10`

## Runtime Path

1. `main()` parses provider/model/session flags and launches `TauiApp`:
   `taui/main.py:90`.
2. `Session.create()` builds the provider, registries, policies, prompt, store, stream
   client, extensions, and `AgentLoop`: `taui/session.py:139`.
3. `TauiApp` sends user input into `Session.send()`: `taui/session.py:330`.
4. `AgentLoop.run()` writes stream events, calls the provider, executes tools, and emits
   final assistant output: `taui/agent/loop.py:174`.
5. `StreamClient` projects stored events back into replayable conversations:
   `taui/store/stream.py:92`.

## Invariants

- Session history is store-backed. Do not add a second event bus for agent lifecycle
  state; use `EventType` and stream projections: `taui/store/events.py:10`.
- Tools return `ToolResult.ok()` or `ToolResult.fail()` for expected outcomes:
  `taui/tools/base.py:24`.
- Permissions are decided before tool execution: `taui/tools/executor.py:219`.
- Provider-specific wire handling stays in `taui/llm_provider/providers/`; the loop uses
  shared provider types from `taui/llm_provider/types.py:151`.
- UI behavior belongs in `taui/tui/app.py:206`; core agent behavior belongs in
  `taui/session.py:139` and `taui/agent/loop.py:93`.

## Maintained Docs

- Runtime: `docs/runtime.md:1`
- Tools and permissions: `docs/tools.md:1`, `docs/permission-dsl.md:1`
- Extensions, hooks, skills, agents: `docs/build-your-harness.md:1`,
  `docs/extension-hooks.md:1`, `docs/agents.md:1`
- Providers: `docs/providers.md:1`
- Context and prompts: `docs/context-strategies.md:1`, `docs/system-prompt.md:1`
- Testing: `docs/testing.md:1`
