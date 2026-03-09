"""API endpoint implementations."""

from dataclasses import dataclass
from typing import Optional

from .auth import AuthService
from .task_board import TaskBoardService


@dataclass
class APIResponse:
    """Standard API response."""

    status_code: int
    data: dict


class APIError(Exception):
    """API error with code and message."""

    def __init__(self, code: str, message: str, details: dict = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class APIService:
    """REST API service."""

    def __init__(self):
        self.auth = AuthService()
        self.task_board = TaskBoardService()

    def login(self, username: str, password: str, ip: str) -> APIResponse:
        """POST /auth/login - Authenticate and receive session token.

        - behavior: Returns 200 with token on success, 401 on failure.
        - constraints: Rate limited.
        """
        user_id = self.auth.validate_credentials(username, password, ip)

        if user_id is None:
            raise APIError("UNAUTHORIZED", "Invalid credentials")

        session = self.auth.create_session(user_id)

        return APIResponse(
            200, {"token": session.token, "expires_at": session.expires_at}
        )

    def logout(self, token: str) -> APIResponse:
        """POST /auth/logout - Invalidate current session.

        - behavior: Returns 204 on success, 401 if not authenticated.
        - constraints: Idempotent (safe to call multiple times).
        """
        if not self.auth.validate_session(token):
            raise APIError("UNAUTHORIZED", "Invalid session")

        self.auth.revoke_session(token)

        return APIResponse(204, {})

    def get_session(self, token: str) -> APIResponse:
        """GET /auth/session - Verify session validity.

        - behavior: Returns 200 with user info if valid, 401 if invalid.
        - constraints: Must check session expiration.
        """
        user_id = self.auth.validate_session(token)

        if user_id is None:
            raise APIError("UNAUTHORIZED", "Invalid or expired session")

        return APIResponse(200, {"user_id": user_id})

    def list_boards(
        self, user_id: int, page: int = 1, per_page: int = 20
    ) -> APIResponse:
        """GET /boards - List all boards for authenticated user.

        - behavior: Returns paginated list of boards.
        - constraints: Only show boards user has access to.
        """
        # Simulated board list
        boards = [{"id": 1, "title": "My Board", "owner_id": user_id}]

        return APIResponse(
            200,
            {
                "boards": boards,
                "page": page,
                "per_page": per_page,
                "total": len(boards),
            },
        )

    def create_board(self, user_id: int, title: str) -> APIResponse:
        """POST /boards - Create a new board.

        - behavior: Returns 201 with new board ID.
        - constraints: Title required, max 100 chars.
        """
        if not title:
            raise APIError("VALIDATION_ERROR", "Title is required")

        if len(title) > 100:
            raise APIError("VALIDATION_ERROR", "Title must be under 100 characters")

        board_id = 1  # Simulated

        return APIResponse(201, {"id": board_id, "title": title})
