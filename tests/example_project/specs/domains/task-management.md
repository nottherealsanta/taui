---
title: Task Management
type: domain
status: active
owners:
  - example-team
domain: task-management
depends_on:
  - specs/domains/data-layer.md
code_refs:
  - src/task_board.py
test_refs:
  - tests/example_project/tests/test_task_board.py
last_updated: 2026-03-20
---

# Task Management

## Responsibility

Basic task tracking with boards and cards. Owns card creation, editing, deletion, and organization workflows.

## Invariants

- A card cannot be updated unless it was first created and persisted.
- Card creation requires a title.
- All card operations must be persisted to the database via the data layer.

## Interfaces

- `create_card(title, description)` → card
- `update_card(card_id, fields)` → card
- `delete_card(card_id)` → None
- `organize_cards(board_id, order)` → None

## Key Components

- **Create card workflow**: Define the card creation flow with validation and persistence.
- **Update card workflow**: Modify existing cards with validation.
- **Delete card workflow**: Soft-delete cards by archiving them.
- **Card organization**: Organize cards into columns and support drag-and-drop.

## Important Code References

- `src/task_board.py`

## Verification

```
pytest tests/example_project/tests/test_task_board.py -q
```

## Related Features

- [Create Task](../features/create-task.md)
- [Edit Task](../features/edit-task.md)
- [Delete Task](../features/delete-task.md)

## Related Decisions

No decisions recorded yet.
