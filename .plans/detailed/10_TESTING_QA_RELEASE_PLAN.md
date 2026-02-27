# Testing, QA, and Release Detailed Plan

## Objective
Define a practical quality strategy that verifies architecture correctness, safety guarantees, and interface parity before release.

## Scope
- Unit, integration, and end-to-end testing across `llm`, `tools`, `agent`, `config`, `skills`, CLI, and TUI.
- Release readiness checks for MVP milestones.

## Test Pyramid
- Unit tests: data contracts, registries, policy logic, stream helpers.
- Integration tests: provider adapters, executor pipeline, agent loop with tool reinjection.
- End-to-end tests: CLI and TUI smoke flows using same core runtime.

## Priority Test Matrix
- P0 safety:
  - read-before-edit/write guard
  - policy allow/confirm/deny enforcement
  - timeout behavior in `bash` and executor
  - bash workspace boundary and output truncation enforcement
- P0 correctness:
  - provider event mapping and cancellation
  - approval-required and approval-resolved event sequencing
  - agent loop stop condition and tool result reinjection
  - session persistence round-trip with locking and atomic writes
  - token budget compaction and hard-limit summarization behavior
- P1 interface parity:
  - same prompt/tool scenario in CLI and TUI yields consistent outcomes
- P1 skills/config:
  - config precedence and skill activation order

## Environment Matrix
- Python versions targeted by project.
- Local file system operations with temporary workspace fixtures.
- Network-mocked provider tests plus optional live provider smoke tests.

## Deterministic Stream Fixtures
- Maintain canonical fixture files for provider streams covering:
  - text-only deltas
  - partial tool-call deltas and final `tool_call_done`
  - provider error mid-stream
  - usage emission on completion
- Replay fixtures in unit/integration tests to avoid live-network flakiness.
- Keep fixture schema versioned to match `StreamEvent` contract updates.

## Automation Plan
- Pre-merge checks:
  - formatting/linting/type checks
  - unit and integration test suites
  - deterministic fixture replay suite
- Nightly or scheduled checks:
  - live provider smoke tests (if credentials available)
  - long-running stream/cancellation stress tests

## Quality Gates per Milestone
- Gate A: `llm` contracts and OpenAI provider tests green.
- Gate B: tools executor and built-in safety tests green.
- Gate C: agent loop integration tests green.
- Gate D: CLI and TUI parity smoke tests green.
- Gate E: config/skills and Copilot provider tests green.

## Manual QA Checklist
- Validate confirm prompts for `edit`, `write`, `bash`.
- Validate non-interactive confirm-required behavior is deterministic and safe.
- Validate denied tool behavior with clear user feedback.
- Validate interruption/cancellation does not corrupt session state.
- Validate large output truncation messaging in both interfaces.

## Release Checklist
- All P0 tests passing.
- No known high-severity safety bugs open.
- Documentation updated for config, policies, and interfaces.
- Example workflows validated end-to-end.
- Known follow-up decisions tracked in ADR plan.

## Exit Criteria
- Reproducible test runs and stable pass rate.
- Interface parity confirmed for representative scenarios.
- Safety and policy behavior verified under error conditions.
