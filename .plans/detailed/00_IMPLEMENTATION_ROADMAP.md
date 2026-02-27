# Detailed Implementation Roadmap

## Objective
Deliver the architecture in `.plans/ARCHITECTURE_PLAN.md` as a sequence of buildable, testable milestones while preserving the project philosophy: minimal core and maximum composability.

## Source Anchors
- Design philosophy: minimal core, composable primitives.
- Module structure under `taui/` with `llm`, `tools`, `agent`, `config`, and `skills`.
- Implementation order items 1 through 9.
- Known follow-ups (prompt strategy, plugin contract, session branching).

## Scope
- In scope: implementation planning for all modules listed in the architecture plan, including CLI and Textual integration.
- In scope: quality gates, risk controls, and release readiness criteria.
- Out of scope: final product policy language, external plugin marketplace, long-term branching UX.

## Workstreams
- `W1 LLM Core`: `llm/types.py`, `llm/provider.py`, `llm/registry.py`, `llm/providers/openai.py`, `llm/stream.py`.
- `W2 Tooling Core`: `tools/base.py`, `tools/registry.py`, `tools/executor.py`.
- `W3 Built-in Tools`: `read`, `edit`, `write`, `bash`, `glob`, `grep`.
- `W4 Agent Runtime`: `agent/loop.py`, `agent/session.py`, `agent/events.py`.
- `W5 Interfaces`: `cli.py` and `app.py` consuming the same agent event stream.
- `W6 Config and Policy`: `config/settings.py`, `config/policies.py` and config file contract.
- `W7 Skills`: loader, activation rules, and built-in skill packaging.
- `W8 Provider Expansion`: `llm/providers/copilot.py`.

## Phase Plan

### Phase 0: Repository Scaffolding and Conventions
- Create package layout exactly as defined in architecture.
- Add common typing and error conventions across modules.
- Define shared event naming and serialization expectations.
- Exit criteria: skeleton imports resolve, no circular imports in baseline.

### Phase 1: LLM Primitive
- Implement type contracts and provider protocol first.
- Build OpenAI provider with streaming-first completion behavior.
- Add model-to-provider routing via registry.
- Exit criteria: streaming completion works in isolation with usage reporting.

### Phase 2: Config and Policy Foundation
- Implement `config/settings.py` and `config/policies.py` baseline contracts early.
- Define precedence rules and provider credential resolution.
- Finalize policy decision outcomes (`allow`, `confirm`, `deny`) consumed by executor and interfaces.
- Exit criteria: policy/config contracts are stable and available for all downstream phases.

### Phase 3: Tool Primitive
- Implement tool contract dataclasses/protocols.
- Implement registry discovery and schema export.
- Implement executor validation, policy checks, timeout, and normalized errors.
- Exit criteria: tool call can be validated and executed through one common path.

### Phase 4: Built-in Toolset (MVP)
- Implement all six built-ins with predictable errors and metadata.
- Enforce read-before-edit and read-before-write guard using session read tracking.
- Ensure `edit` exact-match behavior and ambiguity detection.
- Exit criteria: each built-in passes contract and safety tests.

### Phase 5: Agent Runtime
- Implement think-act-observe loop with tool reinjection.
- Implement session persistence and message history operations.
- Implement unified agent events including approval-request lifecycle for both interface modes.
- Exit criteria: multi-turn loop with tool calls reaches deterministic stop condition.

### Phase 6: Headless CLI
- Build stdin/stdout interface over the shared runtime.
- Support streaming text and tool activity output.
- Implement exit codes and script-safe output mode.
- Exit criteria: non-interactive invocation can complete full tool-using turns.

### Phase 7: Textual TUI Integration
- Connect UI to same `AsyncIterator[AgentEvent]` pipeline as CLI.
- Provide approval flows for gated tools and cancellation controls.
- Handle long-running streams without blocking UI.
- Exit criteria: full turn execution parity with CLI behavior.

### Phase 8: Skills
- Load skills from both user config and built-in package paths.
- Activate matching skills and inject instructions/tools into turn context.
- Add deterministic merge behavior for overlapping skill tools/instructions.
- Exit criteria: skills can be enabled and influence one turn predictably.

### Phase 9: Copilot Provider
- Implement provider parity adapter with capability signaling.
- Align streaming and tool-call semantics with provider protocol.
- Exit criteria: registry can route `copilot:*` models and complete end-to-end turns.

## Dependency Graph (High-Level)
- `W6 -> W2/W3/W4/W5`: Policy and settings are upstream dependencies for executor behavior and interface approvals.
- `W1 -> W4`: Agent loop depends on provider and stream contracts.
- `W2 -> W3 -> W4`: Runtime tool execution depends on executor and concrete tools.
- `W4 -> W5`: Interfaces are thin consumers of the same runtime events.
- `W7 -> W4/W5`: Skills affect turn context and visible behavior.
- `W8 -> W1/W4`: New provider must satisfy core protocol and runtime assumptions.

## Quality Gates
- Gate A (Core Contracts): type checks pass for `llm` and `tools` core modules.
- Gate B (Runtime Loop): deterministic event ordering, approval events, and stop conditions validated.
- Gate C (Interface Parity): same prompt/input produces compatible outputs in CLI and TUI.
- Gate D (Safety): policy checks, read guards, timeout handling, and bash boundaries validated.
- Gate E (Release): smoke suite passes for OpenAI provider and built-ins.

## Definition of Done (Global)
- Required files exist and implement architecture contracts.
- Unit tests cover success path plus policy/error edges.
- One end-to-end scenario validates user -> tool call -> tool result -> final answer.
- Documentation reflects commands, configuration, and known limitations.
- No unresolved blocking decision in the current milestone.

## Risk Register
- Provider API drift: isolate provider-specific translation layers and add adapter tests.
- Tool safety regressions: centralize policy and guard checks in executor and session.
- Event contract drift between CLI/TUI: enforce shared typed events and contract tests.
- Session persistence corruption: add versioned serialization and basic recovery strategy.

## Reporting Cadence
- Per-phase demo showing one real turn through the current capability set.
- Checklist updates in `.plans/detailed/` as milestones complete.
- Immediate documentation update when contracts change.
