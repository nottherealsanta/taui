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

from taui.agent.context import DEFAULT_MAX_INPUT_TOKENS, compact_messages, estimate_total_tokens
from taui.agent.tokenizer import Tokenizer, create_tokenizer
from taui.agent.types import Message
from taui.llm_provider.errors import ContextOverflowError, QuotaExceededError
from taui.llm_provider.rate_limit import RateLimiter
from taui.llm_provider.types import ProviderToolCall, ProviderTurnResult
from taui.store.events import EventType
from taui.store.stream import StreamClient
from taui.tools.executor import Completed, Denied, NeedsApproval, ToolExecutor

logger = logging.getLogger(__name__)


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
        max_turns: int = 50,
        on_tool_call: Callable[[str, str, dict], Awaitable[None]] | None = None,
        on_tool_result: Callable[[str, str, str, bool], Awaitable[None]] | None = None,
        on_approval: Callable[[str, str, dict], Awaitable[bool]] | None = None,
        on_text: Callable[[str], Awaitable[None]] | None = None,
        on_text_delta: Callable[[str], None] | None = None,
        on_reasoning_delta: Callable[[str], None] | None = None,
        tokenizer: Tokenizer | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.agent_id = agent_id or uuid4().hex[:12]
        self.stream_id = f"agents/{self.agent_id}"
        self._llm = llm
        self._executor = executor
        self._stream = stream
        self._system_prompt = system_prompt
        self._model = model
        self._max_turns = max_turns

        # UI callbacks — optional hooks for frontends
        self._on_tool_call = on_tool_call
        self._on_tool_result = on_tool_result
        self._on_approval = on_approval
        self._on_text = on_text
        self._on_text_delta = on_text_delta
        self._on_reasoning_delta = on_reasoning_delta

        # Batch-question callback: async (list[(question, options)]) -> list[str|None]
        self._on_questions_batch: (
            Callable[[list[tuple[str, list[str] | None]]], Awaitable[list[str | None]]]
            | None
        ) = None

        # Compaction notification callback: (removed, before_tokens, after_tokens) -> None
        self._on_compact: Callable[[int, int, int], None] | None = None

        # Result post-processor callback: (tool_name, call_id, content) -> content
        self._on_result_process: Callable[[str, str, str], str] | None = None

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
            await self._emit(EventType.STREAM_START, {"agent_id": self.agent_id})

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
                turn_result = await self._think_and_act(turn)
                turn_results.append(turn_result)

                # If no tool calls, the agent is done
                if turn_result.tool_calls_count == 0:
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

            # Hit max turns
            self.state = AgentState.DONE
            last_text = turn_results[-1].text or "Max turns reached."
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

    async def _think_and_act(self, turn: int) -> TurnResult:
        """One think→tool→observe cycle."""
        # Wait if paused (in-flight tool calls already completed)
        await self._paused.wait()
        # Think: call LLM
        self.state = AgentState.THINKING
        await self._emit(EventType.STATE_CHANGE, {"state": "thinking", "turn": turn})

        llm_result = await self._call_llm()

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
                    "tool_calls": [
                        _serialize_tool_call(tc) for tc in llm_result.tool_calls
                    ],
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
            # Calibrate tokenizer based on actual input tokens from provider
            actual_input = llm_result.usage.input_tokens
            if actual_input and actual_input > 0:
                estimated = estimate_total_tokens(self._messages, self._tokenizer)
                self._tokenizer.calibrate(estimated, actual_input)

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
        """Inject any pending steering messages into the conversation."""
        while self._steering_queue:
            msg = self._steering_queue.pop(0)
            self._messages.append(Message(role="user", content=msg, kind="steer"))

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

    async def _call_llm(self) -> ProviderTurnResult:
        """Call the LLM with current conversation and tool schemas."""
        self._maybe_compact()
        messages = self._build_llm_messages()
        tools = self._executor.registry.schemas() or None
        # Wire streaming text delta callback to provider
        self._llm.on_text_delta = self._on_text_delta
        self._llm.on_reasoning_delta = self._on_reasoning_delta
        try:
            try:
                if self._rate_limiter:
                    async with self._rate_limiter.acquire():
                        return await self._llm.create_turn(messages, self._model, tools=tools)
                else:
                    return await self._llm.create_turn(messages, self._model, tools=tools)
            except ContextOverflowError:
                # Auto-recovery: aggressive compaction + one retry
                before = estimate_total_tokens(self._messages, self._tokenizer)
                removed = compact_messages(
                    self._messages,
                    soft_ratio=0.50,
                    hard_ratio=0.60,
                    tokenizer=self._tokenizer,
                )
                if removed:
                    after = estimate_total_tokens(self._messages, self._tokenizer)
                    logger.info(
                        "Auto-recovery compaction agent_id=%s removed=%d tokens=%d->%d",
                        self.agent_id, removed, before, after,
                    )
                    if self._on_compact:
                        self._on_compact(removed, before, after)
                    messages = self._build_llm_messages()
                if self._rate_limiter:
                    async with self._rate_limiter.acquire():
                        return await self._llm.create_turn(messages, self._model, tools=tools)
                else:
                    return await self._llm.create_turn(messages, self._model, tools=tools)
        finally:
            self._llm.on_text_delta = None
            self._llm.on_reasoning_delta = None

    def _maybe_compact(self) -> None:
        """Compact messages if approaching token budget."""
        before = estimate_total_tokens(self._messages, self._tokenizer)
        soft = int(DEFAULT_MAX_INPUT_TOKENS * 0.80)
        if before > soft:
            removed = compact_messages(self._messages, tokenizer=self._tokenizer)
            if removed:
                after = estimate_total_tokens(self._messages, self._tokenizer)
                logger.info(
                    "Compacted %d messages agent_id=%s tokens=%d->%d",
                    removed, self.agent_id, before, after,
                )
                if self._on_compact:
                    self._on_compact(removed, before, after)

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

        # Build question specs for the UI
        specs: list[tuple[str, list[str] | None]] = []
        for tc in tcs:
            q = tc.arguments.get("question", "")
            opts = tc.arguments.get("options")
            if opts is not None and not isinstance(opts, list):
                opts = None
            specs.append((q, opts))

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

        outcome = await self._executor.run(tc.call_id, tc.name, tc.arguments)

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
                        tc.call_id, tc.name, tc.arguments, approved=True
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
        return result

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
