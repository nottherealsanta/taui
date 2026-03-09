- # API Endpoints {{status: in-progress}}
    REST API for all client interactions.
    
    Base URL: `/api/v1`
    
    - ## Authentication endpoints {{status: done}}
        Endpoints for login, logout, and session management.
        
        - {{depends_on: [Auth System](auth_system.md)}}
        
        - ### POST /auth/login {{status: done}}
            Authenticate and receive session token.
            
            - {{code_ref: `tests/example_project/src/api.py#L1-L40`}}
            - {{verification: pytest tests/example_project/tests/test_api.py::test_login_endpoint -q}}
        
        - ### POST /auth/logout {{status: done}}
            Invalidate current session.
            
            - {{code_ref: `tests/example_project/src/api.py#L42-L65`}}
            - {{verification: pytest tests/example_project/tests/test_api.py::test_logout_endpoint -q}}
        
        - ### GET /auth/session {{status: done}}
            Verify session validity.
            
            - {{code_ref: `tests/example_project/src/api.py#L67-L85`}}
            - {{verification: pytest tests/example_project/tests/test_api.py::test_session_endpoint -q}}
    
    - ## Task board endpoints {{status: in-progress}}
        CRUD operations for task boards and cards.
        
        - {{depends_on: [Task Board](task_board.md#task-board)}}
        
        - ### GET /boards {{status: done}}
            List all boards for authenticated user.
            
            - {{code_ref: `tests/example_project/src/api.py#L87-L115`}}
            - {{verification: pytest tests/example_project/tests/test_api.py::test_list_boards -q}}
        
        - ### POST /boards {{status: in-progress}}
            Create a new board.
            
            - {{code_ref: `tests/example_project/src/api.py#L117-L145`}}
        
        - ### GET /boards/{id} {{status: draft}}
            Get board details with cards.
        
        - ### POST /boards/{id}/cards {{status: draft}}
            Create a new card in board.
            
            - {{depends_on: [Persist card creation](task_board.md#persist-card-creation)}}
    
    - [[users.md]]
