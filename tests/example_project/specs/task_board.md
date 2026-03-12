- # Task Board
    A collaborative kanban-style board for managing tasks.
    - {{status: ready}}

    - ## Create card workflow
        Define the card creation flow with validation and persistence.
        - {{status: done}}

        - ### Persist card creation
            Save new cards to the database with proper validation.
            - {{status: done}}
            - {{code_ref: `src/task_board.py#L1-L45`}}
            - {{verification: pytest tests/example_project/tests/test_task_board.py::test_create_card -q}}

    - ## Update card workflow
        Modify existing cards with validation.
        - {{status: in_progress}}
        - {{depends_on: [Persist card creation](task_board.md#persist-card-creation)}}

        - ### Edit card fields
            Update title, description, or assignee.
            - {{status: in_progress}}
            - {{code_ref: `src/task_board.py#L47-L89`}}

    - ## Delete card workflow
        Soft-delete cards by archiving them.
        - {{status: draft}}

        - ### Archive card
            Mark a card as archived without removing data.
            - {{status: draft}}

    - ## Card organization
        Organize cards into columns and support drag-and-drop.
        - {{status: draft}}

        - 
            - {{status: draft}}
            - {{depends_on: [Archive card](task_board.md#archive-card)}}
