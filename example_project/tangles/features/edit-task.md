---
title: Edit Task
status: draft
last_updated: 2026-03-20
---

# Edit Task

Depends on: [Task Management](../domains/task-management.md), [Create Task](create-task.md)

## Purpose

Modify existing tasks. Update title, description, or assignee.

## User / Business Outcome

Users can keep task information up to date as work progresses.

## Scope

- Update a card's title, description, or assignee.
- Persist the updated card.

## Constraints

Depends on Create Task — cannot edit a task that doesn't exist. The card must be retrievable via `src/task_board.py#list_cards`.

## Design

Call `update_card(card_id, fields)` on `src/task_board.py#TaskBoard`. The board validates the card exists before updating. Persistence is handled through `src/database.py#transaction` for atomic updates.

## Code References

- `src/task_board.py#TaskBoard` — board class owning update logic.
- `src/task_board.py#Card` — card data model being updated.
- `src/task_board.py#list_cards` — used to verify card exists.
- `src/database.py#transaction` — atomic persistence for updates.

## Tests / Verification

Not yet implemented.

## Open Questions

- Should partial updates be supported (PATCH semantics)?

## Related Decisions

No decisions recorded yet.
