- ## User endpoints {{status: draft}}
    Endpoints for user management.
    
    {{depends_on: [User Management](user_management.md)}}
    
    - ### GET /users/me {{status: draft}}
        Get current user profile.
        
        - behavior: Returns authenticated user's profile.
        - constraints: Requires valid session.
    
    - ### PATCH /users/me {{status: draft}}
        Update current user profile.
        
        - behavior: Partial update of user fields.
        - constraints: Email uniqueness check, validation.
    
    - ### DELETE /users/me {{status: draft}}
        Delete current user account.
        
        - behavior: Soft-delete user and all personal data.
        - constraints: Requires password confirmation, cascades to owned boards.
    
    - ### GET /users/{id} {{status: blocked}}
        Get public profile for any user.
        
        {{question:
        What information should be public vs private?
        1) Show only username and avatar
        2) Show username, avatar, and public boards count
        3) Show full profile with privacy settings per field
        4) User can type a custom answer
        }}
        {{answer: 2) Show username, avatar, and public boards count}}
        
        - behavior: Returns public profile information.
        - constraints: Hidden if user opts out of public profiles.
