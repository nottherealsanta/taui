---
title: Delete Task
status: draft
last_updated: 2026-03-20
---

# Delete Task

Depends on: [Task Management](../domains/task-management.md)

## Purpose

Remove tasks from the board. Soft-delete by archiving.

## User / Business Outcome

Users can remove tasks that are no longer relevant without losing the historical record.

## Scope

- Archive a card (mark as archived without removing data).
- Archived cards are hidden from default board views returned by `src/task_board.py#list_cards`.

## Constraints

- Hard deletion is not permitted; all deletes are soft (archive).
- Archival must be persisted atomically via `src/database.py#transaction`.

## Design

Call `delete_card(card_id)` on `src/task_board.py#TaskBoard`, which marks the `src/task_board.py#Card` as archived. Persistence is handled by `src/database.py#DatabaseService`.

## Code References

- `src/task_board.py#TaskBoard` — board class owning delete logic.
- `src/task_board.py#Card` — card data model being archived.
- `src/task_board.py#list_cards` — filters out archived cards.
- `src/database.py#transaction` — atomic archival persistence.

## Tests / Verification

Not yet implemented.

## Open Questions

- Should archived cards be recoverable?

## Related Decisions

No decisions recorded yet.
