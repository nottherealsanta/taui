---
title: Login
status: active
last_updated: 2026-03-20
---

# Login

Depends on: [Authentication](../domains/authentication.md)

## Purpose

User login with credentials.

## User / Business Outcome

Users can authenticate to access the application.

## Scope

- Accept username and password.
- Validate credentials against the simulated user database.
- Return a session token on success.
- Rate-limit login attempts per IP.

## Constraints

- Invalid credentials must return an error, not a session token — enforced in `src/api.py#login` which raises `src/api.py#APIError`.
- Passwords must not be logged.
- Rate limited to 5 attempts per minute per IP via `src/auth.py#_check_rate_limit`.
- Maximum 10 active sessions per user, enforced in `src/auth.py#create_session`.

## Design

The API endpoint `src/api.py#login` orchestrates the flow:
1. Calls `src/auth.py#validate_credentials` with username, password, and IP.
2. `validate_credentials` checks rate limit via `src/auth.py#_check_rate_limit`.
3. Hashes password with `src/auth.py#_hash_password` and checks against stored hash.
4. On success, `src/api.py#login` calls `src/auth.py#create_session` to create a `src/auth.py#Session`.
5. Returns `src/api.py#APIResponse` with token and expiry.
6. On failure, raises `src/api.py#APIError` with UNAUTHORIZED code.

## Code References

- `src/api.py#login` — REST endpoint entry point.
- `src/auth.py#validate_credentials` — credential validation with rate limiting.
- `src/auth.py#create_session` — session creation with 24h TTL.
- `src/auth.py#Session` — session data model.
- `src/auth.py#_check_rate_limit` — IP-based rate limiter.
- `src/auth.py#_hash_password` — SHA-256 password hashing.
- `src/api.py#APIResponse` — standard response wrapper.
- `src/api.py#APIError` — error with code and message.

## Tests / Verification

Manual testing with valid credentials.

## Open Questions

None.

## Related Decisions

No decisions recorded yet.
