# Detailed Plan Index

This index links all detailed planning documents derived from `.plans/ARCHITECTURE_PLAN.md`.

## Master Roadmap
- [ ] [`00_IMPLEMENTATION_ROADMAP.md`](./00_IMPLEMENTATION_ROADMAP.md) - Overall phases, dependencies, gates, and risk register.

## Core Primitives
- [ ] [`01_LLM_CORE_PLAN.md`](./01_LLM_CORE_PLAN.md) - `taui.llm` contracts, OpenAI provider, streaming helpers.
- [ ] [`02_TOOLS_CORE_PLAN.md`](./02_TOOLS_CORE_PLAN.md) - Tool protocol, registry, executor pipeline.
- [ ] [`03_BUILTIN_TOOLS_PLAN.md`](./03_BUILTIN_TOOLS_PLAN.md) - MVP built-ins (`read`, `edit`, `write`, `bash`, `glob`, `grep`).
- [ ] [`04_AGENT_LOOP_SESSION_PLAN.md`](./04_AGENT_LOOP_SESSION_PLAN.md) - Agent orchestration, session persistence, event model.

## Interfaces
- [ ] [`05_HEADLESS_CLI_PLAN.md`](./05_HEADLESS_CLI_PLAN.md) - Headless CLI streaming and non-interactive behavior.
- [ ] [`06_TEXTUAL_TUI_PLAN.md`](./06_TEXTUAL_TUI_PLAN.md) - Textual event mapping, approvals, and cancellation UX.

## Platform Controls
- [ ] [`07_CONFIG_POLICY_PLAN.md`](./07_CONFIG_POLICY_PLAN.md) - Config precedence, provider settings, policy decisions.
- [ ] [`08_SKILLS_PLAN.md`](./08_SKILLS_PLAN.md) - Skill loading, activation, instruction/tool injection.

## Provider Expansion
- [ ] [`09_COPILOT_PROVIDER_PLAN.md`](./09_COPILOT_PROVIDER_PLAN.md) - Copilot adapter parity with provider protocol.

## Quality and Governance
- [ ] [`10_TESTING_QA_RELEASE_PLAN.md`](./10_TESTING_QA_RELEASE_PLAN.md) - Test matrix, quality gates, release checklist.
- [ ] [`11_OPEN_DECISIONS_ADR_PLAN.md`](./11_OPEN_DECISIONS_ADR_PLAN.md) - Open decisions and ADR workflow.

## Suggested Execution Order
1. `00_IMPLEMENTATION_ROADMAP.md`
2. `01_LLM_CORE_PLAN.md`
3. `07_CONFIG_POLICY_PLAN.md`
4. `02_TOOLS_CORE_PLAN.md`
5. `03_BUILTIN_TOOLS_PLAN.md`
6. `04_AGENT_LOOP_SESSION_PLAN.md`
7. `05_HEADLESS_CLI_PLAN.md`
8. `06_TEXTUAL_TUI_PLAN.md`
9. `08_SKILLS_PLAN.md`
10. `09_COPILOT_PROVIDER_PLAN.md`
11. `10_TESTING_QA_RELEASE_PLAN.md`
12. `11_OPEN_DECISIONS_ADR_PLAN.md`

## Status Conventions
- `[ ]` Not started
- `[-]` In progress
- `[x]` Complete
