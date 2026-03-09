- # Auth System {{status: in-progress}}
    Handle user authentication and session management securely.
    
    - ## User login {{status: done}}
        Authenticate users with username and password.
        
        - ### Validate credentials {{status: done}}
            Check password hash against stored value.
            
            - {{code_ref: `tests/example_project/src/auth.py#L1-L35`}}
            - {{verification: pytest tests/example_project/tests/test_auth.py::test_login -q}}
    
    - ## Session management {{status: done}}
        Manage active user sessions with TTL.
        
        - {{depends_on: [Validate credentials](auth_system.md#validate-credentials)}}
        
        - ### Create session {{status: done}}
            Generate session token with expiration.
            
            - {{code_ref: `tests/example_project/src/auth.py#L37-L65`}}
            - {{verification: pytest tests/example_project/tests/test_auth.py::test_create_session -q}}
        
        - ### Validate session {{status: done}}
            Check if session token is valid and not expired.
            
            - {{code_ref: `tests/example_project/src/auth.py#L67-L85`}}
            - {{verification: pytest tests/example_project/tests/test_auth.py::test_validate_session -q}}
        
        - ### Revoke session {{status: done}}
            Invalidate a session before natural expiration.
            
            - {{code_ref: `tests/example_project/src/auth.py#L87-L102`}}
            - {{verification: pytest tests/example_project/tests/test_auth.py::test_revoke_session -q}}
    
    - ## Password reset {{status: draft}}
        Allow users to reset forgotten passwords.
        
        - ### Generate reset token {{status: draft}}
            Create time-limited single-use reset token.
        
        - ### Send reset notification {{status: draft}}
            Deliver token via user's preferred channel.
            
            - {{depends_on: [Generate reset token](auth_system.md#generate-reset-token)}}
        
        - ### Apply password reset {{status: draft}}
            Update password using valid reset token.
            
            - {{depends_on: [Send reset notification](auth_system.md#send-reset-notification)}}
