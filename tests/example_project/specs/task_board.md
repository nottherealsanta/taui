# Task Board
{{status: ready}}

Build a small board with columns and cards for task tracking.

## Create card workflow
{{status: draft}}

Define card fields and validation flow.

### Persist card creation
{{status: done}}
{{code_ref: `tests/example_project/src/task_board.py#L1-L24`}}
{{code_ref: `tests/example_project/tests/test_task_board.py#L1-L21`}}
{{verification: uv run pytest tests/example_project/tests/test_task_board.py -q}}

- behavior: creating a card stores title and optional description.
- constraints: title is required and trimmed.
