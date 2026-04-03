---
title: Logout
status: draft
last_updated: 2026-03-20
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

Not yet implemented.

## Open Questions

- Should all sessions for a user be invalidated, or only the current one?

## Related Decisions

No decisions recorded yet.
