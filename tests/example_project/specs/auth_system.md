- # Auth System {{status: in-progress}}
    Handle user authentication and session management securely.
    
    - ## User login {{status: done}}
        Authenticate users with username and password.
        
        - ### Validate credentials {{status: done}}
            Check password hash against stored value.
            
            {{code_ref: `tests/example_project/src/auth.py#L1-L35`}}
            {{verification: pytest tests/example_project/tests/test_auth.py::test_login -q}}
            
            - behavior: Returns auth token on success, error on failure.
            - constraints: Rate limit to 5 attempts per minute.
    
    - ## Session management {{status: done}}
        Manage active user sessions with TTL.
        
        {{depends_on: [Validate credentials](auth_system.md#validate-credentials)}}
        
        - ### Create session {{status: done}}
            Generate session token with expiration.
            
            {{code_ref: `tests/example_project/src/auth.py#L37-L65`}}
            {{verification: pytest tests/example_project/tests/test_auth.py::test_create_session -q}}
            
            - behavior: 24-hour fixed TTL from creation time.
            - constraints: Maximum 10 active sessions per user.
        
        - ### Validate session {{status: done}}
            Check if session token is valid and not expired.
            
            {{code_ref: `tests/example_project/src/auth.py#L67-L85`}}
            {{verification: pytest tests/example_project/tests/test_auth.py::test_validate_session -q}}
            
            - behavior: Returns user ID if valid, None if expired/invalid.
            - constraints: Must handle timezone correctly (UTC).
        
        - ### Revoke session {{status: done}}
            Invalidate a session before natural expiration.
            
            {{code_ref: `tests/example_project/src/auth.py#L87-L102`}}
            {{verification: pytest tests/example_project/tests/test_auth.py::test_revoke_session -q}}
            
            - behavior: Immediate invalidation, cannot be reused.
            - constraints: Idempotent (safe to revoke non-existent session).
    
    - ## Password reset {{status: blocked}}
        Allow users to reset forgotten passwords.
        
        {{question:
        How should password reset tokens be delivered?
        1) Email only
        2) SMS only
        3) Both email and SMS (user choice)
        4) User can type a custom answer
        }}
        {{answer: 3) Both email and SMS (user choice)}}
        
        - ### Generate reset token {{status: blocked}}
            Create time-limited single-use reset token.
            
            {{question:
            What should be the token expiration time?
            1) 15 minutes
            2) 1 hour
            3) 24 hours
            4) User can type a custom answer
            }}
            {{answer: 2) 1 hour}}
            
            - behavior: Cryptographically secure random token, 1-hour TTL.
            - constraints: Single use only, invalidated after use or expiry.
        
        - ### Send reset notification {{status: draft}}
            Deliver token via user's preferred channel.
            
            {{depends_on: [Generate reset token](auth_system.md#generate-reset-token)}}
            
            - behavior: Send email or SMS based on user preference.
            - constraints: Must not leak whether email/phone exists.
        
        - ### Apply password reset {{status: draft}}
            Update password using valid reset token.
            
            {{depends_on: [Send reset notification](auth_system.md#send-reset-notification)}}
            
            - behavior: Invalidate token, update password hash, notify user.
            - constraints: New password must meet complexity requirements.
    
    - ## OAuth integration {{status: ready}}
        Support third-party authentication providers.
        
        - ### Google OAuth {{status: draft}}
            Authenticate via Google accounts.
            
            - behavior: Standard OAuth 2.0 flow with PKCE.
            - constraints: Store only Google user ID, not tokens.
        
        - ### GitHub OAuth {{status: draft}}
            Authenticate via GitHub accounts.
            
            - behavior: Standard OAuth 2.0 flow.
            - constraints: Request minimal scopes (read:user only).

    - ## Security Considerations
        Auth-related security requirements.
        
        - Password requirements:
            - Minimum 12 characters
            - Must include uppercase, lowercase, number, symbol
            - Check against common password lists
        
        - Session security:
            - HTTP-only cookies
            - Secure flag in production
            - SameSite=Strict
