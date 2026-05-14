"""PLN tool — spawn a scoped planning agent.

The PLN agent is a built-in sub-agent specialised for producing
implementation plans. It runs read-only, returns a structured plan
as text, and never edits files itself.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from taui.tools.base import ToolCategory, ToolResult
from taui.tools.registry import ToolRegistry


PLN_SYSTEM_PROMPT = (
    "You are PLN, a planning agent. Your job is to investigate the "
    "task and produce a clear, actionable implementation plan. "
    "You do NOT write or edit code — only read, search, and reason.\n\n"
    "Output a plan with:\n"
    "1. Goal — one sentence restating what is being built.\n"
    "2. Key files — paths (with line numbers when useful) that will "
    "change or are load-bearing context.\n"
    "3. Steps — an ordered list of concrete edits or actions.\n"
    "4. Risks / open questions — anything ambiguous or worth confirming.\n\n"
    "Be specific. Prefer file_path:line_number references over prose. "
    "Stop as soon as the plan is solid — do not pad."
)


@dataclass
class PLNTool:
    """Spawn the PLN planning agent.

    PLN is a read-only child agent that investigates a task and returns
    a structured plan. It shares the parent's LLM provider and event
    store, but runs in its own conversation with a scoped, read-only
    tool subset.
    """

    name: str = "pln"
    description: str = (
        "Delegate planning to PLN, a built-in agent that investigates "
        "the task read-only and returns a structured implementation plan "
        "(goal, key files, ordered steps, risks). Use before any non-trivial "
        "change when you want an independent plan before editing."
    )
    category: ToolCategory = ToolCategory.AGENT
    guidelines: str = (
        "Use `pln` when the task is non-trivial and would benefit from "
        "an explicit plan before editing. PLN cannot write or edit files; "
        "it returns a plan as text. Pass a clear task description and any "
        "constraints the plan must honour."
    )
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    # Injected by Session.create()
    _llm: Any = None
    _stream: Any = None
    _parent_executor: Any = None
    _model: str = "default"

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
                            "What needs planning. Include the goal and any "
                            "constraints (files to touch, approaches to avoid, "
                            "deadlines, etc.)."
                        ),
                    },
                    "context": {
                        "type": "string",
                        "description": (
                            "Optional extra context PLN should treat as ground "
                            "truth (decisions already made, prior findings)."
                        ),
                    },
                    "max_turns": {
                        "type": "integer",
                        "description": "Max turns for PLN. Default: 10, cap: 25.",
                    },
                },
                "required": ["task"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        task = arguments.get("task")
        if not isinstance(task, str) or not task.strip():
            return ToolResult.fail("'task' must be a non-empty string.")

        if self._llm is None or self._parent_executor is None:
            return ToolResult.fail("PLN not configured. Missing LLM or executor.")

        # PLN is read-only: scope to read/search tools that exist in the parent.
        parent_registry = self._parent_executor.registry
        read_only_tools = ["read", "glob", "grep", "skills", "mcp"]
        tool_names = [t for t in read_only_tools if t in parent_registry]

        if tool_names:
            child_registry = parent_registry.subset(tool_names)
        else:
            child_registry = ToolRegistry()

        max_turns = min(arguments.get("max_turns", 10), 25)

        context = arguments.get("context")
        if isinstance(context, str) and context.strip():
            prompt = f"Context:\n{context.strip()}\n\nTask:\n{task.strip()}"
        else:
            prompt = task.strip()

        # Import here to avoid circular dependency
        from taui.agent.loop import AgentLoop
        from taui.tools.executor import ToolExecutor, ToolPolicy

        child_executor = ToolExecutor(registry=child_registry, policy=ToolPolicy())
        child_loop = AgentLoop(
            llm=self._llm,
            executor=child_executor,
            stream=self._stream,
            system_prompt=PLN_SYSTEM_PROMPT,
            model=self._model,
            max_turns=max_turns,
        )

        if self._on_tool_call is not None:
            child_loop._on_tool_call = self._on_tool_call
        if self._on_tool_result is not None:
            child_loop._on_tool_result = self._on_tool_result

        try:
            result = await child_loop.run(prompt)
            return ToolResult.ok(
                result.text,
                turns=result.turns,
                state=result.state.value,
            )
        except Exception as exc:
            return ToolResult.fail(f"PLN failed: {exc}")
