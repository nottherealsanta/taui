"""TaskTool — launch a sub-agent for a focused task."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from taui.tools.base import ToolCategory, ToolContext, ToolResult


def _agent_names() -> list[str]:
    from taui.agent.agents import AGENT_DEFINITIONS
    return sorted(AGENT_DEFINITIONS)


@dataclass(slots=True)
class TaskTool:
    name: str = "task"
    description: str = (
        "Launch a sub-agent to perform a focused task. The sub-agent runs "
        "autonomously and returns its result when finished.\n\n"
        "Parameters:\n"
        "  task (required): description of what the sub-agent should do\n"
        "  agent_type: type of agent to launch (explorer, planner, builder, general)\n"
        "  spec_ref: spec reference for the sub-agent (default: current)\n"
        "  max_turns: maximum number of turns (default: from agent type)"
    )
    schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Description of the task for the sub-agent.",
            },
            "agent_type": {
                "type": "string",
                "enum": ["explorer", "planner", "builder", "general"],
                "description": "Type of agent to launch.",
            },
            "spec_ref": {
                "type": "string",
                "description": "Spec ref to scope the sub-agent.",
            },
            "max_turns": {
                "type": "integer",
                "description": "Maximum turns for the sub-agent.",
            },
        },
        "required": ["task"],
        "additionalProperties": False,
    })
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.AGENT

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        task_desc = arguments.get("task", "")
        agent_type = arguments.get("agent_type", "general")
        spec_ref = arguments.get("spec_ref", "")
        max_turns = arguments.get("max_turns")

        if not task_desc:
            return ToolResult.fail("task is required.")

        # Get agent manager from session
        session = context.session
        agent_manager = getattr(session, "agent_manager", None) if session else None
        if agent_manager is None:
            return ToolResult.fail(
                "No agent manager available — sub-agent launching requires "
                "an active session with an AgentManager."
            )

        # Get agent runner for current agent (to find parent_agent_id, llm, etc.)
        agent_runner = getattr(session, "agent_runner", None) if session else None

        # Get LLM and model from the parent runner or session
        llm = getattr(agent_runner, "llm", None) or getattr(session, "llm", None)
        model = getattr(agent_runner, "model", None) or getattr(session, "model", "")
        tool_registry = getattr(agent_runner, "tool_registry", None) or getattr(session, "tool_registry", None)
        spec_service = getattr(agent_runner, "spec_service", None) or getattr(session, "spec_service", None)
        parent_agent_id = getattr(agent_runner, "agent_id", None)

        if not llm or not tool_registry:
            return ToolResult.fail(
                "Cannot launch sub-agent: missing LLM or tool registry in session."
            )

        if not spec_ref:
            spec_ref = getattr(agent_runner, "spec_ref", "") or "root"

        try:
            from taui.agent.agents import get_agent_definition

            agent_def = get_agent_definition(agent_type)

            runner = await agent_manager.launch(
                spec_ref=spec_ref,
                task=task_desc,
                tier=agent_type,
                llm=llm,
                model=model,
                tool_registry=tool_registry,
                spec_service=spec_service,
                parent_agent_id=parent_agent_id,
            )

            # Wait for the sub-agent to finish
            if runner._task is not None:
                import asyncio
                try:
                    await asyncio.wait_for(runner._task, timeout=600.0)
                except asyncio.TimeoutError:
                    await runner.stop_safely()
                    return ToolResult.fail(
                        f"Sub-agent timed out after 600 seconds. "
                        f"Agent type: {agent_type}, task: {task_desc[:100]}"
                    )

            # Gather the final message from the sub-agent
            final_messages = runner._messages
            result_text = ""
            for msg in reversed(final_messages):
                if msg.role == "assistant" and msg.content:
                    result_text = msg.content
                    break

            if not result_text:
                result_text = f"Sub-agent ({agent_type}) completed task without a summary."

            return ToolResult.ok(
                f"Sub-agent result ({agent_type}):\n\n{result_text}",
                metadata={
                    "sub_agent_id": runner.agent_id,
                    "agent_type": agent_type,
                    "total_turns": len([m for m in final_messages if m.role == "assistant"]),
                },
            )

        except ValueError as exc:
            return ToolResult.fail(str(exc))
        except Exception as exc:
            return ToolResult.fail(f"Failed to launch sub-agent: {exc}")
