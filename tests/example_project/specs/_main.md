- 

- 

- 

- Example Project Simple
    A simplified spec demonstrating all scenarios from spec_standards.md.

    - # Task Management
        Basic task tracking with boards and cards.
        - {{status: ready}}

        - ## Create Task
            Add new tasks to a board. `knmlw`
            - {{status: done}}
            - {{code_ref: `./src/task_board.py#L1-L20`}}
            - {{verification: pytest ./tests/test_task_board.py -q}}

            - ability to create a task with title and _description_

        - ## Edit Task
            Modify existing tasks.
            - {{status: in_progress}}
            - {{depends_on: [Create Task](_main.md#create-task)}}

        - ## Delete Task
            Remove tasks from the board.
            - {{status: draft}}

            - fef
                - {{status: draft}}

    - # Authentication
        User authentication system.
        - {{status: ready}}

        - ## Login
            User login with credentials.
            - {{status: done}}
            - {{code_ref: `./src/auth.py#L1-L30`}}
            - {{verification: Manual testing with valid credentials}}

        - ## Logout
            End user session.
            - {{status: draft}}

    - # Data Layer
        Database abstraction and operations.
        - {{status: ready}}
        - {{tree: [Database Schema](database_schema.md)}}
