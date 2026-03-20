---
title: Delete Task
type: feature
status: draft
owners:
  - example-team
domain: task-management
depends_on:
  - specs/domains/task-management.md
last_updated: 2026-03-20
---

# Delete Task

## Purpose

Remove tasks from the board. Soft-delete by archiving.

## User / Business Outcome

Users can remove tasks that are no longer relevant without losing the historical record.

## Scope

- Archive a card (mark as archived without removing data).
- Archived cards are hidden from default board views.

## Constraints

- Hard deletion is not permitted; all deletes are soft (archive).

## Design

Call `delete_card(card_id)` on the task board, which marks the card as archived in the data layer.

## Code References

Not yet implemented.

## Tests / Verification

Not yet implemented.

## Open Questions

- Should archived cards be recoverable?

## Related Decisions

No decisions recorded yet.
