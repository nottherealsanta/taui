# Open Decisions and ADR Detailed Plan

## Objective
Track unresolved architecture follow-ups as explicit decisions with criteria, timeline, and ownership expectations.

## Source Follow-ups
From `.plans/ARCHITECTURE_PLAN.md`:
- Prompt strategy (minimal default prompt vs fuller policy prompt).
- Plugin package contract for `taui install`.
- Session tree/branching in MVP vs post-MVP.

## Decision Framework
- For each decision capture:
  - context and current constraints
  - options considered
  - evaluation criteria
  - recommendation
  - consequence and migration cost

## Decision 1: Prompt Strategy
- Options:
  - A: minimal default prompt with strict tool/policy scaffolding
  - B: fuller policy-rich prompt with more behavior guidance
- Evaluation criteria:
  - reliability of tool use
  - token/cost impact
  - maintainability and auditability
- Proposed initial default: A for MVP, with optional B profile flag for experimentation.

## Decision 2: Extension Contract (`taui install`)
- Options:
  - A: Python entry-point plugins
  - B: file-based drop-ins under `~/.config/taui/extensions/`
- Evaluation criteria:
  - isolation and security model
  - ease of local authoring
  - cross-platform packaging overhead
- Proposed initial default: B for MVP simplicity, keep A as post-MVP hardening path.

## Decision 3: Session Branching
- Options:
  - A: linear sessions only in MVP
  - B: branching tree in MVP
- Evaluation criteria:
  - implementation complexity
  - UX clarity in CLI/TUI
  - persistence schema stability
- Proposed initial default: A for MVP, design schema with forward-compatible branch metadata.

## ADR File Template
Create ADR files under `.plans/adr/` using this structure:

```markdown
# ADR-XXXX: <Title>

## Status
Proposed | Accepted | Rejected | Superseded

## Context
<why this is a decision now>

## Decision
<chosen option and rationale>

## Consequences
<trade-offs, follow-up work, migration>

## Alternatives Considered
- <option 1>
- <option 2>
```

## Decision Timeline
- Before Phase 5 completion: prompt strategy decision.
- Before Phase 8 completion: extension contract decision.
- Before Phase 9 completion: session branching MVP decision.

## Exit Criteria
- Each open follow-up has an ADR with status.
- Chosen decisions are reflected in implementation plans and docs.
- Deferred decisions include explicit revisit trigger and owner.
