from __future__ import annotations

import json
from typing import Any

from .agent_db import AgentHistoryDB


class ProjectHistoryStore:
    """History facade backed by the project-local AgentHistoryDB.

    Provides the interface expected by PrimeAgent and AgentManager while
    delegating all storage to the on-disk, WAL-mode AgentHistoryDB.
    """

    def __init__(self, db: AgentHistoryDB) -> None:
        self._db = db

    async def connect(self) -> None:
        return

    async def close(self) -> None:
        return

    async def record_session(
        self,
        *,
        agent_id: str,
        workspace: str | None,
        spec_ref: str,
        task: str,
        display_name: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        agent_type: str = "root",
    ) -> None:
        existing = await self._db.get_agent_session(agent_id)
        if existing is not None:
            return
        await self._db.create_agent_session(
            agent_id=agent_id,
            session_id=agent_id,
            spec_ref=spec_ref,
            task=task,
            tier="medium",
            agent_type=agent_type,
            display_name=display_name,
            model=model,
            provider=provider,
            parent_agent_id=None,
        )

    async def record_message(
        self,
        *,
        agent_id: str,
        role: str,
        content: str | None,
        tool_call_id: str | None = None,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        await self._ensure_session(agent_id)
        metadata_json = json.dumps(metadata) if isinstance(metadata, dict) else None
        message_id = await self._db.record_agent_message(
            agent_id=agent_id,
            role=role,
            content=content,
            tool_call_id=tool_call_id,
            name=name,
            metadata=metadata_json,
        )
        if metadata and tool_call_id and name:
            await self._db.record_agent_tool_call(
                call_id=tool_call_id,
                agent_id=agent_id,
                message_id=message_id,
                tool_name=name,
                arguments=json.dumps(metadata.get("arguments", {})),
            )
        return message_id

    async def list_sessions(
        self,
        *,
        workspace: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        rows = await self._db.list_agent_sessions()
        if workspace is not None:
            rows = [r for r in rows if (r.get("workspace") == workspace)]
        return rows[:limit]

    async def get_messages(
        self, agent_id: str, *, limit: int = 500
    ) -> list[dict[str, Any]]:
        return await self._db._all(
            "SELECT id, agent_id, role, content, tool_call_id, name, metadata, seq, created_at FROM agent_messages WHERE agent_id = ? ORDER BY seq LIMIT ?",
            (agent_id, limit),
        )

    async def get_messages_page(
        self,
        agent_id: str,
        *,
        before_seq: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if before_seq is None:
            rows = await self._db._all(
                "SELECT id, agent_id, role, content, tool_call_id, name, metadata, seq, created_at FROM agent_messages WHERE agent_id = ? ORDER BY seq DESC LIMIT ?",
                (agent_id, limit),
            )
        else:
            rows = await self._db._all(
                "SELECT id, agent_id, role, content, tool_call_id, name, metadata, seq, created_at FROM agent_messages WHERE agent_id = ? AND seq < ? ORDER BY seq DESC LIMIT ?",
                (agent_id, before_seq, limit),
            )
        return list(reversed(rows))

    async def _ensure_session(self, agent_id: str) -> None:
        existing = await self._db.get_agent_session(agent_id)
        if existing is not None:
            return
        now_ref = "prime" if agent_id == "prime" else "tangles/index.md#index"
        now_task = "Prime assistant" if agent_id == "prime" else "Session"
        await self._db.create_agent_session(
            agent_id=agent_id,
            session_id=agent_id,
            spec_ref=now_ref,
            task=now_task,
            tier="medium",
            agent_type="prime" if agent_id == "prime" else "root",
            display_name="Prime" if agent_id == "prime" else None,
            model=None,
            provider=None,
            parent_agent_id=None,
        )
