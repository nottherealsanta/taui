# Spec Tree Standards

This document is the canonical specification for Taui's spec system.

Taui is spec-first. Projects are authored as a tree that starts at high-level intent and narrows down to implementation details, verification, and code references. Agents and users collaborate in the same tree.

## Core model

- Spec files live under `specs/`.
- Root entry file is `specs/_main.md`.
- The tree is list-driven: every node is a markdown list item.
- Nodes can include heading prefixes (`#`, `##`, etc.) in the list-item text.
- Heading prefixes are part of node markdown and do not create nodes on their own.
- L0 (project name) does not use a heading prefix.

- ## Tree syntax (list of list)

Each node is a list item. Nesting is represented by indentation.

- Use **4 spaces per level**.
- Use `- ` for list items (parser also accepts `*` and `+`).
- Heading convention:
  - L0 project node: plain text (`- Example Project`)
  - L1 node text starts with `# `
  - L2 node text starts with `## `
  - L3 node text starts with `### `
  - and so on

Example:

```md
- Project
    Project intent paragraph line 1.
    Project intent paragraph line 2.
    - # Feature A
        Feature A intent.
        - ## Leaf task
            - {{code_ref: `src/feature.py`}}
            - {{verification: pytest tests/test.py -q}}
```

## Node content vs child nodes

Each node is a single markdown block:

1. **First line**: the list item line itself (`- # Node heading`)
2. **Continuation lines**: indented lines under that item that do not start a child list item

Rules:

- Continuation text (indented, no new list marker) belongs to the same node markdown block.
- A nested list item at the next indent level is a child node.
- Empty lines are allowed inside node content.

Example:

```md
- # Task Board
    Build a small board with columns and cards.

    This second paragraph is still Task Board content.
    - ## Create card workflow
        Define fields and validation.
```

## Cross-file composition and references

There are two link semantics:

1. **Tree expansion (composition)** via `{{tree: ...}}` metadata:

```md
- {{tree: [Task Board](./task_board.md)}}
```

- `{{tree: [Title](./file.md)}}` means "inline that spec file's tree here".
- The value is a standard markdown link — clickable in any markdown viewer.
- Expansion happens at the same tree level position.
- This is how multi-file trees are composed.

2. **Reference links** via normal markdown links:

```md
[Task Board](task_board.md#task-board)
```

- Regular `[text](target)` links are references only.
- They do not inline/expand tree structure.

## Directory contract

- Root file: `specs/_main.md`.
- First-level children should be split into separate files/folders where practical:
  - file node: `specs/<child>.md`
  - folder node: `specs/<child>/_main.md`
- Use `{{tree: [Title](./path)}}` from parent files to compose child files into one tree.

## Metadata format (`{{key: value}}`)

- Machine-parseable metadata uses `{{key: value}}`.
- `status` is required for every actionable node in normal workflows.
- Canonical status representation is a child metadata item (`- {{status: ...}}`). Inline status on the title line is legacy-compatible but should not be authored in new specs.
- Metadata should be child list items (not content lines):

```md
- Feature
    Feature description.
    - {{status: draft}}
    - {{code_ref: `src/feature.py`}}
    - {{verification: pytest tests/test_feature.py -q}}
```

Examples of supported metadata:

    - {{status: value}}
    - {{tree: [Child File](./child.md)}}
    - {{depends_on: [Reference](file.md#section)}}
    - {{related_to: [Reference](file.md#section)}}
    - {{code_ref: `src/file.py#L10-L20`}}
    - {{verification: pytest tests/test.py -q}}

Recommended keys:

- `status`
- `tree`
- `depends_on`
- `related_to`
- `code_ref`
- `verification`

## Status model

Allowed statuses:

- `draft`
- `ready`
- `in_progress`
- `to_review`
- `done`
- `blocked`

Transitions:

1. `draft -> ready`
2. `ready -> in_progress`
3. `in_progress -> done`
4. `in_progress -> blocked`
5. `in_progress -> to_review`
6. `to_review -> done`
7. `to_review -> in_progress`
8. `blocked -> in_progress`

Notes:

- `blocked` means execution should pause until clarified.
- Legacy `in-progress` may appear; write new status as `in_progress`.
- `collapsed` is UI state only and should not be written to markdown.

## Intent extraction

Node intent is derived from the first prose-like content lines under a node.

- Metadata lines and pure links are ignored for intent.
- Intent may span multiple lines/paragraphs.

## Code references

Use `{{code_ref: ...}}` as a child list item.

Example:

```md
- ## Feature implementation
    - {{code_ref: `src/server.py`}}
    - {{code_ref: `src/server.py#L34-L45`}}
```

## Verification evidence

Use `{{verification: ...}}` as a child list item.

Example:

```md
- ## Feature implementation
    - {{verification: pytest tests/test_auth.py -q}}
```

## Dependencies and traversal

- Primary traversal follows tree edges (list nesting + `{{tree: ...}}` expansion).
- Dependency edges from `{{depends_on: ...}}` are secondary constraints.
- Do not introduce dependency cycles.

## Traceability tiers

- `done` nodes are strict:
  - include relevant `code_ref`
  - include verification evidence
- Other statuses are flexible.

## Non-negotiable invariants

1. No major coding task without target node(s) in `specs/`.
2. No silent spec drift; use explicit amendment/clarification.
3. `done` requires verification-level evidence and code references.

## End-to-end example

```md
- Shared Lists App
    Build a collaborative app where many users share lists.
    - {{status: ready}}
    - {{tree: [Server](./server.md)}}
    - {{tree: [Client](./client.md)}}
```

```md
- # Server
    - {{status: in_progress}}
    - ## List sharing endpoint
        - {{status: in_progress}}
        - {{depends_on: [Auth model](server.md#auth-model)}}
        - {{code_ref: `taui/server/routes/lists.py#L88-L170`}}
        - {{verification: pytest tests/test_shared_links.py -q}}
```
