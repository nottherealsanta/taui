"""
AgentRunner — async think → tool → observe loop for a single agent session.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable
from uuid import uuid4

from taui.llm.types import Message, ToolCall
from taui.llms.base import ProviderTurnResult
from taui.specs.db import SpecDB

logger = logging.getLogger(__name__)


class _AgentSession:
    """Minimal session object injected into ToolContext so spec-tree tools
    can reach SpecService and the AgentRunner without importing at module level."""

    def __init__(self, spec_service: Any, agent_runner: Any | None = None) -> None:
        self.spec_service = spec_service
        self.agent_runner = agent_runner


class AgentState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    THINKING = "thinking"
    TOOL_EXECUTION = "tool_execution"
    STOPPING = "stopping"
    DONE = "done"


@dataclass(slots=True)
class AgentEvent:
    agent_id: str
    event_type: str  # state_change | tool_call | tool_result | message | token
    payload: dict[str, Any]


# Callback types
EventCallback = Callable[[AgentEvent], None]


def _build_system_prompt(spec_ref: str, task: str) -> str:
    return (
        f"You are an AI agent working on the spec tree. "
        f"You are assigned to spec branch: {spec_ref!r}.\n"
        f"Your current task is:\n{task}\n\n"
        "Use the spec-tree tools to read and modify spec nodes. "
        "When you are finished, simply stop calling tools and provide a summary."
    )


class AgentRunner:
    """
    Runs a single agent session. Manages the think → tool → observe loop.

    The runner is created by AgentManager and lives as long as the agent is active.
    It persists all messages, tool calls, and events to SpecDB.
    """

    def __init__(
        self,
        *,
        agent_id: str,
        session_id: str,
        spec_ref: str,
        task: str,
        tier: str,
        llm: Any,  # BaseLLMClient — duck-typed; only create_turn() is called
        model: str,
        db: SpecDB,
        tool_registry: Any,  # ToolRegistry — imported lazily to avoid cycles
        spec_service: Any | None = None,  # SpecService — optional, for spec-tree tools
        event_callback: EventCallback | None = None,
        parent_agent_id: str | None = None,
        max_turns: int = 50,
    ) -> None:
        self.agent_id = agent_id
        self.session_id = session_id
        self.spec_ref = spec_ref
        self.task = task
        self.tier = tier
        self.llm = llm
        self.model = model
        self.db = db
        self.tool_registry = tool_registry
        self.spec_service = spec_service
        self.event_callback = event_callback
        self.parent_agent_id = parent_agent_id
        self.max_turns = max_turns

        self.state: AgentState = AgentState.IDLE
        self._stop_flag = asyncio.Event()
        self._steer_queue: asyncio.Queue[str] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

        # Question blocking: question_node_ref → asyncio.Event
        self._pending_questions: dict[str, asyncio.Event] = {}
        self._question_answers: dict[str, str] = {}  # question_node_ref → answer

        # In-memory conversation history
        self._messages: list[Message] = []

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch the agent loop as a background asyncio task."""
        self._task = asyncio.create_task(
            self._run_loop(), name=f"agent-{self.agent_id}"
        )

    async def stop_safely(self) -> None:
        """Request graceful shutdown. Waits for the current tool to finish."""
        logger.info("AgentRunner stop requested agent_id=%s", self.agent_id)
        self._stop_flag.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=30.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass

    async def steer(self, message: str) -> None:
        """Enqueue a steer message (injected before next think cycle)."""
        await self._steer_queue.put(message)

    async def ask_question(
        self,
        spec_ref: str,
        question: str,
        options: list[str] | None = None,
        timeout: float = 300.0,
    ) -> str | None:
        """Ask the user a question; blocks until answered, dismissed, or timeout.

        Records the question in the DB and emits an agent/questionAsked event.
        Returns the answer string, or None if dismissed or timed out.
        """
        question_node_ref = f"{spec_ref}#question-{uuid4().hex[:8]}"

        await self.db.add_agent_question(
            agent_id=self.agent_id,
            question_node_ref=question_node_ref,
            question=question,
            options=options,
        )

        event = AgentEvent(
            agent_id=self.agent_id,
            event_type="question_asked",
            payload={
                "question_node_ref": question_node_ref,
                "spec_ref": spec_ref,
                "question": question,
                "options": options or [],
            },
        )
        self._emit(event)
        await self._persist_event(event)

        # Block until answered or stop is requested
        done_event = asyncio.Event()
        self._pending_questions[question_node_ref] = done_event

        try:
            # Wait for answer with timeout, but also respect stop_flag
            async def _wait() -> None:
                await done_event.wait()

            wait_task = asyncio.create_task(_wait())
            stop_task = asyncio.create_task(self._stop_flag.wait())
            done, _ = await asyncio.wait(
                [wait_task, stop_task],
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            wait_task.cancel()
            stop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await wait_task
            with contextlib.suppress(asyncio.CancelledError):
                await stop_task

            if wait_task in done:
                answer = self._question_answers.pop(question_node_ref, None)
                return answer
            else:
                # Timed out or stop_flag set — dismiss the question
                await self.db.dismiss_agent_question(question_node_ref)
                return None
        finally:
            self._pending_questions.pop(question_node_ref, None)

    def answer_question(self, question_node_ref: str, answer: str) -> bool:
        """Unblock a pending ask_question() call. Returns True if found."""
        event = self._pending_questions.get(question_node_ref)
        if event is None:
            return False
        self._question_answers[question_node_ref] = answer
        event.set()
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "spec_ref": self.spec_ref,
            "task": self.task,
            "tier": self.tier,
            "state": self.state.value,
            "parent_agent_id": self.parent_agent_id,
        }

    # ── State management ───────────────────────────────────────────────────────

    async def _set_state(self, new_state: AgentState) -> None:
        self.state = new_state
        await self.db.update_agent_state(self.agent_id, new_state.value)
        event = AgentEvent(
            agent_id=self.agent_id,
            event_type="state_change",
            payload={"state": new_state.value, "spec_ref": self.spec_ref},
        )
        self._emit(event)
        await self._persist_event(event)

    def _emit(self, event: AgentEvent) -> None:
        if self.event_callback is not None:
            try:
                self.event_callback(event)
            except Exception:
                logger.exception(
                    "Agent event callback raised agent_id=%s event=%s",
                    self.agent_id,
                    event.event_type,
                )

    async def _persist_event(self, event: AgentEvent) -> None:
        try:
            await self.db.add_agent_event(
                agent_id=event.agent_id,
                event_type=event.event_type,
                payload=json.dumps(event.payload),
            )
        except Exception:
            logger.exception("Failed to persist agent event agent_id=%s", self.agent_id)

    # ── Main loop ──────────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        logger.info(
            "AgentRunner starting agent_id=%s spec_ref=%s task_len=%s",
            self.agent_id,
            self.spec_ref,
            len(self.task),
        )
        try:
            await self._run_task_with_writeback(self.task)

            # Task queue: after first task completes, keep picking up queued tasks
            while not self._stop_flag.is_set():
                next_task = await self.db.pop_agent_task(self.agent_id)
                if next_task is None:
                    break
                logger.info(
                    "AgentRunner picking up queued task agent_id=%s task_id=%s",
                    self.agent_id,
                    next_task["id"],
                )
                await self._run_task_with_writeback(next_task["message"])
                await self.db.complete_agent_task(next_task["id"])

        except asyncio.CancelledError:
            logger.info("AgentRunner cancelled agent_id=%s", self.agent_id)
            raise
        except Exception:
            logger.exception("AgentRunner unexpected error agent_id=%s", self.agent_id)
        finally:
            # Flush any remaining dirty spec files (covers stop/cancel paths)
            if self.spec_service is not None and hasattr(self.spec_service, "writer"):
                try:
                    await self.spec_service.writer.flush_all_files()
                except Exception:
                    logger.exception(
                        "AgentRunner final writeback flush failed agent_id=%s",
                        self.agent_id,
                    )
            # Clean up any pending questions before exiting
            await self.db.dismiss_all_agent_questions(self.agent_id)
            if self.state not in (AgentState.DONE, AgentState.STOPPING):
                await self._set_state(AgentState.DONE)
            else:
                await self._set_state(AgentState.DONE)
            logger.info(
                "AgentRunner finished agent_id=%s state=%s", self.agent_id, self.state
            )

    async def _run_task_with_writeback(self, task: str) -> None:
        """Run one task, deferring spec-file writeback until the task completes."""
        if self.spec_service is not None and hasattr(
            self.spec_service, "defer_writeback"
        ):
            async with self.spec_service.defer_writeback():
                await self._task_loop(task)
        else:
            await self._task_loop(task)

    async def _task_loop(self, task: str) -> None:
        """Run one task (system prompt → think → tool → ... → done)."""
        await self._set_state(AgentState.RUNNING)
        self._messages = [
            Message(
                role="system",
                content=_build_system_prompt(self.spec_ref, task),
            ),
            Message(
                role="user",
                content="Begin working on your assigned task.",
            ),
        ]
        await self._persist_message(role="system", content=self._messages[0].content)
        await self._persist_message(role="user", content=self._messages[1].content)

        for turn in range(self.max_turns):
            if self._stop_flag.is_set():
                logger.info(
                    "AgentRunner stopping early turn=%s agent_id=%s",
                    turn,
                    self.agent_id,
                )
                await self._set_state(AgentState.STOPPING)
                break

            # Inject any pending steer messages
            steer_messages = await self._drain_steer()
            for steer_text in steer_messages:
                steer_content = f"<<STEER>> {steer_text}"
                self._messages.append(Message(role="user", content=steer_content))
                await self._persist_message(role="user", content=steer_content)

            # Think
            await self._set_state(AgentState.THINKING)
            try:
                result = await self._do_llm_turn()
            except Exception as exc:
                logger.exception(
                    "LLM turn failed agent_id=%s turn=%s", self.agent_id, turn
                )
                error_content = f"LLM error: {exc}"
                event = AgentEvent(
                    agent_id=self.agent_id,
                    event_type="error",
                    payload={"error": error_content},
                )
                self._emit(event)
                await self._persist_event(event)
                break

            # Record assistant message
            assistant_msg = Message(
                role="assistant",
                content=result.text or None,
                tool_calls=[
                    ToolCall(id=tc.call_id, name=tc.name, arguments=tc.arguments)
                    for tc in result.tool_calls
                ]
                or None,
            )
            self._messages.append(assistant_msg)
            msg_id = await self._persist_message(
                role="assistant",
                content=result.text or None,
            )
            event = AgentEvent(
                agent_id=self.agent_id,
                event_type="message",
                payload={"role": "assistant", "content": result.text or ""},
            )
            self._emit(event)
            await self._persist_event(event)

            # No tool calls → agent is done with this task
            if not result.tool_calls:
                logger.info(
                    "AgentRunner done (no tool calls) agent_id=%s turn=%s",
                    self.agent_id,
                    turn,
                )
                break

            # Execute tool calls
            await self._set_state(AgentState.TOOL_EXECUTION)
            tool_results: list[Message] = []
            for tc in result.tool_calls:
                if self._stop_flag.is_set():
                    break
                tool_result_msg = await self._execute_tool(tc, msg_id)
                tool_results.append(tool_result_msg)

            self._messages.extend(tool_results)

        else:
            logger.warning(
                "AgentRunner hit max_turns=%s agent_id=%s",
                self.max_turns,
                self.agent_id,
            )

    async def _drain_steer(self) -> list[str]:
        messages: list[str] = []
        while True:
            try:
                msg = self._steer_queue.get_nowait()
                messages.append(msg)
            except asyncio.QueueEmpty:
                break
        return messages

    async def _do_llm_turn(self) -> ProviderTurnResult:
        """Call LLM with current message history + available tools."""
        messages_raw = [m.to_dict() for m in self._messages]
        tool_schemas = self.tool_registry.list_schemas() if self.tool_registry else []

        return await self.llm.create_turn(
            messages=messages_raw,
            model=self.model,
            tools=tool_schemas or None,
        )

    async def _execute_tool(self, tool_call: Any, assistant_msg_id: int) -> Message:
        """Execute a single tool call, persist result, emit events."""
        call_id = tool_call.call_id
        tool_name = tool_call.name
        arguments = tool_call.arguments

        logger.info(
            "AgentRunner executing tool agent_id=%s tool=%s call_id=%s",
            self.agent_id,
            tool_name,
            call_id,
        )

        # Emit tool_call event (brief indicator for UI)
        event = AgentEvent(
            agent_id=self.agent_id,
            event_type="tool_call",
            payload={
                "call_id": call_id,
                "tool_name": tool_name,
                "arguments": arguments,
            },
        )
        self._emit(event)
        await self._persist_event(event)

        # Persist tool call record
        await self.db.record_agent_tool_call(
            call_id=call_id,
            agent_id=self.agent_id,
            message_id=assistant_msg_id,
            tool_name=tool_name,
            arguments=json.dumps(arguments),
        )

        start_ms = time.monotonic()
        output: str | None = None
        error: str | None = None

        try:
            from taui.tools.base import ToolContext
            from taui.config.policies import Policy
            from taui.config.settings import BashPolicySettings

            # Build a permissive policy for agent tool execution
            # (spec-tree tools are auto-approved; bash/write may confirm)
            auto_approve = {
                "spec_get_tree",
                "spec_get_node",
                "spec_get_branch",
                "spec_create_node",
                "spec_create_sibling",
                "spec_update_node",
                "spec_move_node",
                "bash",
                "read",
                "glob",
                "grep",
            }
            bash_settings = BashPolicySettings(
                default_timeout_sec=60,
            )
            policy = Policy(
                auto_approve=auto_approve,
                confirm={"spec_delete_node", "write", "edit"},
                deny=set(),
                bash=bash_settings,
            )

            # Working dir defaults to cwd for now
            import pathlib

            ctx = ToolContext(
                working_dir=pathlib.Path.cwd(),
                session=_AgentSession(self.spec_service, agent_runner=self)
                if self.spec_service
                else _AgentSession(None, agent_runner=self),
                policy=policy,
            )

            tool = self.tool_registry.get(tool_name)
            result = await tool.execute(arguments, ctx)
            output = result.content
            if result.error:
                error = result.content
                output = None

        except ValueError as exc:
            # Unknown tool
            error = f"Unknown tool '{tool_name}': {exc}"
            logger.warning(
                "AgentRunner unknown tool agent_id=%s tool=%s", self.agent_id, tool_name
            )
        except Exception as exc:
            error = f"Tool execution failed: {exc}"
            logger.exception(
                "AgentRunner tool error agent_id=%s tool=%s", self.agent_id, tool_name
            )

        duration_ms = int((time.monotonic() - start_ms) * 1000)

        # Persist tool result
        await self.db.record_agent_tool_result(
            call_id=call_id,
            output=output,
            error=error,
            duration_ms=duration_ms,
        )

        # Emit tool_result event
        result_event = AgentEvent(
            agent_id=self.agent_id,
            event_type="tool_result",
            payload={
                "call_id": call_id,
                "tool_name": tool_name,
                "output": output,
                "error": error,
                "duration_ms": duration_ms,
            },
        )
        self._emit(result_event)
        await self._persist_event(result_event)

        result_content = output if output is not None else (error or "")
        return Message(
            role="tool",
            content=result_content,
            tool_call_id=call_id,
            name=tool_name,
        )

    async def _persist_message(
        self,
        *,
        role: str,
        content: str | None,
        tool_call_id: str | None = None,
        name: str | None = None,
    ) -> int:
        try:
            return await self.db.record_agent_message(
                agent_id=self.agent_id,
                role=role,
                content=content,
                tool_call_id=tool_call_id,
                name=name,
            )
        except Exception:
            logger.exception(
                "Failed to persist agent message agent_id=%s role=%s",
                self.agent_id,
                role,
            )
            return 0
