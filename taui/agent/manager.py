"""
AgentManager — central coordinator for all agent sessions.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable
from uuid import uuid4

from taui.agent.runner import AgentEvent, AgentRunner, AgentState
from taui.specs.db import SpecDB

logger = logging.getLogger(__name__)

NotificationCallback = Callable[[dict[str, Any]], None]

# States considered "non-terminal" — these are interrupted by a restart
_INTERRUPTED_STATES = {"idle", "running", "thinking", "tool_execution", "stopping"}


class AgentManager:
    """
    Manages root agents and their sub-agents.

    Responsibilities:
    - Launch / stop agents
    - Buffer agent events (for Phase 3 subscriptions)
    - Forward events as notifications over the WebSocket
    """

    def __init__(self, db: SpecDB) -> None:
        self.db = db
        self._runners: dict[str, AgentRunner] = {}  # agent_id → runner
        self._event_buffers: dict[str, list[AgentEvent]] = {}  # agent_id → events
        self._subscriptions: set[str] = (
            set()
        )  # agent_ids with active detail subscribers
        self._notification_callback: NotificationCallback | None = None

    def set_notification_callback(self, callback: NotificationCallback | None) -> None:
        self._notification_callback = callback

    # ── Launch ─────────────────────────────────────────────────────────────────

    async def launch(
        self,
        *,
        spec_ref: str,
        task: str,
        tier: str = "medium",
        llm: Any,  # BaseLLMClient
        model: str,
        tool_registry: Any,  # ToolRegistry
        spec_service: Any | None = None,  # SpecService — for spec-tree tools
        parent_agent_id: str | None = None,
    ) -> AgentRunner:
        agent_id = str(uuid4())
        session_id = str(uuid4())

        await self.db.create_agent_session(
            agent_id=agent_id,
            session_id=session_id,
            spec_ref=spec_ref,
            task=task,
            tier=tier,
            model=model,
            parent_agent_id=parent_agent_id,
        )

        self._event_buffers[agent_id] = []

        runner = AgentRunner(
            agent_id=agent_id,
            session_id=session_id,
            spec_ref=spec_ref,
            task=task,
            tier=tier,
            llm=llm,
            model=model,
            db=self.db,
            tool_registry=tool_registry,
            spec_service=spec_service,
            event_callback=self._on_agent_event,
            parent_agent_id=parent_agent_id,
        )

        self._runners[agent_id] = runner
        runner.start()

        logger.info(
            "AgentManager launched agent_id=%s spec_ref=%s tier=%s",
            agent_id,
            spec_ref,
            tier,
        )
        return runner

    # ── Stop ───────────────────────────────────────────────────────────────────

    async def stop(self, agent_id: str) -> None:
        runner = self._runners.get(agent_id)
        if runner is None:
            raise ValueError(f"No active agent with id={agent_id!r}")
        await runner.stop_safely()
        self._runners.pop(agent_id, None)
        logger.info("AgentManager stopped agent_id=%s", agent_id)

    # ── Steer ──────────────────────────────────────────────────────────────────

    async def steer(self, agent_id: str, message: str) -> None:
        """Inject a steer message into the runner's steer queue."""
        runner = self._runners.get(agent_id)
        if runner is None:
            raise ValueError(f"No active agent with id={agent_id!r}")
        await runner.steer(message)

    # ── Queue ──────────────────────────────────────────────────────────────────

    async def queue(self, agent_id: str, message: str) -> None:
        """Enqueue a follow-up task for the agent to pick up after the current task."""
        # Verify the agent exists (active or historical)
        session = await self.db.get_agent_session(agent_id)
        if session is None:
            raise ValueError(f"No agent session with id={agent_id!r}")
        await self.db.enqueue_agent_task(agent_id=agent_id, message=message)

    # ── Subscribe / Unsubscribe ────────────────────────────────────────────────

    def subscribe(self, agent_id: str) -> list[dict[str, Any]]:
        """Subscribe to detail events for agent. Returns the event backlog."""
        self._subscriptions.add(agent_id)
        buf = self._event_buffers.get(agent_id, [])
        return [
            {
                "agent_id": e.agent_id,
                "event_type": e.event_type,
                "payload": e.payload,
            }
            for e in buf
        ]

    def unsubscribe(self, agent_id: str) -> None:
        """Stop streaming detail events for agent."""
        self._subscriptions.discard(agent_id)

    # ── Answer question ────────────────────────────────────────────────────────

    async def answer_question(self, question_node_ref: str, answer: str) -> bool:
        """Answer a pending question. Returns True if a runner handled it."""
        # Update DB first
        await self.db.answer_agent_question(question_node_ref, answer)
        # Find which runner owns this question and unblock it
        for runner in self._runners.values():
            if runner.answer_question(question_node_ref, answer):
                return True
        return False

    # ── Branch locks ───────────────────────────────────────────────────────────

    async def acquire_branch_lock(self, spec_ref: str, agent_id: str) -> None:
        await self.db.acquire_branch_lock(spec_ref, agent_id)
        self._emit_notification(
            self._build_lock_notification(spec_ref, agent_id, locked=True)
        )

    async def release_branch_lock(self, spec_ref: str, agent_id: str) -> None:
        await self.db.release_branch_lock(spec_ref, agent_id)
        self._emit_notification(
            self._build_lock_notification(spec_ref, agent_id, locked=False)
        )

    def _build_lock_notification(
        self, spec_ref: str, agent_id: str, *, locked: bool
    ) -> dict[str, Any]:
        from taui.server.protocol import notification_message

        return notification_message(
            "agent/lockChanged",
            {
                "spec_ref": spec_ref,
                "agent_id": agent_id if locked else None,
                "locked": locked,
            },
        )

    # ── List ───────────────────────────────────────────────────────────────────

    def list_active(self) -> list[dict[str, Any]]:
        return [runner.to_dict() for runner in self._runners.values()]

    async def list_all(self) -> list[dict[str, Any]]:
        """Return all agent sessions from DB (active + historical)."""
        rows = await self.db.list_agent_sessions()
        return list(rows)

    # ── Event handling ─────────────────────────────────────────────────────────

    def _on_agent_event(self, event: AgentEvent) -> None:
        """Called from AgentRunner (possibly on a background task)."""
        # Buffer the event
        buf = self._event_buffers.get(event.agent_id)
        if buf is not None:
            buf.append(event)

        # Forward as notification
        if self._notification_callback is not None:
            notifications = self._build_notifications(event)
            for notification in notifications:
                try:
                    self._notification_callback(notification)
                except Exception:
                    logger.exception(
                        "AgentManager notification callback failed agent_id=%s",
                        event.agent_id,
                    )

    def _build_notifications(self, event: AgentEvent) -> list[dict[str, Any]]:
        """Convert an AgentEvent into zero or more JSON-RPC notification dicts."""
        from taui.server.protocol import notification_message

        notifications: list[dict[str, Any]] = []

        if event.event_type == "state_change":
            notifications.append(
                notification_message(
                    "agent/stateChanged",
                    {
                        "agent_id": event.agent_id,
                        "state": event.payload.get("state"),
                        "spec_ref": event.payload.get("spec_ref"),
                    },
                )
            )
        elif event.event_type == "tool_call":
            # Always emit brief indicator
            notifications.append(
                notification_message(
                    "agent/toolBrief",
                    {
                        "agent_id": event.agent_id,
                        "tool_name": event.payload.get("tool_name"),
                    },
                )
            )
            # If subscribed, also emit full detail
            if event.agent_id in self._subscriptions:
                notifications.append(
                    notification_message(
                        "agent/toolCall",
                        {
                            "agent_id": event.agent_id,
                            "tool_name": event.payload.get("tool_name"),
                            "arguments": event.payload.get("arguments"),
                            "call_id": event.payload.get("call_id"),
                        },
                    )
                )
        elif event.event_type == "tool_result":
            if event.agent_id in self._subscriptions:
                notifications.append(
                    notification_message(
                        "agent/toolResult",
                        {
                            "agent_id": event.agent_id,
                            "call_id": event.payload.get("call_id"),
                            "output": event.payload.get("output"),
                            "error": event.payload.get("error"),
                            "duration_ms": event.payload.get("duration_ms"),
                        },
                    )
                )
        elif event.event_type == "message":
            if event.agent_id in self._subscriptions:
                notifications.append(
                    notification_message(
                        "agent/message",
                        {
                            "agent_id": event.agent_id,
                            "message": event.payload,
                        },
                    )
                )
        elif event.event_type == "question_asked":
            notifications.append(
                notification_message(
                    "agent/questionAsked",
                    {
                        "agent_id": event.agent_id,
                        "question_node": event.payload,
                    },
                )
            )

        return notifications

    # Legacy compatibility
    def _build_notification(self, event: AgentEvent) -> dict[str, Any] | None:
        notifications = self._build_notifications(event)
        return notifications[0] if notifications else None

    def _emit_notification(self, notification: dict[str, Any]) -> None:
        if self._notification_callback is not None:
            try:
                self._notification_callback(notification)
            except Exception:
                logger.exception("AgentManager _emit_notification failed")

    def get_buffered_events(self, agent_id: str) -> list[AgentEvent]:
        return list(self._event_buffers.get(agent_id, []))

    def cleanup_runner(self, agent_id: str) -> None:
        self._runners.pop(agent_id, None)

    # ── Startup recovery ───────────────────────────────────────────────────────

    async def startup_recovery(self) -> None:
        """Reload agent state from the DB after a server restart.

        For sessions that were in a non-terminal state (running, thinking, etc.)
        when the server was last shut down:

        1. Mark the session state as ``stopped`` in the DB.
        2. Restore their event buffers from the ``agent_events`` table so that
           detail-panel subscribers can replay history.
        3. Dismiss any pending questions (the runner that would have answered
           them no longer exists).
        4. Release any branch locks that were held by these orphaned sessions.
        """
        interrupted = await self.db.list_agent_sessions_by_states(_INTERRUPTED_STATES)
        if not interrupted:
            logger.info("startup_recovery: no interrupted sessions found")
            return

        logger.info(
            "startup_recovery: found %d interrupted session(s), recovering…",
            len(interrupted),
        )

        for row in interrupted:
            agent_id: str = row["agent_id"]

            # 1. Mark as stopped in the DB
            await self.db.update_agent_state(agent_id, "stopped")

            # 2. Restore event buffer from DB
            db_events = await self.db.get_agent_events(agent_id)
            self._event_buffers[agent_id] = [
                AgentEvent(
                    agent_id=agent_id,
                    event_type=ev["event_type"],
                    payload=json.loads(ev["payload"])
                    if isinstance(ev["payload"], str)
                    else ev["payload"],
                )
                for ev in db_events
            ]

            # Append a synthetic "stopped_on_restart" event so the UI can show
            # that this agent was interrupted and not still running.
            recovery_event = AgentEvent(
                agent_id=agent_id,
                event_type="state_change",
                payload={
                    "state": "stopped",
                    "spec_ref": row.get("spec_ref", ""),
                    "reason": "server_restart",
                },
            )
            self._event_buffers[agent_id].append(recovery_event)
            # Persist it too so future restarts include it
            await self.db.add_agent_event(
                agent_id=agent_id,
                event_type=recovery_event.event_type,
                payload=json.dumps(recovery_event.payload),
            )

            # 3. Dismiss pending questions
            await self.db.dismiss_all_agent_questions(agent_id)

            # 4. Release branch locks held by this agent
            locks = await self.db.list_branch_locks_for_agent(agent_id)
            for lock in locks:
                await self.db.release_branch_lock(lock["spec_ref"], agent_id)
                logger.info(
                    "startup_recovery: released branch lock spec_ref=%s agent_id=%s",
                    lock["spec_ref"],
                    agent_id,
                )

            logger.info(
                "startup_recovery: agent_id=%s was %r → marked stopped, "
                "restored %d events, dismissed questions, released locks",
                agent_id,
                row["state"],
                len(self._event_buffers[agent_id]),
            )

    async def shutdown(self) -> None:
        """Stop all active agents and wait for their tasks to finish."""
        runner_ids = list(self._runners.keys())
        for agent_id in runner_ids:
            try:
                await self.stop(agent_id)
            except Exception:
                logger.exception(
                    "AgentManager shutdown: error stopping agent_id=%s", agent_id
                )
        logger.info("AgentManager shutdown complete")
