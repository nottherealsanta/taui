- # Task Board {{status: ready}}
    A collaborative kanban-style board for managing tasks.
    
    Supports **priority levels**, _labels_, and ***@mentions*** for assignees.
    Tasks can be archived with ~~strikethrough~~ formatting.
    
    - ## Create card workflow {{status: done}}
        Define the card creation flow with validation and persistence.
        
        - ### Persist card creation {{status: done}}
            Save new cards to the database with proper validation.
            
            {{code_ref: `tests/example_project/src/task_board.py#L1-L45`}}
            {{verification: pytest tests/example_project/tests/test_task_board.py::test_create_card -q}}
            
            - behavior: Creating a card stores title, description, and optional assignee.
            - constraints: 
                - Title is required and trimmed
                - Description is optional
                - Assignee must be a valid user ID if provided
    
    - ## Update card workflow {{status: in-progress}}
        Modify existing cards with validation.
        
        {{depends_on: [Persist card creation](task_board.md#persist-card-creation)}}
        
        - ### Edit card fields {{status: in-progress}}
            Update title, description, or assignee.
            
            {{code_ref: `tests/example_project/src/task_board.py#L47-L89`}}
            
            - behavior: Partial updates allowed; only provided fields are modified.
            - constraints: Cannot modify archived cards.
    
    - ## Delete card workflow {{status: draft}}
        Soft-delete cards by archiving them.
        
        - ### Archive card {{status: draft}}
            Mark a card as archived without removing data.
            
            - behavior: Sets `archived_at` timestamp.
            - constraints: Already archived cards are idempotent.
    
    - ## Card organization {{status: blocked}}
        Organize cards into columns and support drag-and-drop.
        
        {{question:
        How should we handle card ordering within columns?
        1) Integer position field with reordering
        2) Linked list (next/prev pointers)
        3) Array ordering in parent column document
        4) User can type a custom answer
        }}
        {{answer: 1) Integer position field with reordering}}
        
        - ### Column ordering {{status: blocked}}
            {{depends_on: [Archive card](task_board.md#archive-card)}}
            
            {{question:
            Should archived cards appear in columns?
            1) Yes, in a special "Archived" column
            2) No, filter them out entirely
            3) Configurable per board
            4) User can type a custom answer
            }}
            {{answer: 2) No, filter them out entirely}}
            
            - behavior: Cards with `archived_at` are excluded from column queries.
            - constraints: Must maintain query performance with large datasets.

    - ## Board sharing {{status: ready}}
        Share boards between users with different permission levels.
        
        - ### Permission model {{status: draft}}
            Define owner, editor, and viewer roles.
            
            - behavior: 
                - Owner: full control including delete
                - Editor: create, update, move cards
                - Viewer: read-only access
        
        - ### Invite users {{status: ready}}
            Send invitations to collaborate on boards.
            
            {{code_ref: `tests/example_project/src/task_board.py#L91-L120`}}
            {{verification: pytest tests/example_project/tests/test_task_board.py::test_invite_user -q}}

    - ## Markdown Support
        Cards support rich text with markdown formatting.
        
        - **Bold text** for emphasis
        - _Italic text_ for styling
        - ***Bold italic*** for strong emphasis
        - `inline code` for technical terms
        - ~~Strikethrough~~ for removed content
        - [Links](task_board.md) to other specs
        - [[auth_system.md]] for composition
