- # User Management {{status: ready}}
    User registration, profiles, and account settings.
    
    - {{depends_on: [Auth System](auth_system.md)}}
    
    - ## User registration {{status: done}}
        Create new user accounts.
        
        - ### Validate registration input {{status: done}}
            Check username, email, and password validity.
            
            - {{code_ref: `tests/example_project/src/user_management.py#L1-L35`}}
            - {{verification: pytest tests/example_project/tests/test_user_management.py::test_validate_registration -q}}
        
        - ### Create user record {{status: done}}
            Persist new user to database.
            
            - {{code_ref: `tests/example_project/src/user_management.py#L37-L65`}}
            - {{verification: pytest tests/example_project/tests/test_user_management.py::test_create_user -q}}
        
        - ### Send welcome email {{status: done}}
            Deliver welcome message to new users.
            
            - {{code_ref: `tests/example_project/src/user_management.py#L67-L85`}}
            - {{verification: pytest tests/example_project/tests/test_user_management.py::test_welcome_email -q}}
    
    - ## User profiles {{status: in-progress}}
        Manage public and private profile information.
        
        - ### Update profile {{status: in-progress}}
            Modify user's display name, bio, and avatar.
            
            - {{code_ref: `tests/example_project/src/user_management.py#L87-L115`}}
        
        - ### Privacy settings {{status: draft}}
            Control visibility of profile fields.
    
    - ## Account deletion {{status: draft}}
        Allow users to delete their accounts.
        
        - ### Soft delete {{status: draft}}
            Mark account as deleted without removing data.
        
        - ### Hard delete {{status: draft}}
            Permanently remove all user data.
            
            - {{depends_on: [Soft delete](user_management.md#soft-delete)}}
    
    - ## User preferences {{status: ready}}
        User-configurable application settings.
        
        - ### Theme preference {{status: ready}}
            Light/dark mode selection.
            
            - {{code_ref: `tests/example_project/src/user_management.py#L117-L135`}}
            - {{verification: pytest tests/example_project/tests/test_user_management.py::test_theme_preference -q}}
        
        - ### Notification preferences {{status: draft}}
            Control email and push notifications.
