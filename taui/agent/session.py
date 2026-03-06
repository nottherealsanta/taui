from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json
from uuid import uuid4

from taui.llm.types import Message, Usage


@dataclass(slots=True)
class SessionUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


@dataclass(slots=True)
class Session:
    session_id: str = field(default_factory=lambda: uuid4().hex)
    messages: list[Message] = field(default_factory=list)
    usage: SessionUsage = field(default_factory=SessionUsage)
    created_at: str = field(default_factory=lambda: _utc_now())
    updated_at: str = field(default_factory=lambda: _utc_now())
    _read_attempts: dict[str, str] = field(default_factory=dict)

    def add_message(self, message: Message) -> None:
        self.messages.append(message)
        self.updated_at = _utc_now()

    def mark_read(self, path: Path, status: str) -> None:
        self._read_attempts[str(path.resolve())] = status
        self.updated_at = _utc_now()

    def record_usage(self, usage: Usage | None) -> None:
        if usage is None:
            return
        self.usage.input_tokens += usage.input_tokens
        self.usage.output_tokens += usage.output_tokens
        self.updated_at = _utc_now()

    def estimated_input_tokens(self) -> int:
        return sum(_estimate_message_tokens(message) for message in self.messages)

    def compact_for_token_budget(
        self,
        max_input_tokens: int,
        reserved_output_tokens: int = 512,
        soft_ratio: float = 0.85,
        hard_ratio: float = 0.95,
    ) -> bool:
        if max_input_tokens <= 0:
            raise ValueError("max_input_tokens must be positive")
        if reserved_output_tokens < 0:
            raise ValueError("reserved_output_tokens must be non-negative")
        available = max_input_tokens - reserved_output_tokens
        if available <= 0:
            raise ValueError("reserved_output_tokens leaves no room for input context")

        soft_limit = max(1, int(available * soft_ratio))
        hard_limit = max(1, int(available * hard_ratio))
        compacted = False
        removed_count = 0

        preserve = _preserved_indexes(self.messages)
        while self.estimated_input_tokens() > soft_limit:
            index = _oldest_droppable_index(self.messages, preserve)
            if index is None:
                break
            del self.messages[index]
            preserve = _preserved_indexes(self.messages)
            compacted = True
            removed_count += 1

        if self.estimated_input_tokens() > hard_limit:
            while self.estimated_input_tokens() > hard_limit:
                index = _oldest_droppable_index(self.messages, preserve)
                if index is None:
                    break
                del self.messages[index]
                preserve = _preserved_indexes(self.messages)
                compacted = True
                removed_count += 1

        if removed_count > 0 and not _has_budget_summary(self.messages):
            summary = Message(
                role="system",
                content=(
                    "Conversation summary: older context trimmed for token budget "
                    f"(messages_removed={removed_count})."
                ),
            )
            insert_at = 1 if self.messages and self.messages[0].role == "system" else 0
            self.messages.insert(insert_at, summary)
            compacted = True

        if self.estimated_input_tokens() > available:
            raise ValueError(
                "Token budget exceeded even after compaction. Reduce prompt size or increase max_input_tokens."
            )

        if compacted:
            self.updated_at = _utc_now()
        return compacted

    def has_read(self, path: Path) -> bool:
        status = self._read_attempts.get(str(path.resolve()))
        return status in {"success", "missing"}

    def read_status(self, path: Path) -> str | None:
        return self._read_attempts.get(str(path.resolve()))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "session_id": self.session_id,
            "messages": [message.to_dict() for message in self.messages],
            "read_attempts": dict(sorted(self._read_attempts.items())),
            "usage": self.usage.to_dict(),
            "timestamps": {
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "Session":
        raw_messages_obj = payload.get("messages", [])
        raw_messages = raw_messages_obj if isinstance(raw_messages_obj, list) else []
        messages = [
            Message.from_dict(item) for item in raw_messages if isinstance(item, dict)
        ]
        read_attempts_raw = payload.get("read_attempts", {})
        read_attempts = {}
        if isinstance(read_attempts_raw, dict):
            for key, value in read_attempts_raw.items():
                if isinstance(key, str) and isinstance(value, str):
                    read_attempts[key] = value
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            session_id = uuid4().hex
        usage_raw = payload.get("usage", {})
        usage = SessionUsage()
        if isinstance(usage_raw, dict):
            in_tokens = usage_raw.get("input_tokens")
            out_tokens = usage_raw.get("output_tokens")
            if isinstance(in_tokens, int) and in_tokens >= 0:
                usage.input_tokens = in_tokens
            if isinstance(out_tokens, int) and out_tokens >= 0:
                usage.output_tokens = out_tokens
        timestamps_raw = payload.get("timestamps", {})
        created_at = _utc_now()
        updated_at = created_at
        if isinstance(timestamps_raw, dict):
            created = timestamps_raw.get("created_at")
            updated = timestamps_raw.get("updated_at")
            if isinstance(created, str) and created:
                created_at = created
            if isinstance(updated, str) and updated:
                updated_at = updated
        return cls(
            session_id=session_id,
            messages=messages,
            usage=usage,
            created_at=created_at,
            updated_at=updated_at,
            _read_attempts=read_attempts,
        )


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _has_budget_summary(messages: list[Message]) -> bool:
    for message in messages:
        if message.role != "system" or not message.content:
            continue
        if message.content.startswith("Conversation summary:"):
            return True
    return False


def _estimate_message_tokens(message: Message) -> int:
    total_chars = len(message.role)
    if message.content:
        total_chars += len(message.content)
    if message.tool_calls:
        for call in message.tool_calls:
            total_chars += len(call.name) + len(call.id)
            total_chars += len(json.dumps(call.arguments, sort_keys=True))
    if message.tool_call_id:
        total_chars += len(message.tool_call_id)
    if message.name:
        total_chars += len(message.name)
    return max(1, (total_chars // 4) + 1)


def _preserved_indexes(messages: list[Message]) -> set[int]:
    preserve: set[int] = set()
    latest_system = _latest_index(messages, "system")
    latest_user = _latest_index(messages, "user")
    if latest_system is not None:
        preserve.add(latest_system)
    if latest_user is not None:
        preserve.add(latest_user)

    unresolved_calls = _unresolved_tool_call_ids(messages)
    if not unresolved_calls:
        return preserve

    for index, message in enumerate(messages):
        if message.tool_calls:
            for call in message.tool_calls:
                if call.id in unresolved_calls:
                    preserve.add(index)
        if message.role == "tool" and message.tool_call_id in unresolved_calls:
            preserve.add(index)
    return preserve


def _latest_index(messages: list[Message], role: str) -> int | None:
    for idx in range(len(messages) - 1, -1, -1):
        if messages[idx].role == role:
            return idx
    return None


def _unresolved_tool_call_ids(messages: list[Message]) -> set[str]:
    requested: set[str] = set()
    resolved: set[str] = set()
    for message in messages:
        if message.tool_calls:
            for call in message.tool_calls:
                requested.add(call.id)
        if message.role == "tool" and message.tool_call_id:
            resolved.add(message.tool_call_id)
    return {tool_id for tool_id in requested if tool_id not in resolved}


def _oldest_droppable_index(messages: list[Message], preserve: set[int]) -> int | None:
    for idx in range(len(messages)):
        if idx not in preserve:
            return idx
    return None
