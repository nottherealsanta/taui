---
title: Create Task
status: active
last_updated: 2026-03-20
---

# Create Task

Depends on: [Task Management](../domains/task-management.md)

## Purpose

Add new tasks to a board. Ability to create a task with title and description.

## User / Business Outcome

Users can add new tasks to track work items on the board.

## Scope

- Create a card with a title and optional description.
- Persist the card to the board's internal list.
- Return the created card to the caller.

## Constraints

- Title is required — enforced by `src/task_board.py#create_card` which raises `ValueError` on empty/whitespace-only titles.
- Title is automatically trimmed of leading/trailing whitespace.
- Description is optional, defaults to empty string in `src/task_board.py#Card`.

## Design

The entry point is `src/task_board.py#create_card` on the `src/task_board.py#TaskBoard` class. It:
1. Strips the title via `title.strip()`.
2. Validates the title is non-empty.
3. Creates a `src/task_board.py#Card` dataclass instance.
4. Appends to the internal `_cards` list.
5. Returns the created card.

## Code References

- `src/task_board.py#TaskBoard` — board class managing card list.
- `src/task_board.py#Card` — card dataclass (title, description).
- `src/task_board.py#create_card` — card creation with validation.

## Tests / Verification

- `tests/example_project/tests/test_task_board.py#test_create_card_trims_and_persists` — verifies title trimming and persistence.
- `tests/example_project/tests/test_task_board.py#test_create_card_requires_title` — verifies empty title raises ValueError.

```
pytest tests/example_project/tests/test_task_board.py -q
```

## Open Questions

None.

## Related Decisions

No decisions recorded yet.
