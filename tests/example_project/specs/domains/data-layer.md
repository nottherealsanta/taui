---
title: Data Layer
status: active
domain: data-layer
code_refs:
  - src/database.py
last_updated: 2026-03-20
---

# Data Layer

## Responsibility

Database abstraction and operations. Defines data models and relationships.

## Invariants

- All database operations must go through this layer.
- Schema changes require a migration.

## Interfaces

- `get_user(user_id)` → user
- `create_task(data)` → task
- `update_task(task_id, data)` → task
- `delete_task(task_id)` → None

## Key Components

- **Users Table** (`src/database.py#L1-L20`): Stores user records with id, username, and password hash.
- **Tasks Table** (`src/database.py#L22-L45`): Stores task records with id, title, description, assignee, and archived status.

## Important Code References

- `src/database.py`

## Verification

Unit tests cover model operations. Run via:

```
pytest tests/example_project/tests/ -q
```

## Related Features

No features directly owned by this domain; it supports task management and authentication.

## Related Decisions

No decisions recorded yet.
