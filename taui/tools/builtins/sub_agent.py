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
        "When a task matches a predefined profile, spawn it with "
        "`agent_id` (see the sub_agent tool's agent_id options) instead of an "
        "ad-hoc sub-agent — e.g. EXP for read-only code exploration. "
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

    # UI callbacks — wired by the TUI (see TauiApp._wire_loop_callbacks).
    # Forwarded onto the child loop so its tool calls surface in the parent's
    # ToolController, driving the sub-agent widget's live activity log. Without
    # these the widget never receives any inner-tool events and sits at
    # "starting…" until the final result arrives.
    _on_tool_call: Any = None
    _on_tool_result: Any = None
    _on_tool_delta: Any = None
    # Child assistant text (async, per turn) and reasoning fragments (sync,
    # streaming). Routed to the sub-agent widget so its status line can reflect
    # the latest tool, reasoning, or LLM text — not just tool calls.
    _on_child_text: Any = None
    _on_child_reasoning: Any = None

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
                        "description": (
                            "Max turns for the sub-agent. Defaults to the "
                            "configured sub_agent_max_turns (25). Capped at 25."
                        ),
                    },
                },
                "required": ["task"],
            }

    def refresh_agent_catalog(self) -> None:
        """Advertise the currently spawnable agent profiles in the schema.

        The model only sees what's in the tool schema, so without this the
        ``agent_id`` field is just an opaque optional string and profiles like
        EXP never get used. This enumerates the spawnable profiles (id, name,
        one-line description) and constrains ``agent_id`` to them via ``enum``.
        Called once the parent session is wired (see ``_configure_sub_agents``)
        and again on extension reload, so newly added profiles show up too.
        """
        if self._session is None:
            return
        try:
            from taui.self_edit.store import SelfEditStore

            profiles = SelfEditStore(
                self._session.config.working_dir
            ).load_agents()
        except Exception:
            return

        spawnable = sorted(
            (p for p in profiles.values() if p.spawnable_as_sub),
            key=lambda p: p.id,
        )
        prop = self.schema["properties"]["agent_id"]
        if not spawnable:
            prop.pop("enum", None)
            return

        lines = []
        for p in spawnable:
            summary = (p.prompt or "").strip().splitlines()
            summary = summary[0].strip() if summary else (p.name or p.id)
            if len(summary) > 140:
                summary = summary[:140] + "…"
            lines.append(f"- {p.id} ({p.name}): {summary}")
        prop["description"] = (
            "Optional ID of a predefined agent profile to spawn. When a task "
            "fits one of these, prefer it over an ad-hoc sub-agent — the "
            "profile brings a tuned system prompt, tool set, and model. "
            "Available profiles:\n" + "\n".join(lines)
        )
        prop["enum"] = [p.id for p in spawnable]

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

        # Default turn budget comes from config (sub_agent_max_turns, default
        # 25); an explicit `max_turns` argument overrides it. Hard cap at 25.
        default_max_turns = 25
        if self._session is not None:
            default_max_turns = getattr(
                self._session.config, "sub_agent_max_turns", 25
            )
        max_turns = min(arguments.get("max_turns", default_max_turns), 25)

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
                self._forward_callbacks(sub)
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

    def _forward_callbacks(self, sub: Any) -> None:
        """Forward the parent's tool-event callbacks onto a sub-session's loop.

        The TUI sets these on the SubAgentTool instance; the child loop is
        created fresh by ``create_sub_session`` with no callbacks, so we copy
        them across. This is what makes the sub-agent widget's activity log
        update live as the child calls tools, instead of jumping straight from
        "starting…" to the final result.
        """
        self._forward_callbacks_to_loop(getattr(sub, "_loop", None))

    def _forward_callbacks_to_loop(self, loop: Any) -> None:
        """Copy the parent's tool-event callbacks onto a child ``AgentLoop``."""
        if loop is None:
            return
        if self._on_tool_call is not None:
            loop._on_tool_call = self._on_tool_call
        if self._on_tool_result is not None:
            loop._on_tool_result = self._on_tool_result
        if self._on_tool_delta is not None:
            loop._on_tool_delta = self._on_tool_delta
        if self._on_child_text is not None:
            loop._on_text = self._on_child_text
        if self._on_child_reasoning is not None:
            loop._on_reasoning_delta = self._on_child_reasoning

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
        # Forward UI callbacks here too so the legacy path drives the live
        # activity log just like the preferred (session) path.
        self._forward_callbacks_to_loop(child_loop)

        try:
            result = await child_loop.run(task)
            return ToolResult.ok(
                result.text,
                turns=result.turns,
                state=result.state.value,
            )
        except Exception as exc:
            return ToolResult.fail(f"Sub-agent failed: {exc}")
