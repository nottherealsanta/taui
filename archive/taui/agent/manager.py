"""
AgentManager — central coordinator for all agent sessions.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from taui.agent.agents import get_agent_definition, AGENT_DEFINITIONS
from taui.agent.runner import AgentEvent, AgentRunner, AgentState
from taui.agent.naming import AgentNamePool, generate_sub_agent_id, AGENT_COLOR_HEX
from taui.tangle.agent_db import AgentHistoryDB

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

    def __init__(
        self,
        db: AgentHistoryDB,
        *,
        history_db: Any | None = None,
        workspace: Path | None = None,
        stream_client: Any | None = None,
    ) -> None:
        self.db = db
        self.history_db = history_db
        self._workspace = workspace
        self._stream_client = stream_client  # StreamClient for durable streams
        self._runners: dict[str, AgentRunner] = {}  # agent_id → runner
        self._event_buffers: dict[str, list[AgentEvent]] = {}  # agent_id → events
        self._subscriptions: set[str] = (
            set()
        )  # agent_ids with active detail subscribers
        self._notification_callback: NotificationCallback | None = None
        self._name_pool = AgentNamePool()
        self._prime_agent: Any | None = None  # Set by MethodHandlers after creation

    def set_notification_callback(self, callback: NotificationCallback | None) -> None:
        self._notification_callback = callback

    def set_stream_client(self, stream_client: Any) -> None:
        """Set the durable streams client (called from app setup)."""
        self._stream_client = stream_client

    def set_prime_agent(self, prime_agent: Any) -> None:
        """Set a reference to the persistent PrimeAgent for root agent → Prime communication."""
        self._prime_agent = prime_agent

    # ── Launch ─────────────────────────────────────────────────────────────────

    async def launch(
        self,
        *,
        tangle_ref: str | None = None,
        spec_ref: str | None = None,
        task: str,
        tier: str = "medium",
        llm: Any,  # BaseLLMClient
        model: str,
        tool_registry: Any,  # ToolRegistry
        spec_service: Any | None = None,  # SpecService — for spec-tree tools
        parent_agent_id: str | None = None,
        working_dir: Any | None = None,  # Path — workspace root
        agent_type: str = "root",  # "root" | "sub_agent"
    ) -> AgentRunner:
        ref = tangle_ref or spec_ref
        if not ref:
            raise ValueError("tangle_ref is required")
        agent_id = str(uuid4())
        session_id = str(uuid4())

        # Assign display name based on agent type
        if agent_type == "sub_agent":
            display_name = generate_sub_agent_id()
            max_turns = 15
        else:
            display_name = self._name_pool.allocate()
            max_turns = 50

        await self.db.create_agent_session(
            agent_id=agent_id,
            session_id=session_id,
            spec_ref=ref,
            task=task,
            tier=tier,
            model=model,
            parent_agent_id=parent_agent_id,
            agent_type=agent_type,
            display_name=display_name,
        )

        if self.history_db is not None:
            try:
                await self.history_db.record_session(
                    agent_id=agent_id,
                    workspace=str(self._workspace) if self._workspace else None,
                    spec_ref=ref,
                    task=task,
                    display_name=display_name,
                    model=model,
                    agent_type=agent_type,
                )
            except Exception:
                logger.exception("Failed to record session in history DB")

        # Resolve agent definition for tool/prompt restrictions (claw-code pattern)
        agent_def = None
        if agent_type in AGENT_DEFINITIONS:
            agent_def = get_agent_definition(agent_type)
            max_turns = agent_def.max_turns

        self._event_buffers[agent_id] = []

        runner = AgentRunner(
            agent_id=agent_id,
            session_id=session_id,
            spec_ref=ref,
            task=task,
            tier=tier,
            llm=llm,
            model=model,
            db=self.db,
            tool_registry=tool_registry,
            spec_service=spec_service,
            event_callback=self._on_agent_event,
            parent_agent_id=parent_agent_id,
            working_dir=working_dir,
            agent_type=agent_type,
            display_name=display_name,
            max_turns=max_turns,
            agent_definition=agent_def,
            history_db=self.history_db,
            stream_client=self._stream_client,
        )

        self._runners[agent_id] = runner
        runner.start()

        logger.info(
            "AgentManager launched agent_id=%s display_name=%s type=%s tangle_ref=%s tier=%s",
            agent_id,
            display_name,
            agent_type,
            ref,
            tier,
        )
        return runner

    # ── Stop ───────────────────────────────────────────────────────────────────

    async def stop(self, agent_id: str) -> None:
        runner = self._runners.get(agent_id)
        if runner is None:
            raise ValueError(f"No active agent with id={agent_id!r}")
        await runner.stop_safely()
        # Release display name back to pool if it's a root agent
        if runner.agent_type == "root":
            self._name_pool.release(runner.display_name)
        self._runners.pop(agent_id, None)
        logger.info("AgentManager stopped agent_id=%s", agent_id)

    # ── Close ──────────────────────────────────────────────────────────────────

    async def close(self, agent_id: str) -> None:
        """Close a root agent and clean up all associated resources.

        Unlike ``stop``, this is the user-initiated "dismiss" action. It:
        1. Stops the runner if still active (force-stop).
        2. Releases the display name back to the pool.
        3. Dismisses any pending questions the agent was waiting on.
        4. Releases any branch locks held by the agent.
        5. Clears the in-memory event buffer and subscription.

        It is safe to call on an agent that is already done/idle — in that
        case only the cleanup in steps 3–5 happens (no runner to stop).
        """
        runner = self._runners.get(agent_id)
        if runner is not None:
            await runner.stop_safely()
            if runner.agent_type == "root":
                self._name_pool.release(runner.display_name)
            self._runners.pop(agent_id, None)

        # Dismiss any pending questions
        try:
            await self.db.dismiss_all_agent_questions(agent_id)
        except Exception:
            logger.exception(
                "AgentManager.close: error dismissing questions agent_id=%s", agent_id
            )

        # Release any branch locks still held
        try:
            locks = await self.db.list_branch_locks_for_agent(agent_id)
            for lock in locks:
                await self.db.release_branch_lock(lock["spec_ref"], agent_id)
        except Exception:
            logger.exception(
                "AgentManager.close: error releasing locks agent_id=%s", agent_id
            )

        # Clear in-memory buffers
        self._event_buffers.pop(agent_id, None)
        self._subscriptions.discard(agent_id)

        logger.info("AgentManager closed agent_id=%s", agent_id)

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
        """Subscribe to detail events for agent. Returns the event backlog.

        Each backlog entry is a flat dict with a ``type`` key matching the
        event_type (e.g. "message", "tool_call") plus the payload fields
        merged at the top level – this matches the format the frontend's
        ``parseEvent`` function expects.
        """
        self._subscriptions.add(agent_id)
        buf = self._event_buffers.get(agent_id, [])
        return [{"type": e.event_type, **e.payload} for e in buf]

    async def subscribe_from_stream(
        self, agent_id: str, from_offset: int = 0
    ) -> tuple[list[dict[str, Any]], int | None]:
        """Subscribe to detail events for agent using durable streams.

        Returns a tuple of (event backlog, last_offset) starting from
        ``from_offset``, reading from the durable stream instead of the
        in-memory buffer. Falls back to the in-memory buffer if no stream
        client is available.

        ``last_offset`` is the highest offset in the returned backlog, or
        ``None`` when falling back to the in-memory buffer.

        This is the durable alternative to ``subscribe()`` — clients that
        reconnect can resume from their last-seen offset without missing events.
        """
        self._subscriptions.add(agent_id)

        if self._stream_client is not None:
            try:
                stream_id = f"agents/{agent_id}"
                if await self._stream_client.stream_exists(stream_id):
                    import json as _json

                    chunks = await self._stream_client.read(
                        stream_id, from_offset=from_offset, limit=10000
                    )
                    events: list[dict[str, Any]] = []
                    last_offset: int | None = None
                    for chunk in chunks:
                        try:
                            data = _json.loads(chunk.data)
                            if isinstance(data, dict):
                                data["_offset"] = chunk.offset
                                events.append(data)
                                last_offset = chunk.offset
                        except (ValueError, UnicodeDecodeError):
                            pass
                    return events, last_offset
            except Exception:
                logger.exception(
                    "subscribe_from_stream: stream read failed, falling back to buffer agent_id=%s",
                    agent_id,
                )

        # Fallback to in-memory buffer
        buf = self._event_buffers.get(agent_id, [])
        return [{"type": e.event_type, **e.payload} for e in buf], None

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

    async def acquire_branch_lock(self, tangle_ref: str, agent_id: str) -> None:
        await self.db.acquire_branch_lock(tangle_ref, agent_id)
        self._emit_notification(
            self._build_lock_notification(tangle_ref, agent_id, locked=True)
        )

    async def release_branch_lock(self, tangle_ref: str, agent_id: str) -> None:
        await self.db.release_branch_lock(tangle_ref, agent_id)
        self._emit_notification(
            self._build_lock_notification(tangle_ref, agent_id, locked=False)
        )

    def _build_lock_notification(
        self, tangle_ref: str, agent_id: str, *, locked: bool
    ) -> dict[str, Any]:
        from taui.server.protocol import notification_message

        return notification_message(
            "agent/lockChanged",
            {
                "spec_ref": tangle_ref,
                "tangle_ref": tangle_ref,
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
            # Look up runner metadata for richer notifications
            runner = self._runners.get(event.agent_id)
            notifications.append(
                notification_message(
                    "agent/stateChanged",
                    {
                        "agent_id": event.agent_id,
                        "state": event.payload.get("state"),
                        "spec_ref": event.payload.get("spec_ref"),
                        "tangle_ref": event.payload.get("tangle_ref")
                        or event.payload.get("spec_ref"),
                        "agent_type": runner.agent_type if runner else "root",
                        "display_name": runner.display_name if runner else None,
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
            # If subscribed, also emit full detail via subscribeEvent
            if event.agent_id in self._subscriptions:
                notifications.append(
                    self._wrap_subscribe_event(event),
                )
        elif event.event_type == "tool_result":
            if event.agent_id in self._subscriptions:
                notifications.append(
                    self._wrap_subscribe_event(event),
                )
        elif event.event_type == "message":
            if event.agent_id in self._subscriptions:
                notifications.append(
                    self._wrap_subscribe_event(event),
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

    def _wrap_subscribe_event(self, event: AgentEvent) -> dict[str, Any]:
        """Wrap an AgentEvent as an ``agent/subscribeEvent`` notification.

        The nested ``event`` dict uses the flat format expected by the
        frontend's ``parseDetailEvent``: ``{type, ...payload}``.
        """
        from taui.server.protocol import notification_message

        return notification_message(
            "agent/subscribeEvent",
            {
                "agent_id": event.agent_id,
                "event": {"type": event.event_type, **event.payload},
            },
        )

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
        runner = self._runners.get(agent_id)
        if runner and runner.agent_type == "root":
            self._name_pool.release(runner.display_name)
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
        5. Append a synthetic ``stopped`` event to the durable stream (if available).
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

            # 5. Append recovery event to durable stream and close it
            if self._stream_client is not None:
                stream_id = f"agents/{agent_id}"
                try:
                    if await self._stream_client.stream_exists(stream_id):
                        await self._stream_client.append_event(
                            stream_id,
                            recovery_event.event_type,
                            recovery_event.payload,
                        )
                        await self._stream_client.close_stream(stream_id)
                except Exception:
                    logger.exception(
                        "startup_recovery: failed to append recovery event to stream agent_id=%s",
                        agent_id,
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
