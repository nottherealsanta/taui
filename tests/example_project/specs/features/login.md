---
title: Login
status: active
domain: authentication
depends_on:
  - specs/domains/authentication.md
code_refs:
  - src/auth.py#L1-L30
last_updated: 2026-03-20
---

# Login

## Purpose

User login with credentials.

## User / Business Outcome

Users can authenticate to access the application.

## Scope

- Accept username and password.
- Validate credentials against the data layer.
- Return a session token on success.

## Constraints

- Invalid credentials must return an error, not a session token.
- Passwords must not be logged.

## Design

Call `login(username, password)` on the auth module. Returns a session token on success.

## Code References

- `src/auth.py#L1-L30`

## Tests / Verification

Manual testing with valid credentials.

## Open Questions

None.

## Related Decisions

No decisions recorded yet.
