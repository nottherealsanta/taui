- # API Endpoints {{status: in-progress}}
    REST API for all client interactions.
    
    Base URL: `/api/v1`
    
    - ## Authentication endpoints {{status: done}}
        Endpoints for login, logout, and session management.
        
        {{depends_on: [Auth System](auth_system.md)}}
        
        - ### POST /auth/login {{status: done}}
            Authenticate and receive session token.
            
            {{code_ref: `tests/example_project/src/api.py#L1-L40`}}
            {{verification: pytest tests/example_project/tests/test_api.py::test_login_endpoint -q}}
            
            - behavior: Returns 200 with token on success, 401 on failure.
            - constraints: Rate limited, see [Auth System](auth_system.md#user-login).
        
        - ### POST /auth/logout {{status: done}}
            Invalidate current session.
            
            {{code_ref: `tests/example_project/src/api.py#L42-L65`}}
            {{verification: pytest tests/example_project/tests/test_api.py::test_logout_endpoint -q}}
            
            - behavior: Returns 204 on success, 401 if not authenticated.
            - constraints: Idempotent (safe to call multiple times).
        
        - ### GET /auth/session {{status: done}}
            Verify session validity.
            
            {{code_ref: `tests/example_project/src/api.py#L67-L85`}}
            {{verification: pytest tests/example_project/tests/test_api.py::test_session_endpoint -q}}
            
            - behavior: Returns 200 with user info if valid, 401 if invalid.
            - constraints: Must check session expiration.
    
    - ## Task board endpoints {{status: in-progress}}
        CRUD operations for task boards and cards.
        
        {{depends_on: [Task Board](task_board.md#task-board)}}
        
        - ### GET /boards {{status: done}}
            List all boards for authenticated user.
            
            {{code_ref: `tests/example_project/src/api.py#L87-L115`}}
            {{verification: pytest tests/example_project/tests/test_api.py::test_list_boards -q}}
            
            - behavior: Returns paginated list of boards.
            - constraints: Only show boards user has access to.
        
        - ### POST /boards {{status: in-progress}}
            Create a new board.
            
            {{code_ref: `tests/example_project/src/api.py#L117-L145`}}
            
            - behavior: Returns 201 with new board ID.
            - constraints: Title required, max 100 chars.
        
        - ### GET /boards/{id} {{status: draft}}
            Get board details with cards.
            
            - behavior: Returns board with nested columns and cards.
            - constraints: Must have read permission on board.
        
        - ### POST /boards/{id}/cards {{status: draft}}
            Create a new card in board.
            
            {{depends_on: [Persist card creation](task_board.md#persist-card-creation)}}
            
            - behavior: Returns 201 with new card ID.
            - constraints: Must have write permission on board.
    
    - ## Error handling
        Standardized error responses.
        
        All errors return JSON with:
        ```json
        {
            "error": "ERROR_CODE",
            "message": "Human-readable description",
            "details": {}
        }
        ```
        
        - Error codes:
            - `UNAUTHORIZED`: Authentication required
            - `FORBIDDEN`: Permission denied
            - `NOT_FOUND`: Resource doesn't exist
            - `VALIDATION_ERROR`: Input validation failed
            - `RATE_LIMITED`: Too many requests
    
    - ## Rate limiting
        API rate limiting configuration.
        
        - Default limits:
            - 100 requests per minute per user
            - 1000 requests per hour per user
            - 10 login attempts per minute per IP
        
        - Headers:
            - `X-RateLimit-Limit`: Request limit
            - `X-RateLimit-Remaining`: Remaining requests
            - `X-RateLimit-Reset`: Unix timestamp when limit resets

    - ## Sub-features
        Detailed endpoint specifications.
        
        - [[users.md]]
