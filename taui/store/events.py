"""Event types and the Event record for the Store."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """Types of events that can appear in a stream.

    Every row in the events table carries one of these types so that
    consumers (Context Manager, frontends, diagnostics) can filter
    and route without parsing the JSON payload.
    """

    # Agent lifecycle
    STREAM_START = "stream_start"
    STREAM_END = "stream_end"
    STATE_CHANGE = "state_change"

    # Messages
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    SYSTEM_MESSAGE = "system_message"

    # Tool cycle
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"

    # Streaming tokens
    TOKEN = "token"

    # User interaction
    QUESTION = "question"
    ANSWER = "answer"

    # Tracking
    USAGE = "usage"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Event:
    """A single event read from a stream."""

    stream_id: str
    offset: int
    type: EventType
    data: dict[str, Any]
    created_at: float
