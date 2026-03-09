- # Task Board {{status: ready}}
    A collaborative kanban-style board for managing tasks.
    
    - ## Create card workflow {{status: done}}
        Define the card creation flow with validation and persistence.
        
        - ### Persist card creation {{status: done}}
            Save new cards to the database with proper validation.
            
            - {{code_ref: `tests/example_project/src/task_board.py#L1-L45`}}
            - {{verification: pytest tests/example_project/tests/test_task_board.py::test_create_card -q}}
    
    - ## Update card workflow {{status: in-progress}}
        Modify existing cards with validation.
        
        - {{depends_on: [Persist card creation](task_board.md#persist-card-creation)}}
        
        - ### Edit card fields {{status: in-progress}}
            Update title, description, or assignee.
            
            - {{code_ref: `tests/example_project/src/task_board.py#L47-L89`}}
    
    - ## Delete card workflow {{status: draft}}
        Soft-delete cards by archiving them.
        
        - ### Archive card {{status: draft}}
            Mark a card as archived without removing data.
    
    - ## Card organization {{status: draft}}
        Organize cards into columns and support drag-and-drop.
        
        - ### Column ordering {{status: draft}}
            - {{depends_on: [Archive card](task_board.md#archive-card)}}
