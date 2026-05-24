"""Sub-agent tool — spawn a scoped child agent for focused tasks.

The parent agent can delegate work to a sub-agent with a restricted
tool set and its own conversation context. The sub-agent runs to
completion and returns its final text response.
"""

from __future__ import annotations

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
                    "agent_id": {
                        "type": "string",
                        "description": (
                            "Optional 3-letter ID of an agent profile to "
                            "spawn (e.g. \"EXP\" for the code explorer). "
                            "When set, the profile's system prompt, allowed "
                            "tools, and model are used. `tools` overrides "
                            "the profile's tool list when both are given."
                        ),
                    },
                    "tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Tool names the sub-agent can use. "
                            "Defaults to read-only tools: read, glob, grep, bash. "
                            "Ignored when `agent_id` is set and this is not "
                            "provided."
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

        # Resolve agent profile (optional)
        profile = None
        agent_id_arg = arguments.get("agent_id")
        if isinstance(agent_id_arg, str) and agent_id_arg.strip():
            profile, err = self._resolve_profile(agent_id_arg.strip().upper())
            if err is not None:
                return ToolResult.fail(err)

        # Resolve tool subset: explicit `tools` wins, then profile's allowed_tools,
        # then defaults.
        requested_tools = arguments.get("tools")
        default_tools = ["read", "glob", "grep", "bash"]
        tool_names: list[str] | None

        if requested_tools and isinstance(requested_tools, list):
            tool_names = [t for t in requested_tools if t != "sub_agent"]
        elif profile is not None and profile.allowed_tools:
            tool_names = [t for t in profile.allowed_tools if t != "sub_agent"]
        else:
            tool_names = [t for t in default_tools]

        max_turns = min(arguments.get("max_turns", 10), 25)

        # System prompt: profile prompt wins over default
        if profile is not None and profile.prompt:
            system_prompt = profile.prompt
        else:
            system_prompt = (
                "You are a focused research agent. "
                "Complete the given task concisely and "
                "return your findings."
            )

        # Model: profile override wins, then live session model, then cached _model
        if profile and profile.model:
            model = profile.model
        elif self._session is not None:
            model = self._session.config.model
        else:
            model = self._model or None

        # Stable name for the sub-session (becomes the agent_id on the loop /
        # the stream id). When spawning a profile, prefix the ID so the
        # operator can tell at a glance which profile is running.
        from uuid import uuid4
        if profile is not None:
            sub_name = f"{profile.id.lower()}-{uuid4().hex[:6]}"
        else:
            sub_name = None

        # Preferred path: use Session.create_sub_session()
        if self._session is not None:
            try:
                sub = await self._session.create_sub_session(
                    name=sub_name,
                    tools=tool_names or None,
                    system_prompt=system_prompt,
                    model=model,
                    max_turns=max_turns,
                )
                result = await sub.send(task)
                return ToolResult.ok(
                    result.text,
                    turns=result.turns,
                    state=result.state.value,
                    agent_id=profile.id if profile else None,
                )
            except Exception as exc:
                return ToolResult.fail(f"Sub-agent failed: {exc}")

        # Legacy fallback: direct AgentLoop construction
        return await self._execute_legacy(
            task, tool_names, max_turns, system_prompt
        )

    def _resolve_profile(self, agent_id: str) -> tuple[Any, str | None]:
        """Look up an AgentProfile by ID via the parent session's working dir.

        Returns (profile, error_message). Profiles with `usage == "main"` are
        refused — they're meant for direct user control only.
        """
        if self._session is None:
            return None, (
                "Cannot resolve `agent_id`: sub-agent has no parent session."
            )
        try:
            from taui.self_edit.store import SelfEditStore

            working_dir = self._session.config.working_dir
            profiles = SelfEditStore(working_dir).load_agents()
        except Exception as exc:
            return None, f"Failed to load agent profiles: {exc}"
        profile = profiles.get(agent_id)
        if profile is None:
            spawnable = sorted(
                p.id for p in profiles.values() if p.spawnable_as_sub
            )
            available = ", ".join(spawnable) or "(none)"
            return None, (
                f"Unknown agent_id: {agent_id}. Spawnable: {available}"
            )
        if not profile.spawnable_as_sub:
            return None, (
                f"Agent {agent_id} is marked main-only "
                "(usage=\"main\") and cannot be spawned as a sub-agent."
            )
        return profile, None

    async def _execute_legacy(
        self,
        task: str,
        tool_names: list[str] | None,
        max_turns: int,
        system_prompt: str | None = None,
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
            system_prompt=system_prompt or self._system_prompt or (
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
