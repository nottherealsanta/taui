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

1. **Tree expansion (composition)** via wiki-link syntax:

```md
- [[task_board.md]]
```

- `[[file.md]]` means "inline that spec file's tree here".
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
- Use `[[...]]` from parent files to compose child files into one tree.

## Metadata format (`{{key: value}}`)

- Machine-parseable metadata uses `{{key: value}}`.
- `status` is required for every actionable node in normal workflows.
- Metadata should be child list items (not content lines):

```md
- Feature {{status: draft}}
    Feature description.
    - {{code_ref: `src/feature.py`}}
    - {{verification: pytest tests/test_feature.py -q}}
```

Examples of supported metadata:

    - {{status: value}}
    - {{depends_on: [Reference](file.md#section)}}
    - {{code_ref: `src/file.py#L10-L20`}}
    - {{verification: pytest tests/test.py -q}}
    - {{collapsed: true}}

Recommended keys:

- `status`
- `depends_on`
- `code_ref`
- `verification`
- `collapsed`

## Status model

Allowed statuses:

- `draft`
- `ready`
- `in-progress`
- `done`
- `blocked`

Transitions:

1. `draft -> ready`
2. `ready -> in-progress`
3. `in-progress -> done`
4. `in-progress -> blocked`
5. `blocked -> in-progress`

Notes:

- `blocked` means execution should pause until clarified.
- Legacy `in_progress` may appear; write new status as `in-progress`.

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

- Primary traversal follows tree edges (list nesting + `[[...]]` expansion).
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
- Shared Lists App {{status: ready}}
    Build a collaborative app where many users share lists.
    - [[server.md]]
    - [[client.md]]
```

```md
- # Server {{status: in-progress}}
    - ## List sharing endpoint {{status: in-progress}}
        - {{depends_on: [Auth model](server.md#auth-model)}}
        - {{code_ref: `taui/server/routes/lists.py#L88-L170`}}
        - {{verification: pytest tests/test_shared_links.py -q}}
```
