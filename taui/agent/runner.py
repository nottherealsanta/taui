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

from taui.agent.cost_tracker import CostTracker
from taui.agent.system_prompt_loader import get_prompt_template, render_prompt_template
from taui.llm.types import Message, ToolCall
from taui.llms.base import ProviderTurnResult
from taui.specs.db import SpecDB
from taui.tools.executor import (
    ToolExecutor,
    ExecutionCompleted,
    ExecutionRequiresApproval,
    ExecutionDenied,
)

logger = logging.getLogger(__name__)

# Default token budget for auto-compaction (matches typical 200k context models)
_DEFAULT_MAX_INPUT_TOKENS = 180_000
_COMPACTION_SOFT_RATIO = 0.80
_COMPACTION_HARD_RATIO = 0.90


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
    event_type: str  # state_change | tool_call | tool_result | message | token | cost_update | turn_complete | permission_denial | thinking_delta | error
    payload: dict[str, Any]


# Callback types
EventCallback = Callable[[AgentEvent], None]


def _build_system_prompt(
    spec_ref: str,
    task: str,
    *,
    working_dir: str = "",
    spec_tree_outline: str = "",
    tool_names: list[str] | None = None,
    agent_definition: Any | None = None,
    agent_type: str = "root",
) -> str:
    """Build a structured system prompt using the SystemPromptBuilder pattern."""
    from taui.tools.prompt_builder import ProjectContext, SystemPromptBuilder

    import platform

    builder = SystemPromptBuilder()
    builder.with_os(platform.system(), platform.release())

    if working_dir:
        from pathlib import Path as _Path

        try:
            ctx = ProjectContext.discover_with_git(_Path(working_dir), "")
            builder.with_project_context(ctx)
        except Exception:
            ctx = ProjectContext.discover(_Path(working_dir), "")
            builder.with_project_context(ctx)

    # Agent-specific prompt section from markdown template
    role_template = get_prompt_template(
        "sub-agent" if agent_type == "sub_agent" else "root"
    )
    if role_template:
        builder.append_section(
            render_prompt_template(
                role_template,
                {
                    "workspace": working_dir,
                    "available_tools": ", ".join(tool_names or []),
                },
            )
        )

    # Agent-specific prefix from definition
    if agent_definition and hasattr(agent_definition, "system_prompt_prefix"):
        prefix = agent_definition.system_prompt_prefix
        if prefix:
            builder.append_section(f"# Agent Role\n{prefix}")

    # Task section
    task_section = f"# Assignment\nYou are assigned to spec branch: {spec_ref!r}.\n\nYour current task is:\n{task}"
    builder.append_section(task_section)

    if spec_tree_outline:
        builder.append_section(
            "# Current Spec Tree\n"
            "Below is an outline of the project's spec tree. Use spec-tree tools "
            "to read full node content or modify nodes.\n\n" + spec_tree_outline
        )
    if tool_names:
        builder.append_section("# Available Tools\n" + ", ".join(tool_names))

    builder.append_section(
        "# Getting Started\n"
        "IMPORTANT: You MUST use tools to complete your task. Do NOT just describe "
        "what you plan to do — actually do it by calling the appropriate tools.\n\n"
        "Start by understanding the project using read, glob, grep, find, and "
        "spec-tree tools. Then proceed with the task. Always call at least one "
        "tool before providing your final answer.\n\n"
        "When finished, provide a summary of what you found or accomplished."
    )

    return builder.render()


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
        working_dir: Any | None = None,  # Path — workspace root for tool context
        agent_type: str = "root",  # "root" | "sub_agent"
        display_name: str | None = None,
        agent_definition: Any | None = None,  # AgentDefinition — for tool restrictions
        history_db: Any | None = None,  # HistoryDB — global message history
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
        self._working_dir = working_dir
        self.agent_type = agent_type
        self.display_name = display_name or agent_id
        self.agent_definition = agent_definition
        self.history_db = history_db

        self.state: AgentState = AgentState.IDLE
        self._stop_flag = asyncio.Event()
        self._steer_queue: asyncio.Queue[str] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

        # Cost tracking (claw-code pattern)
        self.cost_tracker = CostTracker(session_id=session_id)

        # Tool executor — centralizes policy, hooks, timeout, validation
        # (claw-code pattern: runner delegates to executor instead of inline)
        self._tool_executor: ToolExecutor | None = None  # lazily built in _task_loop

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
            "agent_type": self.agent_type,
            "display_name": self.display_name,
            "cost": self.cost_tracker.to_dict(),
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

        # Build spec tree outline for context
        spec_outline = ""
        if self.spec_service is not None:
            try:
                nodes = await self.spec_service.get_tree()
                lines: list[str] = []
                for n in nodes:
                    indent = "  " * n.depth
                    title = (
                        n.markdown.split("\n")[0].lstrip("# ").strip()
                        if n.markdown
                        else n.anchor
                    )
                    lines.append(f"{indent}- {n.spec_ref}: {title}")
                spec_outline = "\n".join(lines)
            except Exception:
                pass

        import pathlib

        wd = self._working_dir or pathlib.Path.cwd()
        tool_names = (
            list(self.tool_registry.names())
            if hasattr(self.tool_registry, "names")
            else None
        )

        # Filter tools by agent definition categories (claw-code pattern)
        if self.agent_definition is not None and tool_names:
            filtered_names: list[str] = []
            for tn in tool_names:
                try:
                    t = self.tool_registry.get(tn)
                    cat = getattr(t, "category", None)
                    if cat is None or self.agent_definition.accepts_category(cat):
                        filtered_names.append(tn)
                except ValueError:
                    filtered_names.append(tn)
            tool_names = filtered_names

        system_content = _build_system_prompt(
            self.spec_ref,
            task,
            working_dir=str(wd),
            spec_tree_outline=spec_outline,
            tool_names=tool_names,
            agent_definition=self.agent_definition,
            agent_type=self.agent_type,
        )

        self._messages = [
            Message(
                role="system",
                content=system_content,
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

            # Auto-compact conversation if approaching token budget (claw-code pattern)
            self._maybe_compact()

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

            # ── Cost tracking: record LLM turn ───────────────────────
            turn_input_tokens, turn_output_tokens = self._estimate_turn_tokens(result)
            cost_record = self.cost_tracker.record_llm_turn(
                model=self.model,
                input_tokens=turn_input_tokens,
                output_tokens=turn_output_tokens,
            )
            cost_event = AgentEvent(
                agent_id=self.agent_id,
                event_type="cost_update",
                payload={
                    "turn_cost_usd": round(cost_record.cost_usd, 6),
                    "turn_input_tokens": turn_input_tokens,
                    "turn_output_tokens": turn_output_tokens,
                    **self.cost_tracker.to_dict(),
                },
            )
            self._emit(cost_event)
            await self._persist_event(cost_event)

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
                # Sub-agents can sometimes respond with planning text before
                # actually using tools. Nudge once or twice if no tool has
                # been executed yet.
                has_tool_results = any(msg.role == "tool" for msg in self._messages)
                if self.agent_type == "sub_agent" and turn < 2 and not has_tool_results:
                    nudge = (
                        "You responded with text but did not call any tools. "
                        "You MUST use tools (read, grep, glob, spec-tree tools, etc.) "
                        "to complete your task. Do NOT just describe what you plan to do — "
                        "actually do it now."
                    )
                    self._messages.append(Message(role="user", content=nudge))
                    await self._persist_message(role="user", content=nudge)
                    logger.info(
                        "AgentRunner nudged sub-agent to use tools agent_id=%s turn=%s",
                        self.agent_id,
                        turn,
                    )
                    continue

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
                tool_result_msg, tool_duration_ms = await self._execute_tool(tc, msg_id)
                tool_results.append(tool_result_msg)

                # ── Cost tracking: record tool call ───────────────────
                self.cost_tracker.record_tool_call(
                    tool_name=tc.name,
                    duration_ms=tool_duration_ms,
                )

            self._messages.extend(tool_results)

            # ── Emit turn_complete event ──────────────────────────────
            turn_complete_event = AgentEvent(
                agent_id=self.agent_id,
                event_type="turn_complete",
                payload={
                    "turn": turn,
                    "tool_calls_count": len(result.tool_calls),
                    **self.cost_tracker.to_dict(),
                },
            )
            self._emit(turn_complete_event)
            await self._persist_event(turn_complete_event)

        else:
            logger.warning(
                "AgentRunner hit max_turns=%s agent_id=%s",
                self.max_turns,
                self.agent_id,
            )

    def _maybe_compact(self) -> None:
        """Drop oldest non-essential messages when approaching token budget.

        Mirrors Session.compact_for_token_budget but operates on the in-memory
        message list directly (claw-code pattern: auto-compaction before each LLM turn).
        """
        # Rough estimate: ~4 chars per token
        est_tokens = sum(len(m.content or "") // 4 for m in self._messages)
        soft_limit = int(_DEFAULT_MAX_INPUT_TOKENS * _COMPACTION_SOFT_RATIO)

        if est_tokens <= soft_limit:
            return

        # Preserve system (index 0) and the most recent messages
        removed = 0
        while est_tokens > soft_limit and len(self._messages) > 4:
            # Find oldest droppable message (skip system at 0, last 3 messages)
            drop_idx: int | None = None
            for i in range(1, len(self._messages) - 3):
                if self._messages[i].role != "system":
                    drop_idx = i
                    break
            if drop_idx is None:
                break
            est_tokens -= len(self._messages[drop_idx].content or "") // 4
            del self._messages[drop_idx]
            removed += 1

        if removed > 0:
            logger.info(
                "Auto-compacted %d messages for token budget agent_id=%s",
                removed,
                self.agent_id,
            )

    def _estimate_turn_tokens(self, result: ProviderTurnResult) -> tuple[int, int]:
        """Estimate input/output tokens for one LLM turn.

        If the provider returned actual usage in ``assistant_metadata``, use
        those numbers.  Otherwise fall back to character-based estimation
        (~4 chars per token).
        """
        meta = result.assistant_metadata or {}
        actual_input = meta.get("input_tokens")
        actual_output = meta.get("output_tokens")

        if isinstance(actual_input, int) and isinstance(actual_output, int):
            return actual_input, actual_output

        # Estimate: input = all messages sent, output = assistant reply
        input_chars = sum(len(m.content or "") for m in self._messages)
        output_chars = len(result.text or "")
        for tc in result.tool_calls:
            output_chars += len(tc.name) + len(str(tc.arguments))

        return max(1, input_chars // 4), max(1, output_chars // 4)

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

        # Filter tool schemas by agent definition categories (claw-code pattern)
        if self.agent_definition is not None and tool_schemas:
            filtered: list[dict[str, Any]] = []
            for schema in tool_schemas:
                name = schema.get("function", {}).get("name", "")
                try:
                    tool = self.tool_registry.get(name)
                    cat = getattr(tool, "category", None)
                    if cat is None or self.agent_definition.accepts_category(cat):
                        filtered.append(schema)
                except (ValueError, KeyError):
                    filtered.append(schema)
            tool_schemas = filtered

        return await self.llm.create_turn(
            messages=messages_raw,
            model=self.model,
            tools=tool_schemas or None,
        )

    async def _execute_tool(
        self, tool_call: Any, assistant_msg_id: int
    ) -> tuple[Message, int]:
        """Execute a single tool call via ToolExecutor, persist result, emit events.

        Delegates to the centralized ToolExecutor which handles policy
        enforcement, schema validation, hooks, and timeouts (claw-code
        pattern: runner delegates to executor instead of inline execution).

        Returns a tuple of (tool_result_message, duration_ms).
        """
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

        # Enforce agent definition tool restrictions (claw-code pattern)
        if self.agent_definition is not None:
            try:
                tool_obj = self.tool_registry.get(tool_name)
                cat = getattr(tool_obj, "category", None)
                if cat is not None and not self.agent_definition.accepts_category(cat):
                    error = (
                        f"Tool '{tool_name}' (category={cat}) is not allowed "
                        f"for agent type '{self.agent_definition.name}'."
                    )
                    logger.warning(
                        "AgentRunner tool denied by agent_definition agent_id=%s tool=%s cat=%s",
                        self.agent_id,
                        tool_name,
                        cat,
                    )
            except (ValueError, KeyError):
                pass  # Unknown tool — will be caught below

        if error is None:
            # Build context for ToolExecutor
            from taui.tools.base import ToolContext
            import pathlib

            ctx = ToolContext(
                working_dir=self._working_dir or pathlib.Path.cwd(),
                session=_AgentSession(self.spec_service, agent_runner=self)
                if self.spec_service
                else _AgentSession(None, agent_runner=self),
                policy=self._build_agent_policy(),
                agent_name=self.display_name,
                session_id=self.session_id,
            )

            # Delegate to ToolExecutor (handles policy, hooks, validation, timeout)
            executor = self._get_tool_executor()
            outcome = await executor.run(
                tool_call_id=call_id,
                tool_name=tool_name,
                arguments=arguments,
                context=ctx,
                approved=True,  # agent auto-approves within its policy
            )

            if isinstance(outcome, ExecutionCompleted):
                if outcome.result.error:
                    error = outcome.result.content
                else:
                    output = outcome.result.content
            elif isinstance(outcome, ExecutionDenied):
                error = outcome.result.content
                # Emit permission_denial event
                denial_event = AgentEvent(
                    agent_id=self.agent_id,
                    event_type="permission_denial",
                    payload={
                        "call_id": call_id,
                        "tool_name": tool_name,
                        "reason": outcome.result.content,
                    },
                )
                self._emit(denial_event)
                await self._persist_event(denial_event)
            elif isinstance(outcome, ExecutionRequiresApproval):
                # For agent execution, auto-approve confirmable tools
                # (the policy already handles this, but as a safety net)
                error = f"Tool '{tool_name}' requires user approval: {outcome.reason}"

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
        return (
            Message(
                role="tool",
                content=result_content,
                tool_call_id=call_id,
                name=tool_name,
            ),
            duration_ms,
        )

    def _get_tool_executor(self) -> ToolExecutor:
        """Lazily build the ToolExecutor with registered hooks."""
        if self._tool_executor is None:
            from taui.tools.hooks import HookConfig, BashSafetyHook

            hook_config = HookConfig()  # shell hooks can be loaded from settings
            self._tool_executor = ToolExecutor(
                registry=self.tool_registry,
                default_timeout_sec=120,
                hook_config=hook_config,
            )
            # Register built-in programmatic hooks
            self._tool_executor._hook_runner.register_pre(BashSafetyHook())
        return self._tool_executor

    def _build_agent_policy(self) -> "Policy":
        """Build the tool execution policy for agent-mode execution."""
        from taui.config.policies import Policy
        from taui.config.settings import BashPolicySettings

        auto_approve = {
            # Spec-tree tools
            "spec_get_tree",
            "spec_get_node",
            "spec_get_branch",
            "spec_create_node",
            "spec_create_sibling",
            "spec_update_node",
            "spec_move_node",
            # File read & search
            "read",
            "glob",
            "grep",
            "find",
            "codesearch",
            # Shell
            "bash",
            # Git (read-only)
            "git",
            # LSP
            "lsp",
            # Planning
            "plan",
            "todowrite",
            "question",
            # Skills
            "skill",
            # Agent
            "monty",
            # Write tools (auto-approve in agent mode)
            "write",
            "edit",
            "apply_patch",
            "multiedit",
        }
        return Policy(
            auto_approve=auto_approve,
            confirm={"spec_delete_node", "skill_import", "task"},
            deny=set(),
            bash=BashPolicySettings(default_timeout_sec=60),
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
            msg_id = await self.db.record_agent_message(
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
            msg_id = 0

        if self.history_db is not None:
            try:
                await self.history_db.record_message(
                    agent_id=self.agent_id,
                    role=role,
                    content=content,
                    tool_call_id=tool_call_id,
                    name=name,
                )
            except Exception:
                logger.exception(
                    "Failed to record message in history DB agent_id=%s",
                    self.agent_id,
                )

        return msg_id
