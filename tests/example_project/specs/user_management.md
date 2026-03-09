- # User Management {{status: ready}}
    User registration, profiles, and account settings.
    
    {{depends_on: [Auth System](auth_system.md)}}
    
    - ## User registration {{status: done}}
        Create new user accounts.
        
        - ### Validate registration input {{status: done}}
            Check username, email, and password validity.
            
            {{code_ref: `tests/example_project/src/user_management.py#L1-L35`}}
            {{verification: pytest tests/example_project/tests/test_user_management.py::test_validate_registration -q}}
            
            - behavior: Validates all fields, returns specific errors.
            - constraints: Username 3-30 chars, email format, password complexity.
        
        - ### Create user record {{status: done}}
            Persist new user to database.
            
            {{code_ref: `tests/example_project/src/user_management.py#L37-L65`}}
            {{verification: pytest tests/example_project/tests/test_user_management.py::test_create_user -q}}
            
            - behavior: Creates user with hashed password, sends welcome email.
            - constraints: Email must be unique, username must be unique.
        
        - ### Send welcome email {{status: done}}
            Deliver welcome message to new users.
            
            {{code_ref: `tests/example_project/src/user_management.py#L67-L85`}}
            {{verification: pytest tests/example_project/tests/test_user_management.py::test_welcome_email -q}}
            
            - behavior: Async email delivery with template.
            - constraints: Retry 3 times on failure, log bounces.
    
    - ## User profiles {{status: in-progress}}
        Manage public and private profile information.
        
        - ### Update profile {{status: in-progress}}
            Modify user's display name, bio, and avatar.
            
            {{code_ref: `tests/example_project/src/user_management.py#L87-L115`}}
            
            - behavior: Partial updates allowed.
            - constraints: Bio max 500 chars, avatar max 2MB.
        
        - ### Privacy settings {{status: draft}}
            Control visibility of profile fields.
            
            - behavior: Toggle public/private for email, activity, boards.
            - constraints: Username always public.
    
    - ## Account deletion {{status: draft}}
        Allow users to delete their accounts.
        
        - ### Soft delete {{status: draft}}
            Mark account as deleted without removing data.
            
            - behavior: Sets deleted_at, anonymizes PII, keeps public content.
            - constraints: 30-day grace period for recovery.
        
        - ### Hard delete {{status: draft}}
            Permanently remove all user data.
            
            {{depends_on: [Soft delete](user_management.md#soft-delete)}}
            
            - behavior: Runs after grace period, cascades to all data.
            - constraints: GDPR-compliant, audit log retained.
    
    - ## User preferences {{status: ready}}
        User-configurable application settings.
        
        - ### Theme preference {{status: ready}}
            Light/dark mode selection.
            
            {{code_ref: `tests/example_project/src/user_management.py#L117-L135`}}
            {{verification: pytest tests/example_project/tests/test_user_management.py::test_theme_preference -q}}
            
            - behavior: System, light, or dark mode.
            - constraints: Persisted per user, synced across devices.
        
        - ### Notification preferences {{status: draft}}
            Control email and push notifications.
            
            - behavior: Granular control per notification type.
            - constraints: Critical notifications cannot be disabled.

    - ## Profile Fields
        Available user profile fields.
        
        | Field | Type | Editable | Public |
        |-------|------|----------|--------|
        | username | string | No | Yes |
        | email | string | Yes | Configurable |
        | display_name | string | Yes | Yes |
        | bio | string | Yes | Yes |
        | avatar_url | string | Yes | Yes |
        | timezone | string | Yes | No |
        | created_at | datetime | No | Yes |
