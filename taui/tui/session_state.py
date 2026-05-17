"""Per-session TUI state — isolates streaming, tool, and queue state per session."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from textual.containers import VerticalScroll

from taui.tui.approval_controller import ApprovalController
from taui.tui.tool_controller import ToolController

if TYPE_CHECKING:
    from taui.session import Session
    from taui.tui.widgets.agent_response import AgentResponse
    from taui.tui.widgets.reply_footer import ReplyFooter


@dataclass
class SessionState:
    """All per-session TUI state that must be isolated for parallel sessions."""

    session: Session
    session_id: str

    # Busy / processing flag for this session
    is_processing: bool = False

    # Streaming turn state
    current_response: AgentResponse | None = None
    current_reasoning: object | None = None  # Static widget
    reasoning_buf: str = ""
    _reasoning_render_pending: bool = False
    streamed_text: bool = False
    reply_footer: ReplyFooter | None = None

    # Queue for follow-up messages (Alt+Enter while busy)
    queued: list[tuple[str, list[str] | None]] = field(default_factory=list)
    pending_indicators: list[tuple[str, str]] = field(default_factory=list)

    # Per-session edit tracking for the right sidebar
    edited_files: dict[str, dict[str, int]] = field(default_factory=dict)

    # Whether the context banner has been shown for this session
    context_banner_shown: bool = False

    # Whether the config-change listener has been attached to the session
    # (kept per-state so loop swaps don't stack duplicate listeners).
    config_listener_wired: bool = False

    # Per-session chat log widget (created when session is added)
    chat_log: VerticalScroll | None = None

    # Controllers (created lazily, one per session)
    tool_ctrl: ToolController | None = None
    approval_ctrl: ApprovalController | None = None


class SessionManager:
    """Tracks multiple open sessions and their per-session TUI state."""

    def __init__(self) -> None:
        self._states: dict[str, SessionState] = {}
        self._active_id: str | None = None
        self._order: list[str] = []  # insertion order for tab display

    @property
    def active_id(self) -> str | None:
        return self._active_id

    @active_id.setter
    def active_id(self, value: str | None) -> None:
        self._active_id = value

    @property
    def active(self) -> SessionState | None:
        if self._active_id is None:
            return None
        return self._states.get(self._active_id)

    @property
    def all_states(self) -> dict[str, SessionState]:
        return self._states

    @property
    def order(self) -> list[str]:
        return self._order

    @property
    def any_processing(self) -> bool:
        return any(s.is_processing for s in self._states.values())

    def add(self, state: SessionState) -> None:
        self._states[state.session_id] = state
        if state.session_id not in self._order:
            self._order.append(state.session_id)

    def remove(self, session_id: str) -> SessionState | None:
        state = self._states.pop(session_id, None)
        if session_id in self._order:
            self._order.remove(session_id)
        if self._active_id == session_id:
            self._active_id = self._order[0] if self._order else None
        return state

    def get(self, session_id: str) -> SessionState | None:
        return self._states.get(session_id)

    def __len__(self) -> int:
        return len(self._states)

    def __contains__(self, session_id: str) -> bool:
        return session_id in self._states
