---
title: Authentication
status: active
domain: authentication
code_refs:
  - src/auth.py
last_updated: 2026-03-20
---

# Authentication

## Responsibility

User authentication system. Owns login and logout flows.

## Invariants

- A user must be authenticated before accessing task management features.
- Sessions must be invalidated on logout.

## Interfaces

- `login(username, password)` → session_token
- `logout(session_token)` → None

## Key Components

- **Login flow**: Validate credentials and create a session.
- **Logout flow**: Invalidate the current session.

## Important Code References

- `src/auth.py`

## Verification

Manual testing with valid and invalid credentials.

## Related Features

- [Login](../features/login.md)
- [Logout](../features/logout.md)

## Related Decisions

No decisions recorded yet.
