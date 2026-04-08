---
title: Task Management
status: active
last_updated: 2026-03-20
---

# Task Management

Depends on: [Data Layer](../domains/data-layer.md)

## Responsibility

Basic task tracking with boards and cards. Owns card creation, editing, deletion, and organization workflows.

## Invariants

- A card cannot be updated unless it was first created and persisted.
- Card creation requires a title — enforced in `src/task_board.py#create_card`.
- All card operations must be persisted to the database via the data layer.

## Interfaces

- `src/task_board.py#create_card` — create a new card with title and optional description.
- `src/task_board.py#list_cards` — return all cards on the board.
- `src/api.py#list_boards` — REST endpoint to list boards for a user.
- `src/api.py#create_board` — REST endpoint to create a new board.

## Key Components

- **Card** (`src/task_board.py#Card`): Core data model — dataclass with title and description.
- **TaskBoard** (`src/task_board.py#TaskBoard`): Board class managing a list of cards. Provides `create_card` and `list_cards`.
- **Create Card** (`src/task_board.py#create_card`): Validates title is non-empty (strips whitespace), creates and persists the card.
- **List Cards** (`src/task_board.py#list_cards`): Returns a copy of the internal card list.
- **API Layer** (`src/api.py#list_boards`, `src/api.py#create_board`): REST endpoints for board operations.

## Important Code References

- `src/task_board.py#TaskBoard`
- `src/task_board.py#Card`
- `src/task_board.py#create_card`
- `src/task_board.py#list_cards`
- `src/api.py#list_boards`
- `src/api.py#create_board`

## Verification

- `tests/example_project/tests/test_task_board.py#test_create_card_trims_and_persists` — verifies card creation with title trimming.
- `tests/example_project/tests/test_task_board.py#test_create_card_requires_title` — verifies title validation.

```
pytest tests/example_project/tests/test_task_board.py -q
```

## Related Features

- [Create Task](../features/create-task.md)
- [Edit Task](../features/edit-task.md)
- [Delete Task](../features/delete-task.md)

## Related Decisions

No decisions recorded yet.
