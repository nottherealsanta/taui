"""Authentication and session management."""

import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class Session:
    """User session with TTL."""

    token: str
    user_id: int
    created_at: float
    expires_at: float

    def is_valid(self) -> bool:
        return time.time() < self.expires_at


class AuthService:
    """Service for user authentication and session management."""

    # Simulated user database
    _users: dict[int, dict] = {
        1: {
            "username": "admin",
            "password_hash": hashlib.sha256("admin123".encode()).hexdigest(),
        }
    }

    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._login_attempts: dict[str, list[float]] = {}  # IP -> timestamps

    def _hash_password(self, password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    def _check_rate_limit(self, ip: str) -> bool:
        """Check if IP has exceeded rate limit (5 attempts per minute)."""
        now = time.time()
        attempts = self._login_attempts.get(ip, [])
        # Filter to last minute
        recent = [t for t in attempts if now - t < 60]
        self._login_attempts[ip] = recent
        return len(recent) < 5

    def validate_credentials(
        self, username: str, password: str, ip: str
    ) -> Optional[int]:
        """Validate user credentials.

        - behavior: Returns auth token on success, error on failure.
        - constraints: Rate limit to 5 attempts per minute.
        """
        if not self._check_rate_limit(ip):
            raise ValueError("Rate limit exceeded")

        self._login_attempts[ip] = self._login_attempts.get(ip, []) + [time.time()]

        password_hash = self._hash_password(password)

        for user_id, user in self._users.items():
            if user["username"] == username and user["password_hash"] == password_hash:
                return user_id

        return None

    def create_session(self, user_id: int) -> Session:
        """Create a new session for user.

        - behavior: 24-hour fixed TTL from creation time.
        - constraints: Maximum 10 active sessions per user.
        """
        # Check existing sessions for user
        user_sessions = [s for s in self._sessions.values() if s.user_id == user_id]
        if len(user_sessions) >= 10:
            # Remove oldest session
            oldest = min(user_sessions, key=lambda s: s.created_at)
            del self._sessions[oldest.token]

        token = secrets.token_urlsafe(32)
        now = time.time()
        session = Session(
            token=token,
            user_id=user_id,
            created_at=now,
            expires_at=now + (24 * 60 * 60),  # 24 hours
        )
        self._sessions[token] = session
        return session

    def validate_session(self, token: str) -> Optional[int]:
        """Validate session token.

        - behavior: Returns user ID if valid, None if expired/invalid.
        - constraints: Must handle timezone correctly (UTC).
        """
        if token not in self._sessions:
            return None

        session = self._sessions[token]

        if not session.is_valid():
            del self._sessions[token]
            return None

        return session.user_id

    def revoke_session(self, token: str) -> bool:
        """Revoke a session.

        - behavior: Immediate invalidation, cannot be reused.
        - constraints: Idempotent (safe to revoke non-existent session).
        """
        if token in self._sessions:
            del self._sessions[token]
            return True
        return False  # Idempotent - no error for non-existent
