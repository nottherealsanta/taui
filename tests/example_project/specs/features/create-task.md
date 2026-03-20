---
title: Create Task
type: feature
status: active
owners:
  - example-team
domain: task-management
depends_on:
  - specs/domains/task-management.md
code_refs:
  - src/task_board.py#L1-L45
test_refs:
  - tests/example_project/tests/test_task_board.py::test_create_card
last_updated: 2026-03-20
---

# Create Task

## Purpose

Add new tasks to a board. Ability to create a task with title and description.

## User / Business Outcome

Users can add new tasks to track work items on the board.

## Scope

- Create a card with a title and optional description.
- Persist the card to the database.
- Return the created card to the caller.

## Constraints

- Title is required.
- Description is optional.

## Design

Call `create_card(title, description)` on the task board. The board delegates persistence to the data layer.

## Code References

- `src/task_board.py#L1-L45`

## Tests / Verification

```
pytest tests/example_project/tests/test_task_board.py::test_create_card -q
```

## Open Questions

None.

## Related Decisions

No decisions recorded yet.
