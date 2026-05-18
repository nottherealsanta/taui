"""Sub-agent tool — spawn a scoped child agent for focused tasks.

The parent agent can delegate work to a sub-agent with a restricted
tool set and its own conversation context. The sub-agent runs to
completion and returns its final text response.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from taui.tools.base import ToolCategory, ToolResult


@dataclass
class SubAgentTool:
    """Spawn a child agent to handle a focused sub-task.

    The child gets its own conversation, a scoped subset of tools,
    a separate turn budget, and a fresh system prompt. It shares the
    parent's LLM provider and event store.
    """

    name: str = "sub_agent"
    description: str = (
        "Delegate a focused sub-task to a child agent. The child agent "
        "has its own conversation and a limited set of tools. It runs to "
        "completion and returns its final response. Use for research, "
        "code analysis, or any task that benefits from a fresh context."
    )
    category: ToolCategory = ToolCategory.AGENT
    # Sub-agents run their own multi-turn loop bounded by `max_turns`; the
    # executor's default 120s wall-clock timeout would kill legitimately
    # long research tasks. The parent worker's cancellation still propagates
    # through `await sub.send(task)` if the user hits Escape / Ctrl+C.
    timeout: float | None = None
    guidelines: str = (
        "Use `sub_agent` for focused tasks like researching a topic, "
        "analyzing a section of code, or exploring alternatives. "
        "Keep the task description clear and specific. "
        "The sub-agent cannot see the parent's conversation history."
    )
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    # Injected by Session.create() — preferred path
    _session: Any = None
    _model: str = "default"

    # Legacy fallback — direct LLM/executor injection (for tests)
    _llm: Any = None
    _stream: Any = None
    _parent_executor: Any = None
    _system_prompt: str = ""

    # UI hooks — let the parent harness surface progress on the sub_agent
    # tool row. `_on_text` fires once per turn with the full assistant
    # text; `_on_text_delta` fires per streaming chunk for real-time updates.
    _on_text: Callable[[str], Awaitable[None]] | None = None
    _on_text_delta: Callable[[str], None] | None = None
    # Single-shot progress callback fired with a short status string each
    # time the sub-agent does something visible (streams text, starts a
    # tool). Set by the parent app so the TUI's '└' progress line stays
    # up to date even when the sub-agent isn't streaming any text.
    _on_progress: Callable[[str], None] | None = None

    def __post_init__(self):
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": (
                            "Clear description of the sub-task to perform. "
                            "Be specific about what output is expected."
                        ),
                    },
                    "tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Tool names the sub-agent can use. "
                            "Defaults to read-only tools: read, glob, grep, bash."
                        ),
                    },
                    "max_turns": {
                        "type": "integer",
                        "description": "Max turns for the sub-agent. Default: 10.",
                    },
                },
                "required": ["task"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        task = arguments.get("task")
        if not isinstance(task, str) or not task.strip():
            return ToolResult.fail("'task' must be a non-empty string.")

        if self._session is None and self._llm is None:
            return ToolResult.fail(
                "Sub-agent not configured. No parent session."
            )

        # Resolve tool subset
        requested_tools = arguments.get("tools")
        default_tools = ["read", "glob", "grep", "bash"]
        tool_names: list[str] | None

        if requested_tools and isinstance(requested_tools, list):
            tool_names = [t for t in requested_tools if t != "sub_agent"]
        else:
            tool_names = [t for t in default_tools]

        max_turns = min(arguments.get("max_turns", 10), 25)

        # Preferred path: use Session.create_sub_session()
        if self._session is not None:
            try:
                sub = await self._session.create_sub_session(
                    tools=tool_names or None,
                    system_prompt=(
                        "You are a focused research agent. "
                        "Complete the given task concisely and "
                        "return your findings."
                    ),
                    model=self._model or None,
                    max_turns=max_turns,
                )
                if self._on_text is not None:
                    sub._loop._on_text = self._on_text
                if self._on_text_delta is not None:
                    sub._loop._on_text_delta = self._on_text_delta
                if self._on_progress is not None:
                    progress_cb = self._on_progress
                    buf: list[str] = [""]

                    async def _on_text_progress(text: str) -> None:
                        buf[0] = ""
                        progress_cb(text)

                    def _on_delta_progress(fragment: str) -> None:
                        buf[0] += fragment
                        progress_cb(buf[0])

                    async def _on_tool_call_progress(
                        _cid: str, name: str, args: dict
                    ) -> None:
                        snippet = ""
                        if args:
                            snippet = " ".join(
                                f"{k}={str(v)[:30]}" for k, v in args.items()
                            )
                        progress_cb(f"{name}  {snippet}".strip())

                    sub._loop._on_text = _on_text_progress
                    sub._loop._on_text_delta = _on_delta_progress
                    sub._loop._on_tool_call = _on_tool_call_progress
                    progress_cb("starting…")
                result = await sub.send(task)
                return ToolResult.ok(
                    result.text,
                    turns=result.turns,
                    state=result.state.value,
                )
            except Exception as exc:
                return ToolResult.fail(f"Sub-agent failed: {exc}")

        # Legacy fallback: direct AgentLoop construction
        return await self._execute_legacy(
            task, tool_names, max_turns
        )

    async def _execute_legacy(
        self,
        task: str,
        tool_names: list[str] | None,
        max_turns: int,
    ) -> ToolResult:
        """Fallback execution using direct LLM/executor injection."""
        from taui.agent.loop import AgentLoop
        from taui.tools.executor import ToolExecutor, ToolPolicy
        from taui.tools.registry import ToolRegistry

        parent_registry = self._parent_executor.registry
        names = tool_names or []
        names = [t for t in names if t in parent_registry]
        names = [t for t in names if t != "sub_agent"]

        if names:
            child_registry = parent_registry.subset(names)
        else:
            child_registry = ToolRegistry()

        child_executor = ToolExecutor(
            registry=child_registry, policy=ToolPolicy()
        )
        child_loop = AgentLoop(
            llm=self._llm,
            executor=child_executor,
            stream=self._stream,
            system_prompt=self._system_prompt or (
                "You are a focused research agent. Complete "
                "the given task concisely."
            ),
            model=self._model,
            max_turns=max_turns,
        )

        try:
            result = await child_loop.run(task)
            return ToolResult.ok(
                result.text,
                turns=result.turns,
                state=result.state.value,
            )
        except Exception as exc:
            return ToolResult.fail(f"Sub-agent failed: {exc}")
