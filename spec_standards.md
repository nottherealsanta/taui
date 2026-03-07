# Spec Tree Standards

This document defines how the `specs/` tree is authored in Taui.

Taui is spec-first. Projects are planned as a tree that starts at high-level intent and narrows down to implementation notes and code references. Agents and users collaborate in the same tree: agents expand details, ask clarifications, and can interleave code work with spec updates.

## Directory and root contract

- All specs live under `specs/`.
- Root file is always `specs/_main.md`.
- `specs/_main.md` must include:
  - project name as first line
  - short project description
  - first-level child index as markdown links

## First-level separation rule

- Every first-level child is its own file or folder:
  - file node: `specs/<child>.md`
  - folder node: `specs/<child>/_main.md`
- Do not inline first-level siblings into a single large file.
- child's md file should follow the same heading levels. for exmaple is _main.md of a level-1 child's folder contains level-2 heading for the child. and that child has a markdown file, it should also start with level-2 heading.

## Heading-driven tree depth

- Hierarchy is represented by headings.
- Level mapping:
  - `#` level 1
  - `##` level 2
  - `###` level 3
  - `####` level 4
  - `#####` level 5
  - `######` level 6
- When depth exceeds 6, continue structure with nested markdown lists under the nearest `h6` node.
- Cross-references use markdown links (not wiki links).
- usually, leaf nodes are at level 3 or 4, but this is flexible based on content needs.

Example:

```md
[Server auth flow](specs/server.md#auth-flow)
```

## Metadata format (`{{key: value}}`)

- All machine-parseable metadata uses `{{key: value}}` blocks.
- `status` is the only required metadata key for every node.
- Recommended keys:
  - `depends_on`
  - `code_ref`
  - `verification`
  - `question`
  - `answer`

Examples:

```md
{{status: draft}}
{{status: in-progress}}
{{depends_on: [specs/server.md#auth-flow](specs/server.md#auth-flow)}}
{{verification: pytest tests/test_auth.py -q}}
```

## Status model and transitions

Allowed statuses:

- `draft`
- `ready`
- `in-progress`
- `done`
- `blocked`

Transition rules:

1. `draft -> ready`: user (or explicit product decision) marks scope actionable.
2. `ready -> in-progress`: an agent picks up execution.
3. `in-progress -> done`: agent finishes work and records strict completion evidence.
4. `in-progress -> blocked`: agent hits blocking ambiguity and must ask a clarification.
5. `blocked -> in-progress`: clarification is answered and integrated.

Notes:

- `blocked` means no further code implementation on that node until clarified.
- Legacy `in_progress` may exist in older docs; use `in-progress` for new or updated nodes.

## Code reference format

- Code anchors use `{{code_ref: ...}}`.
- Format is path-first with optional line span.

Examples:

```md
{{code_ref: `src/server.py`}}
{{code_ref: `src/server.py#L34-L45`}}
{{code_ref: `taui/agent/loop.py#L120-L169`}}
```

## Leaf node termination (flexible)

A leaf can end in either:

1. Detailed notes (recommended: behavior, constraints, files, tests, verification)
2. One or more `code_ref` anchors

Detailed leaves are intentionally flexible. Use the recommended structure when it helps clarity, but do not require every field if it adds noise.

Example detailed leaf:

```md
#### Session expiration policy
{{status: in-progress}}

- behavior: access token expires at fixed TTL.
- constraints: must not break websocket reconnect.
- tests: add expiry boundary tests.
```

## Clarifications (`{{question: ...}}`)

- Agents ask clarifications inline on the relevant node.
- Question format is a multi-line `{{question: ...}}` block.
- Each question includes 3 concrete options and a 4th free-text path for user input.

Question format:

```md
{{question:
Should session expiry be fixed or sliding?
1) Fixed 24h TTL
2) Sliding window on activity
3) Per-project configurable TTL
4) User can type a custom answer
}}
```

Resolution flow:

1. Record user response in `{{answer: ...}}` directly below the question.
2. Integrate the decision into the node's spec text.
3. Keep question+answer for traceability unless intentionally cleaned in a follow-up pass.

Example:

```md
{{question:
How should failed invites be retried?
1) Retry 3 times with backoff
2) Retry once only
3) No retry; manual resend only
4) User can type a custom answer
}}
{{answer: 1) Retry 3 times with backoff, cap at 30s}}

- behavior: invite delivery retries 3 times with exponential backoff up to 30s.
```

## Dependencies and traversal

- Traversal order is deterministic:
  1. heading/tree edges
  2. dependency edges via `{{depends_on: ...}}`
- Do not create dependency cycles.

## Traceability tiers

- `done` nodes are strict:
  - must include relevant `code_ref` entries for implemented behavior
  - must include verification evidence (`{{verification: ...}}`, test output refs, or equivalent)
- `draft`, `ready`, `in-progress`, and `blocked` have no strict traceability requirement.

## Clarification and amendment rules

- If ambiguity blocks execution, mark `{{status: blocked}}` and ask a `{{question: ...}}`.
- Do not continue coding a blocked node.
- If implementation reality conflicts with spec intent, propose an explicit amendment in-spec.
- Never silently mutate spec intent during execution.

## Non-negotiable invariants

1. No major coding task without a target node in `specs/`.
2. No silent spec drift; use amendment flow.
3. `done` requires verification-level evidence and code references.

## End-to-end example

```md
# Shared Lists App
{{status: ready}}

- Build a collaborative app where many users share lists.
- Child index:
  - [Server](specs/server.md#server)
  - [Client](specs/client.md#client)

## Server
{{status: in-progress}}

### FastAPI stack
{{status: in-progress}}

#### List sharing endpoint
{{status: blocked}}
{{depends_on: [specs/server.md#auth-model](specs/server.md#auth-model)}}

{{question:
How should anonymous users access shared lists?
1) Read-only via signed links
2) No anonymous access
3) Optional by project setting
4) User can type a custom answer
}}
{{answer: 1) Read-only via signed links, 48h expiry}}

- behavior: signed links provide read-only access for 48h.
- constraints: revoked links must fail immediately.
- tests: add signed-link expiry and revocation tests.
{{code_ref: `taui/server/routes/lists.py#L88-L170`}}
{{verification: pytest tests/test_shared_links.py -q}}

#### Auth model
{{status: done}}
{{code_ref: `taui/server/auth.py#L1-L120`}}
{{verification: pytest tests/test_auth.py -q}}
```
