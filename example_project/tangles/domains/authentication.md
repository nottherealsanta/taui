---
title: Authentication
status: active
last_updated: 2026-04-09T08:11:36
---

# Authentication

# Authentication

## Responsibility

User authentication system. Owns login and logout flows, session handling, and credential validation.

## Invariants

- A user must be authenticated before accessing task management features.
- Sessions must be invalidated on logout via `src/auth.py#revoke_session`.
- Rate limiting enforced by `src/auth.py#_check_rate_limit` (5 attempts per minute per IP).
- Sessions have a 24-hour fixed TTL, checked by `src/auth.py#Session#is_valid`.

## Interfaces

- `src/auth.py#validate_credentials` — validate username/password, returns user_id or None.
- `src/auth.py#create_session` — create a new session for a user, returns `src/auth.py#Session`.
- `src/auth.py#validate_session` — check if a session token is valid, returns user_id or None.
- `src/auth.py#revoke_session` — invalidate a session token.

## Key Components

- **AuthService** (`src/auth.py#AuthService`): Core authentication service class. Manages the simulated user database and session store.
- **Session** (`src/auth.py#Session`): Session dataclass with token, user_id, TTL, and `is_valid()` check.
- **Rate Limiter** (`src/auth.py#_check_rate_limit`): IP-based rate limiting for login attempts.
- **Password Hashing** (`src/auth.py#_hash_password`): SHA-256 password hashing.
- **API Endpoints** (`src/api.py#login`, `src/api.py#logout`, `src/api.py#get_session`): REST API layer for auth operations.

## Important Code References

- `src/auth.py#AuthService`
- `src/auth.py#Session`
- `src/auth.py#validate_credentials`
- `src/auth.py#create_session`
- `src/auth.py#validate_session`
- `src/auth.py#revoke_session`
- `src/api.py#login`
- `src/api.py#logout`

## Verification

- `tests/test_authentication.py::test_hello_world_auth` — Hello world sanity test: instantiates `AuthService`, validates credentials, creates a session, and revokes it end-to-end.
- Manual testing with valid and invalid credentials.

## Related Features

- [Login](../features/login.md)
- [Logout](../features/logout.md)

## Related Decisions

No decisions recorded yet.
