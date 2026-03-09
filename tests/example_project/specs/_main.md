- Example Project Simple
    A simplified spec demonstrating all scenarios from spec_standards.md.
    
    - # Task Management {{status: ready}}
        Basic task tracking with boards and cards.
        
        - ## Create Task {{status: done}}
            Add new tasks to a board.
            
            - {{code_ref: `tests/example_project/src/task_board.py#L1-L20`}}
            - {{verification: pytest tests/example_project/tests/test_task_board.py -q}}
        
        - ## Edit Task {{status: in-progress}}
            Modify existing tasks.
            
            - {{depends_on: [Create Task](task_board.md#create-task)}}
        
        - ## Delete Task {{status: draft}}
            Remove tasks from the board.
        
        - ## Organize Tasks {{status: draft}}
            Arrange tasks in columns.
    
    - # Authentication {{status: ready}}
        User authentication system.
        
        - ## Login {{status: done}}
            User login with credentials.
            
            - {{code_ref: `tests/example_project/src/auth.py#L1-L30`}}
            - {{verification: Manual testing with valid credentials}}
        
        - ## Logout {{status: draft}}
            End user session.
    
    - # Data Layer {{status: ready}}
        Database abstraction and operations.
        
        - [[database_schema.md]]
