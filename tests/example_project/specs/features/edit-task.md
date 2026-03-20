---
title: Edit Task
type: feature
status: draft
owners:
  - example-team
domain: task-management
depends_on:
  - specs/domains/task-management.md
  - specs/features/create-task.md
code_refs:
  - src/task_board.py#L47-L89
last_updated: 2026-03-20
---

# Edit Task

## Purpose

Modify existing tasks. Update title, description, or assignee.

## User / Business Outcome

Users can keep task information up to date as work progresses.

## Scope

- Update a card's title, description, or assignee.
- Persist the updated card.

## Constraints

Depends on Create Task — cannot edit a task that doesn't exist.

## Design

Call `update_card(card_id, fields)` on the task board. The board validates the card exists before updating.

## Code References

- `src/task_board.py#L47-L89`

## Tests / Verification

Not yet implemented.

## Open Questions

- Should partial updates be supported (PATCH semantics)?

## Related Decisions

No decisions recorded yet.
