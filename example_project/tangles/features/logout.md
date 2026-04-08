---
title: Logout
status: draft
last_updated: 2026-04-08T09:32:33
---

# Logout

Depends on: [Authentication](../domains/authentication.md)

## Purpose

End user session.

## User / Business Outcome

Users can securely end their session to prevent unauthorized access.

## Scope

- Invalidate the current session token.
- Return confirmation of logout.

## Constraints

- Must invalidate the session server-side via `src/auth.py#revoke_session`, not just client-side.
- Endpoint is idempotent — safe to call multiple times, per `src/api.py#logout`.
- Must verify session exists first via `src/auth.py#validate_session`.

## Design

The API endpoint `src/api.py#logout` orchestrates the flow:
1. Validates the session token via `src/auth.py#validate_session`.
2. If invalid, raises `src/api.py#APIError` with UNAUTHORIZED code.
3. If valid, calls `src/auth.py#revoke_session` to remove the session from `src/auth.py#AuthService`'s internal store.
4. Returns `src/api.py#APIResponse` with 204 status.

## Code References

- `src/api.py#logout` — REST endpoint entry point.
- `src/auth.py#revoke_session` — removes session from internal store.
- `src/auth.py#validate_session` — checks token validity before revocation.
- `src/auth.py#AuthService` — owns the session store.
- `src/api.py#APIError` — error response for invalid sessions.

## Tests / Verification

Implemented in `tests/test_authentication.py` — `TestLogout` class (6 tests):

- `test_valid_logout_returns_204` — valid token returns HTTP 204 with empty body.
- `test_logout_invalidates_session` — token is no longer valid after logout.
- `test_logout_with_invalid_token_raises_unauthorized` — unknown token raises `APIError(UNAUTHORIZED)`.
- `test_logout_after_expiry_raises_unauthorized` — expired token raises `APIError(UNAUTHORIZED)`.
- `test_logout_idempotency_second_call_raises_unauthorized` — second call raises `UNAUTHORIZED` (session already gone), not a server error.
- `test_logout_only_revokes_current_session` — only the presented token is revoked; other sessions for the same user remain valid.

All 6 tests pass (38 total in suite).

## Open Questions

- ~~Should all sessions for a user be invalidated, or only the current one?~~

**Resolved:** Only the current session (identified by the presented token) is revoked. Other active sessions for the same user remain valid. This matches the spec constraint "Endpoint is idempotent — safe to call multiple times" and the design flow which operates on a single token. Verified by `test_logout_only_revokes_current_session`.

## Related Decisions

No decisions recorded yet.
