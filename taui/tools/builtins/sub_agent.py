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
from taui.tools.registry import ToolRegistry


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
    guidelines: str = (
        "Use `sub_agent` for focused tasks like researching a topic, "
        "analyzing a section of code, or exploring alternatives. "
        "Keep the task description clear and specific. "
        "The sub-agent cannot see the parent's conversation history."
    )
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    # Injected by Session.create()
    _llm: Any = None
    _stream: Any = None
    _parent_executor: Any = None
    _model: str = "default"
    _system_prompt: str = ""

    # Callbacks forwarded from the parent loop for TUI visibility
    _on_tool_call: Callable[[str, str, dict], Awaitable[None]] | None = None
    _on_tool_result: Callable[[str, str, str, bool], Awaitable[None]] | None = None

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

        if self._llm is None or self._parent_executor is None:
            return ToolResult.fail("Sub-agent not configured. Missing LLM or executor.")

        # Resolve tool subset
        parent_registry = self._parent_executor.registry
        requested_tools = arguments.get("tools")
        default_tools = ["read", "glob", "grep", "bash"]

        if requested_tools and isinstance(requested_tools, list):
            tool_names = [t for t in requested_tools if t in parent_registry]
        else:
            tool_names = [t for t in default_tools if t in parent_registry]

        # Never give sub-agent the sub_agent tool (no recursion)
        tool_names = [t for t in tool_names if t != "sub_agent"]

        if tool_names:
            child_registry = parent_registry.subset(tool_names)
        else:
            child_registry = ToolRegistry()

        max_turns = min(arguments.get("max_turns", 10), 25)

        # Import here to avoid circular dependency
        from taui.agent.loop import AgentLoop
        from taui.tools.executor import ToolExecutor, ToolPolicy

        child_executor = ToolExecutor(registry=child_registry, policy=ToolPolicy())
        child_loop = AgentLoop(
            llm=self._llm,
            executor=child_executor,
            stream=self._stream,
            system_prompt=self._system_prompt or (
                "You are a focused research agent. Complete the given task "
                "concisely and return your findings. You have a limited turn budget, "
                "so be efficient."
            ),
            model=self._model,
            max_turns=max_turns,
        )

        # Forward tool call/result callbacks so sub-agent activity is visible in TUI
        if self._on_tool_call is not None:
            child_loop._on_tool_call = self._on_tool_call
        if self._on_tool_result is not None:
            child_loop._on_tool_result = self._on_tool_result

        try:
            result = await child_loop.run(task)
            return ToolResult.ok(
                result.text,
                turns=result.turns,
                state=result.state.value,
            )
        except Exception as exc:
            return ToolResult.fail(f"Sub-agent failed: {exc}")
