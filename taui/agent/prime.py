"""
PrimeAgent — persistent, interruptible AI assistant.

Prime lives for the server session lifetime and maintains a growing
conversation history.  It delegates heavy work to root agents (big tasks)
and sub-agents (quick lookups), staying responsive for the user at all times.

Concurrency model: **interrupt-and-pivot**.  When a new message arrives
while Prime is mid-work (thinking or executing tools), the current tool
finishes, partial results are appended, and Prime re-enters the think
cycle with the new message in context.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from taui.agent.system_prompt_loader import (
    get_prompt_template_for_workspace,
    render_prompt_template,
)

logger = logging.getLogger(__name__)

NotificationCallback = Callable[[dict[str, Any]], None]

# Token budget for auto-compaction
_MAX_INPUT_TOKENS = 180_000
_COMPACTION_SOFT_RATIO = 0.80
_CONTEXT_BOUNDARY_MARKER = "[prime:new_context]"
_DEFAULT_HISTORY_PAGE_SIZE = 50


class PrimeState(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    TOOL_EXECUTION = "tool_execution"


class PrimeAgent:
    """Persistent, interruptible Prime agent.

    Usage::

        prime = PrimeAgent(
            workspace=Path("/my/project"),
            spec_service=spec_service,
            agent_manager=agent_manager,
            resolve_llm=resolve_llm_fn,
            emit_notification=emit_fn,
        )
        # From any context (user RPC, root agent report, etc.):
        await prime.send_message("Hello, what's the project structure?")
    """

    AGENT_ID = "prime"  # Fixed agent_id for history DB

    def __init__(
        self,
        *,
        workspace: Path,
        spec_service: Any,
        agent_manager: Any | None = None,
        resolve_llm: Callable[..., tuple[Any, str]],
        emit_notification: NotificationCallback,
        history_db: Any | None = None,
        max_turns: int = 30,
        stream_client: Any | None = None,
    ) -> None:
        self._workspace = workspace
        self._spec_service = spec_service
        self._agent_manager = agent_manager
        self._resolve_llm = resolve_llm
        self._emit = emit_notification
        self._history_db = history_db
        self._max_turns = max_turns
        self._stream_client = stream_client  # Durable streams client

        # Persistent conversation history (grows across all interactions)
        self._messages: list[dict[str, Any]] = []
        self._system_prompt_built = False
        self._history_initialized = False
        self._stream_initialized = False

        # Concurrency primitives
        self._interrupt = asyncio.Event()
        self._pending: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._state = PrimeState.IDLE
        self._loop_task: asyncio.Task[None] | None = None

        # Tool infrastructure (lazily built)
        self._registry: Any | None = None
        self._tool_schemas: list[dict[str, Any]] | None = None
        self._policy: Any | None = None
        self._session: Any | None = None

        # Durable stream IDs for prime
        self._stream_id = "prime"
        self._token_stream_id = "prime/tokens"

    @property
    def state(self) -> PrimeState:
        return self._state

    @property
    def messages(self) -> list[dict[str, Any]]:
        """Read-only view of conversation history."""
        return list(self._messages)

    # ── Public API ─────────────────────────────────────────────────────────────

    async def send_message(
        self,
        content: str,
        *,
        role: str = "user",
        sender: str | None = None,
    ) -> None:
        """Send a message to Prime.

        If Prime is idle, starts the think loop.
        If Prime is busy, sets the interrupt flag so it pivots.

        Args:
            content: The message text.
            role: Message role (usually "user").
            sender: Optional sender label (e.g. "[Agent Kappa]" for root agent reports).
        """
        if sender:
            content = f"[{sender}]: {content}"

        msg = {"role": role, "content": content}

        if self._state == PrimeState.IDLE:
            # Directly append and start loop
            self._messages.append(msg)
            await self._persist_message(msg)
            self._start_loop()
        else:
            # Queue the message and signal interrupt
            await self._pending.put(msg)
            self._interrupt.set()

    async def cancel(self) -> None:
        """Cancel the current think loop without injecting a new message."""
        if self._loop_task is not None and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._state = PrimeState.IDLE
            self._emit_prime("prime/done", {})

    async def new_context(self, seed_message: str | None = None) -> None:
        """Start a new Prime context while keeping prior transcript in history.

        This preserves only the system prompt in the active in-memory context and
        optionally injects a first user message to kick off a fresh turn.
        """
        # Stop ongoing work before resetting context.
        await self.cancel()
        await self._ensure_initialized()

        # Close durable streams for the old context; new streams will be
        # created lazily on the next _think_loop iteration.
        await self._close_streams()

        # Reset to empty — system prompt will be freshly rebuilt below.
        self._messages = []
        self._system_prompt_built = False

        # Clear queued pending user messages from the previous context.
        while True:
            try:
                self._pending.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._interrupt.clear()

        # Rebuild the system prompt now so it's current.
        if self._tool_schemas is not None:
            tool_names = [t["function"]["name"] for t in self._tool_schemas]
            await self._build_system_prompt(tool_names)

        # Persist a context boundary marker so startup restore can recover the
        # latest context only.
        await self._persist_message(
            {"role": "system", "content": _CONTEXT_BOUNDARY_MARKER}
        )

        if seed_message:
            await self.send_message(seed_message, role="user")

    def get_history(self) -> list[dict[str, Any]]:
        """Return the full conversation history (for prime/history RPC)."""
        # Filter out system messages for the external view
        return [m for m in self._messages if m.get("role") != "system"]

    # ── Loop management ────────────────────────────────────────────────────────

    def _start_loop(self) -> None:
        """Start the think→tool→observe loop as a background task."""
        self._loop_task = asyncio.create_task(self._run_loop(), name="prime-think-loop")
        self._loop_task.add_done_callback(self._on_loop_done)

    def _on_loop_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Prime loop failed: %s", exc, exc_info=exc)

    async def _run_loop(self) -> None:
        """Main loop: think → tool → observe, with interrupt checks."""
        try:
            await self._ensure_initialized()
            await self._think_loop()
        except asyncio.CancelledError:
            logger.info("Prime loop cancelled")
            raise
        except Exception as exc:
            logger.error("Prime loop error: %s", exc, exc_info=True)
            self._emit_prime(
                "prime/token", {"text": f"Sorry, I couldn't respond right now: {exc}"}
            )
        finally:
            self._state = PrimeState.IDLE
            self._emit_prime("prime/done", {})

    async def _think_loop(self) -> None:
        """Core think→tool→observe loop with interrupt-and-pivot."""
        llm, model = self._resolve_llm()
        # Ensure durable streams exist for Prime
        await self._ensure_streams()

        for _turn in range(self._max_turns):
            # ── Check for interrupts before thinking ───────────────────
            if self._drain_pending():
                # New messages were injected — just continue the loop
                # so the LLM sees them in context
                pass

            # ── Think ──────────────────────────────────────────────────
            self._state = PrimeState.THINKING
            self._emit_prime("prime/stateChanged", {"state": "thinking"})

            self._maybe_compact()

            try:
                result = await llm.create_turn(
                    self._sanitize_messages_for_api(),
                    model,
                    tools=self._tool_schemas or None,
                )
            except Exception as exc:
                logger.error("Prime LLM call failed: %s", exc, exc_info=True)
                self._emit_prime(
                    "prime/token",
                    {"text": f"Sorry, I couldn't respond right now: {exc}"},
                )
                break

            # ── Stream assistant text ──────────────────────────────────
            text = result.text or ""
            if text:
                self._emit_prime("prime/token", {"text": text})
                # Also append to durable token stream for replay
                asyncio.create_task(self._append_token_to_stream(text))

            # Build assistant message for history
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": text}
            if result.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.call_id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in result.tool_calls
                ]
            self._messages.append(assistant_msg)
            await self._persist_message(assistant_msg)

            # No tool calls → done
            if not result.tool_calls:
                break

            # ── Execute tools (with interrupt checks between each) ─────
            self._state = PrimeState.TOOL_EXECUTION
            self._emit_prime("prime/stateChanged", {"state": "tool_execution"})

            for tc in result.tool_calls:
                # Check for interrupt before each tool
                if self._interrupt.is_set():
                    self._drain_pending()
                    self._emit_prime(
                        "prime/interrupted",
                        {
                            "reason": "new_message",
                        },
                    )
                    break  # Break out of tool loop, re-enter think

                # Execute the tool
                self._emit_prime(
                    "prime/toolCall",
                    {
                        "call_id": tc.call_id,
                        "tool_name": tc.name,
                        "arguments": tc.arguments,
                    },
                )
                # Append tool call to durable stream
                asyncio.create_task(
                    self._append_to_stream(
                        "tool_call",
                        {
                            "call_id": tc.call_id,
                            "tool_name": tc.name,
                            "arguments": tc.arguments,
                        },
                    )
                )

                started = time.perf_counter()
                tool_output, tool_error = await self._execute_tool(tc)
                duration_ms = int((time.perf_counter() - started) * 1000)

                self._emit_prime(
                    "prime/toolResult",
                    {
                        "call_id": tc.call_id,
                        "output": tool_output if not tool_error else None,
                        "error": tool_error,
                        "duration_ms": duration_ms,
                    },
                )
                # Append tool result to durable stream
                asyncio.create_task(
                    self._append_to_stream(
                        "tool_result",
                        {
                            "call_id": tc.call_id,
                            "output": tool_output if not tool_error else None,
                            "error": tool_error,
                            "duration_ms": duration_ms,
                        },
                    )
                )

                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc.call_id,
                    "content": tool_output,
                    "name": tc.name,
                }
                self._messages.append(tool_msg)
                await self._persist_message(
                    tool_msg,
                    metadata={
                        "tool_name": tc.name,
                        "arguments": tc.arguments,
                    },
                )
            else:
                # All tools completed without interrupt — continue think loop
                continue

            # If we broke out of the tool loop (interrupt), continue thinking
            # with the new messages already in context
            continue

        else:
            logger.warning("Prime hit max_turns=%s", self._max_turns)

    # ── Interrupt handling ─────────────────────────────────────────────────────

    def _drain_pending(self) -> bool:
        """Drain all pending messages into _messages. Returns True if any were drained."""
        drained = False
        while True:
            try:
                msg = self._pending.get_nowait()
                self._messages.append(msg)
                asyncio.create_task(self._persist_message(msg))
                drained = True
            except asyncio.QueueEmpty:
                break
        if drained:
            self._interrupt.clear()
        return drained

    # ── Tool execution ─────────────────────────────────────────────────────────

    async def _execute_tool(self, tool_call: Any) -> tuple[str, str | None]:
        """Execute a single tool call. Returns (output, error_or_none)."""
        try:
            tool = self._registry.get(tool_call.name)
            result = await tool.execute(tool_call.arguments, self._tool_context)
            return result.content, None
        except Exception as exc:
            return f"Tool error: {exc}", str(exc)

    # ── History persistence ───────────────────────────────────────────────────────

    async def _persist_message(
        self,
        msg: dict[str, Any],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist a single message to HistoryDB (best-effort)."""
        if self._history_db is None:
            return
        metadata_payload = metadata
        if metadata_payload is None and isinstance(msg.get("metadata"), dict):
            metadata_payload = msg.get("metadata")
        if metadata_payload is None and isinstance(msg.get("tool_calls"), list):
            metadata_payload = {"tool_calls": msg["tool_calls"]}
        role = str(msg.get("role", "user"))
        if role == "tool" and not msg.get("name"):
            logger.warning(
                "Persisting tool message without name call_id=%s",
                msg.get("tool_call_id"),
            )
        try:
            await self._history_db.record_message(
                agent_id=self.AGENT_ID,
                role=role,
                content=msg.get("content"),
                tool_call_id=msg.get("tool_call_id"),
                name=msg.get("name"),
                metadata=metadata_payload
                if isinstance(metadata_payload, dict)
                else None,
            )
        except Exception:
            logger.warning("Failed to persist Prime message", exc_info=True)

    async def get_history_page(
        self,
        *,
        before_seq: int | None = None,
        limit: int = _DEFAULT_HISTORY_PAGE_SIZE,
        full: bool = False,
    ) -> dict[str, Any]:
        """Return paginated Prime history for UI consumption.

        Args:
            before_seq: Cursor for older messages (`seq < before_seq`).
            limit: Maximum messages to return.
            full: When true, include context boundary dividers and all sessions.
                When false, returns the current in-memory context (legacy behavior).
        """
        safe_limit = max(1, min(limit, 200))

        # Legacy behavior: current context only from in-memory history.
        if not full or self._history_db is None:
            filtered = self.get_history()
            page = filtered[-safe_limit:]
            return {
                "messages": page,
                "has_more": len(filtered) > len(page),
                "oldest_seq": None,
            }

        await self._ensure_history_session()
        rows = await self._history_db.get_messages_page(
            self.AGENT_ID,
            before_seq=before_seq,
            limit=safe_limit + 1,
        )
        has_more = len(rows) > safe_limit
        if has_more:
            rows = rows[1:]

        messages: list[dict[str, Any]] = []
        for row in rows:
            item = self._history_row_to_public_message(row, include_boundaries=True)
            if item is not None:
                messages.append(item)

        oldest_seq = messages[0].get("seq") if messages else None
        return {
            "messages": messages,
            "has_more": has_more,
            "oldest_seq": oldest_seq,
        }

    def _history_row_to_public_message(
        self,
        row: dict[str, Any],
        *,
        include_boundaries: bool,
    ) -> dict[str, Any] | None:
        role = str(row.get("role") or "user")
        content = str(row.get("content") or "")
        seq = row.get("seq")

        if role == "system":
            if include_boundaries and content == _CONTEXT_BOUNDARY_MARKER:
                return {
                    "role": "divider",
                    "content": "New context",
                    "seq": seq,
                }
            return None

        parsed_metadata: dict[str, Any] | None = None
        metadata_raw = row.get("metadata")
        if isinstance(metadata_raw, str) and metadata_raw:
            try:
                parsed = json.loads(metadata_raw)
                if isinstance(parsed, dict):
                    parsed_metadata = parsed
            except json.JSONDecodeError:
                parsed_metadata = None
        elif isinstance(metadata_raw, dict):
            parsed_metadata = metadata_raw

        msg: dict[str, Any] = {
            "role": role,
            "content": content,
            "seq": seq,
        }
        tool_call_id = row.get("tool_call_id")
        if tool_call_id:
            msg["tool_call_id"] = tool_call_id
        name = row.get("name")
        if name:
            msg["name"] = name
        if parsed_metadata is not None:
            msg["metadata"] = parsed_metadata
        return msg

    async def _ensure_history_session(self) -> None:
        """Ensure the Prime session exists in HistoryDB and load prior messages."""
        if self._history_db is None or self._history_initialized:
            return
        self._history_initialized = True

        try:
            # Create the session record (idempotent — INSERT OR IGNORE)
            await self._history_db.record_session(
                agent_id=self.AGENT_ID,
                workspace=str(self._workspace),
                spec_ref="prime",
                task="Prime assistant",
                display_name="Prime",
                agent_type="prime",
            )

            # Load any prior messages from a previous server session
            if hasattr(self._history_db, "get_messages_page"):
                rows = await self._history_db.get_messages_page(
                    self.AGENT_ID,
                    before_seq=None,
                    limit=500,
                )
            else:
                rows = await self._history_db.get_messages(self.AGENT_ID)
            if rows and not self._messages:
                for row in rows:
                    role = (
                        row.get("role", "user")
                        if isinstance(row, dict)
                        else row["role"]
                    )
                    content = (
                        row.get("content") if isinstance(row, dict) else row["content"]
                    )
                    tool_call_id = (
                        row.get("tool_call_id")
                        if isinstance(row, dict)
                        else row["tool_call_id"]
                    )
                    metadata_raw = (
                        row.get("metadata")
                        if isinstance(row, dict)
                        else row["metadata"]
                    )
                    if role == "system" and content == _CONTEXT_BOUNDARY_MARKER:
                        # Keep only messages after the latest boundary marker.
                        self._messages = []
                        continue
                    msg: dict[str, Any] = {"role": role, "content": content or ""}
                    if tool_call_id:
                        msg["tool_call_id"] = tool_call_id
                    if isinstance(metadata_raw, str) and metadata_raw:
                        try:
                            parsed = json.loads(metadata_raw)
                            if isinstance(parsed, dict):
                                if isinstance(parsed.get("tool_calls"), list):
                                    msg["tool_calls"] = parsed["tool_calls"]
                                if isinstance(parsed.get("tool_name"), str):
                                    msg["name"] = parsed["tool_name"]
                                msg["metadata"] = parsed
                        except json.JSONDecodeError:
                            pass
                    # Skip system messages — they'll be rebuilt
                    if role != "system":
                        self._messages.append(msg)
                if self._messages:
                    logger.info(
                        "Prime restored %d messages from history", len(self._messages)
                    )
        except Exception:
            logger.debug("Failed to load Prime history", exc_info=True)

    # ── Initialization ─────────────────────────────────────────────────────────

    async def _ensure_initialized(self) -> None:
        """Build tool registry, system prompt, etc. on first use."""
        if self._registry is not None and self._system_prompt_built:
            return
        # Load history from DB before anything else
        await self._ensure_history_session()
        from taui.tools.registry import ToolRegistry
        from taui.tools.base import ToolContext
        from taui.tools.builtins import register_builtin_tools
        from taui.tools.builtins.spec_tree import register_spec_tree_tools
        from taui.config.policies import Policy
        from taui.config.settings import BashPolicySettings

        registry = ToolRegistry()
        register_builtin_tools(registry)
        register_spec_tree_tools(registry)

        # Remove "task" — Prime uses launch_sub_agent/launch_root instead
        try:
            registry.unregister("task")
        except ValueError:
            pass

        self._registry = registry
        self._tool_schemas = registry.list_schemas()

        tool_names = [t["function"]["name"] for t in self._tool_schemas]

        auto_approve = {
            "spec_get_tree",
            "spec_get_node",
            "spec_get_branch",
            "spec_create_node",
            "spec_create_sibling",
            "spec_update_node",
            "spec_move_node",
            "read",
            "glob",
            "grep",
            "find",
            "codesearch",
            "bash",
            "git",
            "lsp",
            "plan",
            "todowrite",
            "question",
            "skill",
            "monty",
            "launch_sub_agent",
            "launch_root",
        }
        self._policy = Policy(
            auto_approve=auto_approve,
            confirm={
                "spec_delete_node",
                "write",
                "edit",
                "apply_patch",
                "multiedit",
                "skill_import",
            },
            deny=set(),
            bash=BashPolicySettings(default_timeout_sec=60),
        )

        llm, model = self._resolve_llm()
        self._session = _PrimeSession(
            self._spec_service,
            agent_manager=self._agent_manager,
            notification_callback=self._emit,
            llm=llm,
            model=model,
            tool_registry=registry,
        )

        self._tool_context = ToolContext(
            working_dir=self._workspace,
            session=self._session,
            policy=self._policy,
        )

        # Build system prompt (only once, or refresh if spec tree changes)
        if not self._system_prompt_built:
            await self._build_system_prompt(tool_names)

    async def _build_system_prompt(self, tool_names: list[str]) -> None:
        """Build the system prompt and prepend it to message history."""
        prompt_template = get_prompt_template_for_workspace(
            "prime", workspace=self._workspace
        )
        context_parts: list[str] = []

        if prompt_template:
            context_parts.append(
                render_prompt_template(
                    prompt_template,
                    {
                        "workspace": str(self._workspace),
                        "available_tools": ", ".join(tool_names),
                    },
                )
            )
        else:
            context_parts.append(
                "You are Prime, the user's main AI assistant in Taui — "
                "a spec-driven development environment.\n\n"
                "## Your Role\n"
                "You are a conversationalist and dispatcher. You talk directly "
                "with the user, help them think, answer questions, and coordinate work.\n\n"
                "## Delegation Strategy\n"
                "You MUST delegate actual work to agents:\n"
                "- Use 'launch_root' for BIG tasks: implementing features, "
                "refactoring code, writing tests, creating files. Root agents run "
                "in the background as separate tabs. You stay free for the user.\n"
                "- Use 'launch_sub_agent' for QUICK lookups: reading files, searching "
                "code, checking status, answering factual questions. Sub-agents block "
                "until done and return their result to you.\n\n"
                "## Multi-Topic Conversations\n"
                "The user may talk about multiple topics at once. Track each topic "
                "naturally. When the user switches topics mid-conversation, acknowledge "
                "it and continue. You have full conversation history.\n\n"
                "## Important Rules\n"
                "- NEVER do heavy work yourself when you can delegate.\n"
                "- Stay responsive. Prefer launching agents over doing multi-step "
                "tool chains yourself.\n"
                "- When the user asks about something while you're working, pivot "
                "to their new question immediately.\n"
                "- For simple questions (no file reading needed), just answer directly.\n"
                "- When a root agent reports back, summarize the result to the user.\n\n"
                "## Critical: Act, Don't Narrate\n"
                "When you decide to use a tool, CALL IT in the same response. "
                "Never respond with only text describing what you plan to do — "
                "that ends your turn without taking action.\n\n"
                "BAD (text-only, no tool call):\n"
                '  "Let me check the authentication spec first."\n\n'
                "GOOD (tool call in the same response):\n"
                "  Calls launch_sub_agent or launch_root immediately.\n\n"
                "If the user asks you to launch an agent, call launch_root or "
                "launch_sub_agent right now. Do not say 'let me check first' and stop. "
                "Every response that describes an action without performing it is a failure.\n\n"
                "Available tools: " + ", ".join(tool_names) + "\n\n"
                "Be concise and helpful."
            )
            context_parts.append(f"\nWorkspace: {self._workspace}")

        # Inject spec tree outline
        try:
            await self._spec_service.ensure_initialized()
            nodes = await self._spec_service.get_tree()
            if nodes:
                lines: list[str] = []
                for n in nodes:
                    indent = "  " * n.depth
                    title = (
                        n.markdown.split("\n")[0].lstrip("# ").strip()
                        if n.markdown
                        else n.anchor
                    )
                    lines.append(f"{indent}- {n.spec_ref}: {title}")
                context_parts.append("\n\n## Project Spec Tree\n" + "\n".join(lines))
        except Exception:
            pass

        self._messages.insert(
            0,
            {
                "role": "system",
                "content": "\n".join(context_parts),
            },
        )
        self._system_prompt_built = True

    # ── API message sanitisation ──────────────────────────────────────────────

    def _sanitize_messages_for_api(self) -> list[dict[str, Any]]:
        """Return a clean copy of _messages suitable for the OpenAI chat API.

        The in-memory list may contain extra keys (``metadata``, ``seq``) added
        by history restoration that the API does not accept.  Sending unknown
        keys can cause some API implementations to silently refuse tool use.

        This method also repairs tool_call / tool_result pairing issues that
        arise when history is partially restored after a server restart:

        * Every ``assistant`` message that declares ``tool_calls`` must be
          followed by exactly one ``tool`` message per call_id.  Orphaned
          assistant tool_calls or orphaned tool results are dropped so the
          API always receives a consistent pairing.
        * ``content`` on an assistant message that only contains tool_calls
          is set to ``None`` (not ``""``) per the OpenAI spec.
        """
        _API_KEYS = {
            # role is always present
            "role",
            # text content
            "content",
            # assistant → tool_calls list
            "tool_calls",
            # tool result message fields
            "tool_call_id",
            "name",
        }

        # ── Pass 1: strip non-API keys and normalise content ──────────────
        clean: list[dict[str, Any]] = []
        for msg in self._messages:
            role = msg.get("role", "user")
            stripped: dict[str, Any] = {k: v for k, v in msg.items() if k in _API_KEYS}
            # For assistant messages with tool_calls, null-out empty content
            if role == "assistant" and stripped.get("tool_calls"):
                if not stripped.get("content"):
                    stripped["content"] = None
            clean.append(stripped)

        # ── Pass 2: validate tool_call / tool_result pairing ──────────────
        # Collect the set of call_ids that have a matching tool-result message.
        result_ids: set[str] = set()
        for msg in clean:
            if msg.get("role") == "tool":
                cid = msg.get("tool_call_id")
                if cid:
                    result_ids.add(str(cid))

        # Drop tool_calls entries in assistant messages that have no result,
        # and drop tool-result messages that reference no assistant tool_call.
        # We walk the list in order and build the final output.
        declared_ids: set[str] = set()  # call_ids declared by assistant messages
        output: list[dict[str, Any]] = []
        for msg in clean:
            role = msg.get("role", "user")
            if role == "assistant" and msg.get("tool_calls"):
                # Keep only calls that have a matching result
                valid_calls = [
                    tc
                    for tc in msg["tool_calls"]
                    if isinstance(tc, dict) and str(tc.get("id", "")) in result_ids
                ]
                if valid_calls:
                    msg = dict(msg)
                    msg["tool_calls"] = valid_calls
                    for tc in valid_calls:
                        declared_ids.add(str(tc.get("id", "")))
                else:
                    # All calls are orphaned — drop tool_calls entirely
                    msg = {k: v for k, v in msg.items() if k != "tool_calls"}
                    if not msg.get("content"):
                        # Nothing left of value; skip the message entirely
                        continue
            elif role == "tool":
                cid = str(msg.get("tool_call_id", ""))
                if cid not in declared_ids:
                    # Orphaned result — skip
                    continue
            output.append(msg)

        return output

    # ── Auto-compaction ────────────────────────────────────────────────────────

    def _maybe_compact(self) -> None:
        """Drop oldest non-essential messages when approaching token budget."""
        est_tokens = sum(len(m.get("content") or "") // 4 for m in self._messages)
        soft_limit = int(_MAX_INPUT_TOKENS * _COMPACTION_SOFT_RATIO)

        if est_tokens <= soft_limit:
            return

        removed = 0
        while est_tokens > soft_limit and len(self._messages) > 4:
            # Find oldest droppable (skip system at 0, last 3)
            drop_idx: int | None = None
            for i in range(1, len(self._messages) - 3):
                if self._messages[i].get("role") != "system":
                    drop_idx = i
                    break
            if drop_idx is None:
                break
            est_tokens -= len(self._messages[drop_idx].get("content") or "") // 4
            del self._messages[drop_idx]
            removed += 1

        if removed > 0:
            logger.info("Prime auto-compacted %d messages", removed)

    # ── Durable stream helpers ──────────────────────────────────────────────

    async def _ensure_streams(self) -> None:
        """Create durable streams for Prime events and tokens if not yet created."""
        if self._stream_initialized or self._stream_client is None:
            return
        try:
            await self._stream_client.ensure_stream(self._stream_id)
            await self._stream_client.ensure_stream(self._token_stream_id)
            self._stream_initialized = True
        except Exception:
            logger.warning("Failed to create Prime durable streams", exc_info=True)

    async def _close_streams(self) -> None:
        """Close durable streams for Prime (called on new_context / shutdown)."""
        if self._stream_client is None:
            return
        for sid in (self._stream_id, self._token_stream_id):
            try:
                await self._stream_client.close_stream(sid)
            except Exception:
                logger.debug("Failed to close Prime stream %s", sid, exc_info=True)
        self._stream_initialized = False

    async def _append_to_stream(self, event_type: str, payload: dict[str, Any]) -> None:
        """Append an event to the Prime event stream (best-effort)."""
        if self._stream_client is None:
            return
        try:
            await self._stream_client.append_event(self._stream_id, event_type, payload)
        except Exception:
            logger.warning(
                "Failed to append to Prime stream event_type=%s",
                event_type,
                exc_info=True,
            )

    async def _append_token_to_stream(self, text: str) -> None:
        """Append a token chunk to the Prime token stream (best-effort)."""
        if self._stream_client is None:
            return
        try:
            await self._stream_client.append_event(
                self._token_stream_id, "token", {"text": text}
            )
        except Exception:
            logger.warning("Failed to append token to Prime stream", exc_info=True)

    # ── Notification helper ────────────────────────────────────────────────────

    def _emit_prime(self, method: str, params: dict[str, Any]) -> None:
        """Emit a notification via the server's notification callback."""
        from taui.server.protocol import notification_message

        self._emit(notification_message(method, params))


class _PrimeSession:
    """Session object injected into ToolContext so tools can reach services."""

    def __init__(
        self,
        spec_service: Any,
        *,
        agent_manager: Any = None,
        notification_callback: Any = None,
        llm: Any = None,
        model: str = "",
        tool_registry: Any = None,
    ) -> None:
        self.spec_service = spec_service
        self.agent_runner = None
        self.agent_manager = agent_manager
        self.notification_callback = notification_callback
        self.llm = llm
        self.model = model
        self.tool_registry = tool_registry
        self._read_files: dict[str, str] = {}

    def mark_read(self, path: Any, *, status: str = "success") -> None:
        self._read_files[str(path)] = status

    def has_read(self, path: Any) -> bool:
        return str(path) in self._read_files

    def read_status(self, path: Any) -> str | None:
        return self._read_files.get(str(path))
