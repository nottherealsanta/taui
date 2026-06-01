"""
AgentLoop — the core think → tool → observe cycle.

Simple, functional, extensible. The loop:
1. Sends conversation to the LLM provider
2. If the LLM returns tool calls, executes them through the ToolExecutor
3. Feeds tool results back and repeats
4. Stops when the LLM produces a final text response or max turns is hit

All events are written to the Store via StreamClient.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4

from taui.agent.context import estimate_total_tokens
from taui.agent.tokenizer import Tokenizer, create_tokenizer
from taui.agent.types import Message
from taui.llm_provider.errors import ContextOverflowError, QuotaExceededError
from taui.llm_provider.rate_limit import RateLimiter
from taui.llm_provider.types import ProviderToolCall, ProviderTurnResult
from taui.store.events import EventType
from taui.store.stream import StreamClient
from taui.tools.executor import Completed, Denied, NeedsApproval, ToolExecutor

logger = logging.getLogger(__name__)

# Maximum consecutive compaction failures (raise or removed==0) before the
# loop stops attempting further compactions for the remainder of the session.
# Prevents the auto-recovery path from looping indefinitely on irrecoverable
# contexts (e.g. a single oversized user message).
MAX_COMPACT_FAILURES = 3


class AgentState(StrEnum):
    IDLE = "idle"
    THINKING = "thinking"
    TOOL_EXECUTION = "tool_execution"
    DONE = "done"
    ERROR = "error"


@dataclass
class TurnResult:
    """Result of one complete agent turn (think + all tool executions)."""

    text: str | None
    tool_calls_count: int
    turn_number: int
    usage: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class RunResult:
    """Result of a complete agent run."""

    text: str  # Final assistant response
    turns: int
    state: AgentState = AgentState.DONE
    turn_results: list[TurnResult] = field(default_factory=list)

    @property
    def total_usage(self) -> dict[str, int]:
        """Aggregate usage across all turns."""
        totals: dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "reasoning_tokens": 0,
        }
        for tr in self.turn_results:
            if tr.usage:
                for key in totals:
                    totals[key] += tr.usage.get(key, 0)
        return totals

    @property
    def cost_usd(self) -> float | None:
        """Total estimated cost in USD across all turns. None if no usage data."""
        usage = self.total_usage
        if usage["input_tokens"] == 0 and usage["output_tokens"] == 0:
            return None
        total = 0.0
        for tr in self.turn_results:
            if tr.usage and tr.usage.get("cost_usd") is not None:
                total += tr.usage["cost_usd"]
        return total if total > 0 else None


class AgentLoop:
    """The think → tool → observe agent loop.

    Usage::

        loop = AgentLoop(
            agent_id="agent-1",
            llm=my_provider,
            executor=my_executor,
            stream=my_stream_client,
            system_prompt="You are a helpful assistant.",
        )
        result = await loop.run("What files are in the current directory?")
    """

    def __init__(
        self,
        *,
        agent_id: str | None = None,
        llm: Any,
        executor: ToolExecutor,
        stream: StreamClient | None = None,
        system_prompt: str = "You are a helpful coding assistant.",
        model: str = "default",
        model_variant: str = "",
        max_turns: int = 50,
        on_tool_call: Callable[[str, str, dict], Awaitable[None]] | None = None,
        on_tool_result: Callable[[str, str, str, bool], Awaitable[None]] | None = None,
        on_tool_delta: Callable[[str, str, str], Awaitable[None]] | None = None,
        on_approval: Callable[[str, str, dict], Awaitable[bool]] | None = None,
        on_text: Callable[[str], Awaitable[None]] | None = None,
        on_text_delta: Callable[[str], None] | None = None,
        on_reasoning_delta: Callable[[str], None] | None = None,
        tokenizer: Tokenizer | None = None,
        rate_limiter: RateLimiter | None = None,
        provider_name: str | None = None,
    ) -> None:
        self.agent_id = agent_id or uuid4().hex[:12]
        self.stream_id = f"agents/{self.agent_id}"
        self._llm = llm
        self._executor = executor
        self._stream = stream
        self._system_prompt = system_prompt
        self._model = model
        self._model_variant = model_variant or ""
        self._max_turns = max_turns
        self._provider_name = provider_name

        # UI callbacks — optional hooks for frontends
        self._on_tool_call = on_tool_call
        self._on_tool_result = on_tool_result
        self._on_tool_delta = on_tool_delta
        self._on_approval = on_approval
        self._on_text = on_text
        self._on_text_delta = on_text_delta
        self._on_reasoning_delta = on_reasoning_delta

        # Batch-question callback: async (list[(question, options)]) -> list[str|None]
        self._on_questions_batch: (
            Callable[[list[tuple[str, list[str] | None]]], Awaitable[list[str | None]]]
            | None
        ) = None

        # Compaction notification callback:
        # (removed, before_tokens, after_tokens, summary_text, kind) -> None
        self._on_compact: (
            Callable[[int, int, int, str, str], None] | None
        ) = None

        # Consecutive compaction failures (raise or removed==0). Reset on a
        # successful compaction with removed > 0. Once it reaches
        # MAX_COMPACT_FAILURES the loop stops trying to compact.
        self._compact_failure_count: int = 0

        # Result post-processor callback: (tool_name, call_id, content) -> content
        self._on_result_process: Callable[[str, str, str], str] | None = None

        # Steering-drained callback: called (no args) after steering messages
        # are flushed into the conversation history, so the UI can update.
        self._on_steering_drained: Callable[[], None] | None = None

        # Tokenizer for token estimation and calibration
        self._tokenizer: Tokenizer = tokenizer or create_tokenizer()

        self._rate_limiter = rate_limiter

        self.state = AgentState.IDLE
        self._messages: list[Message] = []
        self._steering_queue: list[str] = []
        self._paused = asyncio.Event()
        self._paused.set()  # starts unpaused (set = not paused)

    @property
    def messages(self) -> list[Message]:
        """Current conversation history (read-only view)."""
        return list(self._messages)

    @property
    def max_input_tokens(self) -> int:
        if self._provider_name:
            from taui.llm_provider.models import get_model_limits
            limits = get_model_limits(self._provider_name, self._model)
            return limits.get("input") or limits.get("context") or 180_000
        return 180_000

    # ── Public API ────────────────────────────────────────────────────────

    async def run(
        self,
        user_message: str,
        *,
        images: list[str] | None = None,
    ) -> RunResult:
        """Run the full agent loop for a user message.

        Returns when the agent produces a final text response,
        hits max turns, or encounters an unrecoverable error.

        *images* is an optional list of data-URL encoded images to attach.
        """
        # Set up stream
        if self._stream:
            await self._stream.ensure_stream(self.stream_id)
            await self._emit(
                EventType.STREAM_START,
                {"agent_id": self.agent_id, "model": self._model},
            )

        # Initialize conversation if empty
        if not self._messages:
            self._messages.append(
                Message(role="system", content=self._system_prompt)
            )

        # Add user message
        self._messages.append(
            Message(role="user", content=user_message, images=images or None)
        )
        event_data: dict[str, Any] = {"text": user_message}
        if images:
            event_data["images"] = images
        await self._emit(EventType.USER_MESSAGE, event_data)

        turn_results: list[TurnResult] = []

        try:
            for turn in range(self._max_turns):
                # Inject any steering messages before calling the LLM
                self._drain_steering()

                turn_result = await self._think_and_act(turn)
                turn_results.append(turn_result)

                # If no tool calls, the agent is done — unless a steer arrived
                if turn_result.tool_calls_count == 0:
                    if self._steering_queue:
                        # Steer arrived during streaming; continue to next turn
                        continue
                    self.state = AgentState.DONE
                    await self._emit(
                        EventType.STREAM_END,
                        {"reason": "complete", "turns": turn + 1},
                    )
                    return RunResult(
                        text=turn_result.text or "",
                        turns=turn + 1,
                        state=AgentState.DONE,
                        turn_results=turn_results,
                    )

            # Hit max turns — give the agent one final, tool-free turn so it
            # returns its findings instead of leaving the caller with whatever
            # (usually empty) text the last tool-calling turn produced.
            self._messages.append(
                Message(
                    role="user",
                    content=(
                        "You have reached your turn limit and can no longer "
                        "call tools. Using only what you have already gathered, "
                        "give your final answer to the original task now."
                    ),
                )
            )
            wrap_up = await self._think_and_act(self._max_turns, with_tools=False)
            turn_results.append(wrap_up)

            self.state = AgentState.DONE
            last_text = wrap_up.text or "Max turns reached."
            await self._emit(
                EventType.STREAM_END,
                {"reason": "max_turns", "turns": self._max_turns},
            )
            return RunResult(
                text=last_text,
                turns=self._max_turns,
                state=AgentState.DONE,
                turn_results=turn_results,
            )

        except ContextOverflowError as exc:
            self.state = AgentState.ERROR
            await self._emit(EventType.ERROR, {"error": str(exc), "error_type": "context_overflow"})
            logger.warning("Context overflow agent_id=%s", self.agent_id)
            raise
        except QuotaExceededError as exc:
            self.state = AgentState.ERROR
            await self._emit(
                EventType.ERROR,
                {
                    "error": str(exc),
                    "error_type": "quota_exceeded",
                    "resets_in_seconds": exc.resets_in_seconds,
                },
            )
            logger.warning("Quota exceeded agent_id=%s", self.agent_id)
            raise
        except Exception as exc:
            self.state = AgentState.ERROR
            await self._emit(EventType.ERROR, {"error": str(exc)})
            logger.exception("Agent loop error agent_id=%s", self.agent_id)
            raise

    # ── Pause / resume / prompt ───────────────────────────────────────────

    def pause(self) -> None:
        """Pause the loop — in-flight tool calls complete, but no new LLM calls."""
        self._paused.clear()

    def resume(self) -> None:
        """Resume the loop — allow new LLM calls."""
        self._paused.set()

    @property
    def is_paused(self) -> bool:
        """Whether the loop is currently paused."""
        return not self._paused.is_set()

    def update_system_prompt(self, new_prompt: str) -> None:
        """Hot-swap the system prompt without restarting the loop.

        Updates both the stored prompt and the first message if it's a system message.
        """
        self._system_prompt = new_prompt
        if self._messages and self._messages[0].role == "system":
            self._messages[0] = Message(role="system", content=new_prompt)

    # ── Core loop ─────────────────────────────────────────────────────────

    async def _think_and_act(self, turn: int, *, with_tools: bool = True) -> TurnResult:
        """One think→tool→observe cycle.

        With ``with_tools=False`` the model gets no tools and can only answer
        with text — used for the final wrap-up turn after the budget is spent.
        """
        # Wait if paused (in-flight tool calls already completed)
        await self._paused.wait()
        # Think: call LLM
        self.state = AgentState.THINKING
        await self._emit(EventType.STATE_CHANGE, {"state": "thinking", "turn": turn})

        llm_result = await self._call_llm(with_tools=with_tools)

        # Capture pre-append token estimate for calibration (A2 fix).
        # The provider's usage.input_tokens reflects the messages *sent*
        # (before the assistant reply), so we must estimate against the
        # same set — i.e. before appending the assistant message.
        _pre_append_estimate: int | None = None
        if llm_result.usage and llm_result.usage.input_tokens:
            _pre_append_estimate = estimate_total_tokens(
                self._messages, self._tokenizer
            )

        # Record assistant message
        assistant_msg = Message(
            role="assistant",
            content=llm_result.text or None,
            tool_calls=llm_result.tool_calls or None,
        )
        self._messages.append(assistant_msg)

        if llm_result.text or llm_result.tool_calls:
            await self._emit(
                EventType.ASSISTANT_MESSAGE,
                {
                    "text": llm_result.text,
                    "agent_id": self.agent_id,
                    "model": self._model,
                    "tool_calls": [
                        _serialize_tool_call(tc) for tc in llm_result.tool_calls
                    ],
                    **(
                        {
                            "reasoning_text": llm_result.assistant_metadata[
                                "reasoning_text"
                            ]
                        }
                        if llm_result.assistant_metadata
                        and llm_result.assistant_metadata.get("reasoning_text")
                        else {}
                    ),
                },
            )
        if llm_result.text:
            if self._on_text:
                await self._on_text(llm_result.text)

        usage_data = None
        if llm_result.usage:
            usage_data = llm_result.usage.to_dict()
            if usage_data.get("cost_usd") is None:
                from taui.llm_provider.types import estimate_cost_usd

                usage_data["cost_usd"] = estimate_cost_usd(
                    self._model,
                    usage_data.get("input_tokens", 0),
                    usage_data.get("output_tokens", 0),
                )
            await self._emit(EventType.USAGE, usage_data)
            # Calibrate tokenizer based on actual input tokens from provider.
            # Use the pre-append estimate (computed before the assistant reply
            # was added) so estimated and actual cover the same message set.
            actual_input = llm_result.usage.input_tokens
            if actual_input and actual_input > 0 and _pre_append_estimate is not None:
                self._tokenizer.calibrate(_pre_append_estimate, actual_input)

        # If no tool calls, we're done with this turn
        if not llm_result.tool_calls:
            return TurnResult(
                text=llm_result.text,
                tool_calls_count=0,
                turn_number=turn,
                usage=usage_data,
                metadata=llm_result.assistant_metadata,
            )

        # Act: execute each tool call
        self.state = AgentState.TOOL_EXECUTION
        await self._emit(
            EventType.STATE_CHANGE, {"state": "tool_execution", "turn": turn}
        )

        # Batch question tool calls so the UI can show them together
        question_tcs = [tc for tc in llm_result.tool_calls if tc.name == "question"]
        other_tcs = [tc for tc in llm_result.tool_calls if tc.name != "question"]

        # Execute non-question tools first
        await self._execute_tools_with_parallelism(other_tcs)

        # Execute question tools — batched if possible
        if question_tcs and self._on_questions_batch and len(question_tcs) > 0:
            await self._execute_questions_batch(question_tcs)
            self._drain_steering()
        else:
            for tc in question_tcs:
                await self._execute_tool(tc)
                self._drain_steering()

        return TurnResult(
            text=llm_result.text,
            tool_calls_count=len(llm_result.tool_calls),
            turn_number=turn,
            usage=usage_data,
            metadata=llm_result.assistant_metadata,
        )

    def steer(self, message: str) -> None:
        """Enqueue a steering message to be injected between tool calls."""
        self._steering_queue.append(message)

    def _drain_steering(self) -> None:
        """Inject any pending steering messages into the conversation.

        Multiple queued messages are consolidated into a single Message so the
        LLM sees one coherent user turn rather than several tiny ones.
        """
        if not self._steering_queue:
            return
        combined = "\n\n".join(self._steering_queue)
        self._steering_queue.clear()
        self._messages.append(Message(role="user", content=combined, kind="steer"))
        if self._on_steering_drained:
            self._on_steering_drained()

    async def _execute_tools_with_parallelism(
        self, tool_calls: list[ProviderToolCall]
    ) -> None:
        """Execute tool calls, gathering consecutive parallel-safe ones."""
        from taui.tools.base import ToolCategory

        PARALLEL_SAFE = {ToolCategory.FILE_READ, ToolCategory.SEARCH}
        i = 0
        while i < len(tool_calls):
            tc = tool_calls[i]
            tool = (
                self._executor.registry.get(tc.name)
                if tc.name in self._executor.registry
                else None
            )
            is_safe = tool and getattr(tool, "category", None) in PARALLEL_SAFE

            if is_safe:
                # Collect consecutive parallel-safe calls
                batch = [tc]
                j = i + 1
                while j < len(tool_calls):
                    next_tc = tool_calls[j]
                    next_tool = (
                        self._executor.registry.get(next_tc.name)
                        if next_tc.name in self._executor.registry
                        else None
                    )
                    if next_tool and getattr(next_tool, "category", None) in PARALLEL_SAFE:
                        batch.append(next_tc)
                        j += 1
                    else:
                        break
                if len(batch) > 1:
                    await asyncio.gather(*(self._execute_tool(t) for t in batch))
                else:
                    await self._execute_tool(batch[0])
                self._drain_steering()
                i = j
            else:
                await self._execute_tool(tc)
                self._drain_steering()
                i += 1

    async def _call_llm(self, *, with_tools: bool = True) -> ProviderTurnResult:
        """Call the LLM with current conversation and tool schemas.

        When ``with_tools`` is False the model is given no tool schemas, so it
        can only respond with text. Used for the final wrap-up turn once the
        turn budget is exhausted, forcing the agent to return its findings.
        """
        await self._maybe_compact()
        messages = self._build_llm_messages()
        tools = (self._executor.registry.schemas() or None) if with_tools else None
        # Wire streaming text delta callback to provider
        self._llm.on_text_delta = self._on_text_delta
        self._llm.on_reasoning_delta = self._on_reasoning_delta
        try:
            try:
                if self._rate_limiter:
                    async with self._rate_limiter.acquire():
                        return await self._llm.create_turn(
                            messages,
                            self._model,
                            tools=tools,
                            thinking_level=self._model_variant or None,
                        )
                else:
                    return await self._llm.create_turn(
                        messages,
                        self._model,
                        tools=tools,
                        thinking_level=self._model_variant or None,
                    )
            except ContextOverflowError:
                # Auto-recovery: aggressive compaction + one retry.
                # Circuit breaker: bail out before wasting another API call
                # if compaction has been ineffective MAX_COMPACT_FAILURES
                # times in a row.
                if self._compact_failure_count >= MAX_COMPACT_FAILURES:
                    logger.warning(
                        "Compaction circuit breaker tripped agent_id=%s failures=%d; "
                        "skipping recovery and re-raising context overflow",
                        self.agent_id, self._compact_failure_count,
                    )
                    raise
                removed = await self._run_compaction(reason="overflow")
                if removed:
                    messages = self._build_llm_messages()
                # Retry once regardless of removed: the overflow may have
                # been spurious, in which case the same messages will now
                # succeed. If the retry overflows again, it propagates and
                # the next ContextOverflowError will see an incremented
                # failure counter and short-circuit.
                if self._rate_limiter:
                    async with self._rate_limiter.acquire():
                        return await self._llm.create_turn(
                            messages,
                            self._model,
                            tools=tools,
                            thinking_level=self._model_variant or None,
                        )
                else:
                    return await self._llm.create_turn(
                        messages,
                        self._model,
                        tools=tools,
                        thinking_level=self._model_variant or None,
                    )
        finally:
            self._llm.on_text_delta = None
            self._llm.on_reasoning_delta = None

    async def _maybe_compact(self) -> None:
        """Compact messages if approaching token budget."""
        if self._compact_failure_count >= MAX_COMPACT_FAILURES:
            return
        max_input = self.max_input_tokens
        before = estimate_total_tokens(self._messages, self._tokenizer)
        soft = int(max_input * 0.80)
        if before > soft:
            await self._run_compaction(reason="threshold")

    async def _run_compaction(self, *, reason: str) -> int:
        """Run async compaction, update the failure counter, and emit events.

        Returns the number of messages removed. Always increments the failure
        counter on raise or removed==0 and resets it on removed>0.
        ``reason`` is one of ``"threshold"`` (proactive) or ``"overflow"``
        (post-error recovery) and is recorded on the persisted event.
        """
        from taui.agent.context import (
            async_compact_messages,
            find_previous_summary,
        )

        before = estimate_total_tokens(self._messages, self._tokenizer)
        try:
            removed = await async_compact_messages(
                self._messages,
                tokenizer=self._tokenizer,
                llm=self._llm,
                model=self._model,
                provider_name=self._provider_name or "default",
                max_input_tokens=self.max_input_tokens,
            )
        except Exception:
            self._compact_failure_count += 1
            logger.exception(
                "Compaction failed agent_id=%s reason=%s failures=%d",
                self.agent_id, reason, self._compact_failure_count,
            )
            return 0

        if not removed:
            self._compact_failure_count += 1
            logger.info(
                "Compaction no-op agent_id=%s reason=%s failures=%d",
                self.agent_id, reason, self._compact_failure_count,
            )
            return 0

        self._compact_failure_count = 0
        after = estimate_total_tokens(self._messages, self._tokenizer)
        logger.info(
            "Compacted %d messages agent_id=%s reason=%s tokens=%d->%d",
            removed, self.agent_id, reason, before, after,
        )
        summary_text = find_previous_summary(self._messages)
        await self._emit(
            EventType.COMPACTION,
            {
                "removed": removed,
                "before_tokens": before,
                "after_tokens": after,
                "kind": "async",
                "reason": reason,
                "summary_text": summary_text,
            },
        )
        if self._on_compact:
            self._on_compact(removed, before, after, summary_text or "", reason)
        return removed

    async def _execute_questions_batch(
        self, tcs: list[ProviderToolCall]
    ) -> None:
        """Execute multiple question tool calls as a batch via the UI."""
        # Emit tool_call events for each
        for tc in tcs:
            await self._emit(
                EventType.TOOL_CALL,
                {"call_id": tc.call_id, "name": tc.name, "arguments": tc.arguments},
            )
            if self._on_tool_call:
                await self._on_tool_call(tc.call_id, tc.name, tc.arguments)

        # Build question specs for the UI. Each spec is a tuple of
        # (question, options, recommended). `options` is a list of option
        # dicts ({"label": str, "description": str | None}); `recommended`
        # is the 1-based index of the model's preferred option, if any.
        from taui.tools.builtins.question import (
            _normalize_options,
            _normalize_recommended,
        )

        specs: list[tuple[str, list[dict] | None, int | None]] = []
        for tc in tcs:
            q = tc.arguments.get("question", "")
            opts = _normalize_options(tc.arguments.get("options"))
            recommended = _normalize_recommended(
                tc.arguments.get("recommended"), opts
            )
            specs.append((q, opts, recommended))

        # Call the batch UI callback
        answers = await self._on_questions_batch(specs)

        # Record results for each tool call
        for tc, answer in zip(tcs, answers):
            if answer is None:
                content = (
                    "Question was dismissed. Proceed with your best judgment."
                )
            else:
                content = f"User answered: {answer}"

            self._messages.append(
                Message(
                    role="tool",
                    content=content,
                    tool_call_id=tc.call_id,
                    name=tc.name,
                )
            )
            is_error = False
            await self._emit(
                EventType.TOOL_RESULT,
                {
                    "call_id": tc.call_id,
                    "name": tc.name,
                    "content": content,
                    "error": is_error,
                },
            )
            if self._on_tool_result:
                await self._on_tool_result(
                    tc.call_id, tc.name, content, is_error
                )

    async def _execute_tool(self, tc: ProviderToolCall) -> None:
        """Execute one tool call and append the result to messages."""
        await self._emit(
            EventType.TOOL_CALL,
            {"call_id": tc.call_id, "name": tc.name, "arguments": tc.arguments},
        )
        if self._on_tool_call:
            await self._on_tool_call(tc.call_id, tc.name, tc.arguments)

        async def on_output_delta(chunk: str) -> None:
            if self._on_tool_delta:
                await self._on_tool_delta(tc.call_id, tc.name, chunk)

        delta_callback = on_output_delta if self._on_tool_delta else None
        outcome = await self._executor.run(
            tc.call_id,
            tc.name,
            tc.arguments,
            on_output_delta=delta_callback,
        )

        match outcome:
            case Completed(result=result):
                content = result.content
                is_error = result.error
            case NeedsApproval():
                approved = True  # default: auto-approve
                if self._on_approval:
                    approved = await self._on_approval(tc.call_id, tc.name, tc.arguments)

                if approved:
                    retry = await self._executor.run(
                        tc.call_id,
                        tc.name,
                        tc.arguments,
                        approved=True,
                        on_output_delta=delta_callback,
                    )
                    match retry:
                        case Completed(result=result):
                            content = result.content
                            is_error = result.error
                        case _:
                            content = "Tool execution failed after approval."
                            is_error = True
                else:
                    content = "Tool call denied by user."
                    is_error = True
            case Denied(result=result):
                content = result.content
                is_error = result.error

        if self._on_result_process and not is_error:
            content = self._on_result_process(tc.name, tc.call_id, content)

        self._messages.append(
            Message(
                role="tool",
                content=content,
                tool_call_id=tc.call_id,
                name=tc.name,
            )
        )

        await self._emit(
            EventType.TOOL_RESULT,
            {
                "call_id": tc.call_id,
                "name": tc.name,
                "content": content,
                "error": is_error,
            },
        )
        if self._on_tool_result:
            await self._on_tool_result(tc.call_id, tc.name, content, is_error)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _build_llm_messages(self) -> list[dict[str, Any]]:
        """Convert internal messages to the format LLM providers expect."""
        result: list[dict[str, Any]] = []
        for msg in self._messages:
            entry: dict[str, Any] = {"role": msg.role}
            if msg.images and msg.content is not None:
                # Multimodal: emit content-block array
                blocks: list[dict[str, Any]] = [
                    {"type": "text", "text": msg.content},
                ]
                for image_url in msg.images:
                    blocks.append(
                        {"type": "image_url", "image_url": {"url": image_url}}
                    )
                entry["content"] = blocks
            elif msg.content is not None:
                entry["content"] = msg.content
            if msg.tool_calls:
                entry["tool_calls"] = [
                    tc.to_chat_completions_format() for tc in msg.tool_calls
                ]
                # OpenAI Chat Completions API requires "content" on
                # assistant messages that carry tool_calls, even if null.
                if msg.content is None:
                    entry["content"] = None
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            if msg.name and msg.role == "tool":
                entry["name"] = msg.name
            # Mark system messages as cacheable for provider-level prompt caching
            if msg.role == "system" and not msg.tool_call_id:
                entry["_cache"] = True
            result.append(entry)
        return _assert_tool_call_groups(result)

    async def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        """Write an event to the stream (if stream is configured)."""
        if self._stream:
            try:
                await self._stream.append(self.stream_id, event_type, data)
            except Exception:
                logger.exception(
                    "Failed to emit event agent_id=%s type=%s",
                    self.agent_id,
                    event_type.value,
                )


def _serialize_tool_call(tc: ProviderToolCall) -> dict[str, Any]:
    return {
        "call_id": tc.call_id,
        "name": tc.name,
        "arguments": tc.arguments,
    }


def _assert_tool_call_groups(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and repair tool-call / tool-result ordering before provider send.

    Providers require that every assistant message with ``tool_calls`` is
    immediately followed by matching ``tool`` role messages. This is a
    last-resort defense that catches ordering issues from any source
    (replay, compaction, external stream appends).
    """
    # Index tool messages by tool_call_id.
    tool_msgs: dict[str, dict[str, Any]] = {}
    for msg in messages:
        if msg.get("role") == "tool" and msg.get("tool_call_id"):
            tool_msgs[msg["tool_call_id"]] = msg

    # Collect call_ids that belong to assistant groups.
    grouped_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                call_id = tc.get("id") or ""
                if call_id:
                    grouped_ids.add(call_id)

    if not grouped_ids:
        return messages  # fast path: no tool calls at all

    result: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == "tool" and msg.get("tool_call_id") in grouped_ids:
            continue  # will be placed by parent assistant message

        result.append(msg)

        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                call_id = tc.get("id") or ""
                if call_id in tool_msgs:
                    result.append(tool_msgs[call_id])
                else:
                    result.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": "Tool result was not recorded.",
                    })

    return result
