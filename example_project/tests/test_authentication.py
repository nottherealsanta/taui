"""Tests for the authentication domain — login, logout, session management."""

from __future__ import annotations

import time

import pytest

from example_project.src.api import APIError, APIResponse, APIService
from example_project.src.auth import AuthService, Session


# ---------------------------------------------------------------------------
# AuthService unit tests
# ---------------------------------------------------------------------------


class TestSessionIsValid:
    """Session.is_valid() reflects TTL correctly."""

    def test_fresh_session_is_valid(self) -> None:
        now = time.time()
        session = Session(
            token="tok", user_id=1, created_at=now, expires_at=now + 3600
        )
        assert session.is_valid() is True

    def test_expired_session_is_invalid(self) -> None:
        now = time.time()
        session = Session(
            token="tok", user_id=1, created_at=now - 100, expires_at=now - 1
        )
        assert session.is_valid() is False

    def test_session_expiry_is_24h(self) -> None:
        """create_session should set a 24-hour TTL."""
        svc = AuthService()
        session = svc.create_session(user_id=1)
        expected_ttl = 24 * 60 * 60
        actual_ttl = session.expires_at - session.created_at
        # Allow 1-second tolerance for test execution time
        assert abs(actual_ttl - expected_ttl) < 1


class TestHashPassword:
    """_hash_password is consistent and non-reversible."""

    def test_same_password_gives_same_hash(self) -> None:
        svc = AuthService()
        assert svc._hash_password("secret") == svc._hash_password("secret")

    def test_different_passwords_give_different_hashes(self) -> None:
        svc = AuthService()
        assert svc._hash_password("a") != svc._hash_password("b")


class TestRateLimit:
    """_check_rate_limit enforces 5 attempts per minute per IP."""

    def test_allows_up_to_five_attempts(self) -> None:
        svc = AuthService()
        ip = "1.2.3.4"
        for _ in range(5):
            assert svc._check_rate_limit(ip) is True
            svc._login_attempts[ip] = svc._login_attempts.get(ip, []) + [time.time()]

    def test_blocks_sixth_attempt(self) -> None:
        svc = AuthService()
        ip = "5.6.7.8"
        now = time.time()
        svc._login_attempts[ip] = [now] * 5
        assert svc._check_rate_limit(ip) is False

    def test_old_attempts_are_not_counted(self) -> None:
        """Attempts older than 60 s must be pruned."""
        svc = AuthService()
        ip = "9.10.11.12"
        old = time.time() - 61  # more than 1 minute ago
        svc._login_attempts[ip] = [old] * 10  # lots of old attempts
        assert svc._check_rate_limit(ip) is True


class TestValidateCredentials:
    """validate_credentials checks user DB and enforces rate limiting."""

    def test_valid_credentials_return_user_id(self) -> None:
        svc = AuthService()
        uid = svc.validate_credentials("admin", "admin123", "127.0.0.1")
        assert uid == 1

    def test_wrong_password_returns_none(self) -> None:
        svc = AuthService()
        uid = svc.validate_credentials("admin", "wrong", "127.0.0.1")
        assert uid is None

    def test_unknown_username_returns_none(self) -> None:
        svc = AuthService()
        uid = svc.validate_credentials("ghost", "admin123", "127.0.0.1")
        assert uid is None

    def test_rate_limit_raises_after_five_failed_attempts(self) -> None:
        svc = AuthService()
        ip = "10.0.0.1"
        for _ in range(5):
            svc.validate_credentials("admin", "bad", ip)

        with pytest.raises(ValueError, match="Rate limit exceeded"):
            svc.validate_credentials("admin", "admin123", ip)


class TestCreateSession:
    """create_session enforces max-10 and 24-h TTL."""

    def test_returns_session_with_token(self) -> None:
        svc = AuthService()
        session = svc.create_session(1)
        assert isinstance(session, Session)
        assert session.token
        assert session.user_id == 1

    def test_session_stored_internally(self) -> None:
        svc = AuthService()
        session = svc.create_session(1)
        assert session.token in svc._sessions

    def test_max_ten_sessions_per_user(self) -> None:
        """The 11th session creation must evict the oldest, not raise."""
        svc = AuthService()
        tokens = []
        for _ in range(10):
            s = svc.create_session(1)
            tokens.append(s.token)

        user_sessions_before = [s for s in svc._sessions.values() if s.user_id == 1]
        assert len(user_sessions_before) == 10

        new_session = svc.create_session(1)
        user_sessions_after = [s for s in svc._sessions.values() if s.user_id == 1]
        assert len(user_sessions_after) == 10
        assert tokens[0] not in svc._sessions
        assert new_session.token in svc._sessions

    def test_different_users_sessions_are_independent(self) -> None:
        """Max-10 limit applies per user, not globally."""
        svc = AuthService()
        for _ in range(10):
            svc.create_session(1)
        # User 2 should still be able to get sessions
        session = svc.create_session(2)
        assert session.token in svc._sessions


class TestValidateSession:
    """validate_session returns user_id for valid tokens, None otherwise."""

    def test_valid_token_returns_user_id(self) -> None:
        svc = AuthService()
        session = svc.create_session(1)
        assert svc.validate_session(session.token) == 1

    def test_unknown_token_returns_none(self) -> None:
        svc = AuthService()
        assert svc.validate_session("nonexistent-token") is None

    def test_expired_session_returns_none_and_is_removed(self) -> None:
        svc = AuthService()
        session = svc.create_session(1)
        # Artificially expire the session
        session.expires_at = time.time() - 1
        result = svc.validate_session(session.token)
        assert result is None
        assert session.token not in svc._sessions


class TestRevokeSession:
    """revoke_session removes session; is idempotent."""

    def test_revoke_existing_session(self) -> None:
        svc = AuthService()
        session = svc.create_session(1)
        result = svc.revoke_session(session.token)
        assert result is True
        assert session.token not in svc._sessions

    def test_revoke_nonexistent_token_is_idempotent(self) -> None:
        """Revoking a non-existent token must not raise."""
        svc = AuthService()
        result = svc.revoke_session("does-not-exist")
        assert result is False

    def test_revoke_twice_is_safe(self) -> None:
        svc = AuthService()
        session = svc.create_session(1)
        svc.revoke_session(session.token)
        result = svc.revoke_session(session.token)
        assert result is False


# ---------------------------------------------------------------------------
# APIService integration tests (login / logout / get_session)
# ---------------------------------------------------------------------------


class TestLogin:
    """POST /auth/login — full flow via APIService."""

    def test_valid_login_returns_token_and_expiry(self) -> None:
        api = APIService()
        response = api.login("admin", "admin123", "127.0.0.1")
        assert isinstance(response, APIResponse)
        assert response.status_code == 200
        assert "token" in response.data
        assert "expires_at" in response.data

    def test_invalid_password_raises_unauthorized(self) -> None:
        api = APIService()
        with pytest.raises(APIError) as exc_info:
            api.login("admin", "wrong_password", "127.0.0.1")
        assert exc_info.value.code == "UNAUTHORIZED"

    def test_unknown_user_raises_unauthorized(self) -> None:
        api = APIService()
        with pytest.raises(APIError) as exc_info:
            api.login("nobody", "admin123", "127.0.0.1")
        assert exc_info.value.code == "UNAUTHORIZED"

    def test_rate_limit_blocks_after_five_attempts(self) -> None:
        """6th failed login from the same IP must raise rate-limit error."""
        api = APIService()
        ip = "192.168.1.1"
        for _ in range(5):
            with pytest.raises(APIError):
                api.login("admin", "bad", ip)

        with pytest.raises(ValueError, match="Rate limit exceeded"):
            api.login("admin", "admin123", ip)

    def test_token_is_valid_session_after_login(self) -> None:
        """Token returned by login must be a valid session."""
        api = APIService()
        response = api.login("admin", "admin123", "127.0.0.1")
        token = response.data["token"]
        assert api.auth.validate_session(token) == 1


class TestLogout:
    """POST /auth/logout — full flow via APIService."""

    def test_valid_logout_returns_204(self) -> None:
        api = APIService()
        login_response = api.login("admin", "admin123", "127.0.0.1")
        token = login_response.data["token"]

        logout_response = api.logout(token)
        assert logout_response.status_code == 204
        assert logout_response.data == {}

    def test_logout_invalidates_session(self) -> None:
        """After logout, the token must no longer be valid."""
        api = APIService()
        login_response = api.login("admin", "admin123", "127.0.0.1")
        token = login_response.data["token"]

        api.logout(token)
        assert api.auth.validate_session(token) is None

    def test_logout_with_invalid_token_raises_unauthorized(self) -> None:
        """Logout with an invalid/unknown token must raise UNAUTHORIZED."""
        api = APIService()
        with pytest.raises(APIError) as exc_info:
            api.logout("invalid-token-xyz")
        assert exc_info.value.code == "UNAUTHORIZED"

    def test_logout_after_expiry_raises_unauthorized(self) -> None:
        """Logout with an already-expired session token must raise UNAUTHORIZED."""
        api = APIService()
        login_response = api.login("admin", "admin123", "127.0.0.1")
        token = login_response.data["token"]

        # Artificially expire the session
        api.auth._sessions[token].expires_at = time.time() - 1

        with pytest.raises(APIError) as exc_info:
            api.logout(token)
        assert exc_info.value.code == "UNAUTHORIZED"

    def test_logout_idempotency_second_call_raises_unauthorized(self) -> None:
        """Second logout raises UNAUTHORIZED (session already gone).

        The spec design mandates validate_session first, so UNAUTHORIZED is the
        correct response when the token is no longer present — not a 500.
        """
        api = APIService()
        login_response = api.login("admin", "admin123", "127.0.0.1")
        token = login_response.data["token"]

        api.logout(token)  # first call — success

        with pytest.raises(APIError) as exc_info:
            api.logout(token)
        assert exc_info.value.code == "UNAUTHORIZED"

    def test_logout_only_revokes_current_session(self) -> None:
        """Logout must revoke only the presented token, not all user sessions."""
        api = APIService()
        r1 = api.login("admin", "admin123", "1.1.1.1")
        r2 = api.login("admin", "admin123", "2.2.2.2")
        token1 = r1.data["token"]
        token2 = r2.data["token"]

        api.logout(token1)

        assert api.auth.validate_session(token1) is None
        assert api.auth.validate_session(token2) == 1


class TestGetSession:
    """GET /auth/session — verifies session validity."""

    def test_valid_session_returns_user_id(self) -> None:
        api = APIService()
        login_response = api.login("admin", "admin123", "127.0.0.1")
        token = login_response.data["token"]

        resp = api.get_session(token)
        assert resp.status_code == 200
        assert resp.data["user_id"] == 1

    def test_invalid_session_raises_unauthorized(self) -> None:
        api = APIService()
        with pytest.raises(APIError) as exc_info:
            api.get_session("bad-token")
        assert exc_info.value.code == "UNAUTHORIZED"

    def test_expired_session_raises_unauthorized(self) -> None:
        api = APIService()
        login_response = api.login("admin", "admin123", "127.0.0.1")
        token = login_response.data["token"]
        api.auth._sessions[token].expires_at = time.time() - 1

        with pytest.raises(APIError) as exc_info:
            api.get_session(token)
        assert exc_info.value.code == "UNAUTHORIZED"
