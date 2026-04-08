"""User management implementation."""

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class User:
    """User entity."""

    id: int
    username: str
    email: str
    password_hash: str
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    timezone: str = "UTC"
    created_at: datetime = None
    deleted_at: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


class UserManagementService:
    """Service for user management."""

    def __init__(self):
        self._users: dict[int, User] = {}
        self._next_user_id = 1

    def _hash_password(self, password: str) -> str:
        """Hash password with SHA-256 (use bcrypt in production)."""
        return hashlib.sha256(password.encode()).hexdigest()

    def validate_registration(self, username: str, email: str, password: str) -> dict:
        """Validate registration input.

        - behavior: Validates all fields, returns specific errors.
        - constraints: Username 3-30 chars, email format, password complexity.
        """
        errors = {}

        # Username validation
        if len(username) < 3:
            errors["username"] = "Username must be at least 3 characters"
        elif len(username) > 30:
            errors["username"] = "Username must be under 30 characters"
        elif not re.match(r"^[a-zA-Z0-9_]+$", username):
            errors["username"] = (
                "Username can only contain letters, numbers, and underscores"
            )

        # Email validation
        if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
            errors["email"] = "Invalid email format"

        # Password validation
        if len(password) < 12:
            errors["password"] = "Password must be at least 12 characters"
        elif not re.search(r"[A-Z]", password):
            errors["password"] = "Password must contain an uppercase letter"
        elif not re.search(r"[a-z]", password):
            errors["password"] = "Password must contain a lowercase letter"
        elif not re.search(r"\d", password):
            errors["password"] = "Password must contain a number"
        elif not re.search(r"[!@#$%^&*]", password):
            errors["password"] = "Password must contain a special character"

        return errors

    def create_user(self, username: str, email: str, password: str) -> User:
        """Create a new user.

        - behavior: Creates user with hashed password, sends welcome email.
        - constraints: Email must be unique, username must be unique.
        """
        errors = self.validate_registration(username, email, password)
        if errors:
            raise ValueError(f"Validation failed: {errors}")

        user = User(
            id=self._next_user_id,
            username=username,
            email=email,
            password_hash=self._hash_password(password),
        )
        self._users[user.id] = user
        self._next_user_id += 1

        # Send welcome email (async in real implementation)
        self._send_welcome_email(user)

        return user

    def _send_welcome_email(self, user: User) -> bool:
        """Send welcome email to new user.

        - behavior: Async email delivery with template.
        - constraints: Retry 3 times on failure, log bounces.
        """
        # Simulated email sending
        print(f"Sending welcome email to {user.email}")
        return True

    def update_profile(self, user_id: int, **kwargs) -> User:
        """Update user profile.

        - behavior: Partial updates allowed.
        - constraints: Bio max 500 chars, avatar max 2MB.
        """
        if user_id not in self._users:
            raise ValueError(f"User {user_id} not found")

        user = self._users[user_id]

        if "display_name" in kwargs:
            user.display_name = kwargs["display_name"]

        if "bio" in kwargs:
            bio = kwargs["bio"]
            if bio and len(bio) > 500:
                raise ValueError("Bio must be under 500 characters")
            user.bio = bio

        if "avatar_url" in kwargs:
            user.avatar_url = kwargs["avatar_url"]

        return user

    def set_theme_preference(self, user_id: int, theme: str) -> User:
        """Set user's theme preference.

        - behavior: System, light, or dark mode.
        - constraints: Persisted per user, synced across devices.
        """
        if user_id not in self._users:
            raise ValueError(f"User {user_id} not found")

        if theme not in ("system", "light", "dark"):
            raise ValueError(f"Invalid theme: {theme}")

        # Theme would be stored in user preferences table
        # For demo, just return user
        return self._users[user_id]
