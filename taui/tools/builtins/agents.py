"""
Agent-launching tools — launch_minion and launch_root.

These tools are intended for Prime's tool loop. They rely on the session
having an ``agent_manager`` and ``notification_callback`` so they can
spin up agents and push real-time notifications to the frontend.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from taui.tools.base import ToolCategory, ToolContext, ToolResult

logger = logging.getLogger(__name__)


def _get_agent_manager(context: ToolContext) -> Any:
    """Extract AgentManager from the tool context session."""
    session = context.session
    return getattr(session, "agent_manager", None) if session else None


def _get_notification_callback(context: ToolContext) -> Callable[..., None] | None:
    """Extract the notification callback from the tool context session."""
    session = context.session
    return getattr(session, "notification_callback", None) if session else None


def _emit(context: ToolContext, method: str, params: dict[str, Any]) -> None:
    """Emit a JSON-RPC notification via the session's callback."""
    from taui.server.protocol import notification_message

    cb = _get_notification_callback(context)
    if cb is not None:
        try:
            cb(notification_message(method, params))
        except Exception:
            logger.exception("Failed to emit notification %s", method)


# ── LaunchMinionTool ──────────────────────────────────────────────────────────


@dataclass(slots=True)
class LaunchMinionTool:
    """Launch a lightweight minion agent for a quick lookup or sub-task.

    The minion runs autonomously and this tool blocks until the minion
    finishes, returning its result directly. The frontend sees the minion
    as an inline card in Prime's chat.
    """

    name: str = "launch_minion"
    description: str = (
        "Launch a lightweight minion agent for a focused sub-task such as "
        "reading files, searching code, or answering a factual question.\n\n"
        "The minion runs autonomously and returns its result when done. "
        "Use this when you need to gather information without interrupting "
        "your main reasoning flow.\n\n"
        "Parameters:\n"
        "  task (required): what the minion should do\n"
        "  spec_ref: spec branch context (optional)"
    )
    schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Description of the task for the minion.",
                },
                "spec_ref": {
                    "type": "string",
                    "description": "Spec ref context for the minion (optional).",
                },
            },
            "required": ["task"],
            "additionalProperties": False,
        }
    )
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.AGENT

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        task_desc = arguments.get("task", "")
        spec_ref = arguments.get("spec_ref", "root")

        if not task_desc:
            return ToolResult.fail("task is required.")

        agent_manager = _get_agent_manager(context)
        if agent_manager is None:
            return ToolResult.fail(
                "No agent manager available — minion launching requires "
                "an active Prime session with an AgentManager."
            )

        # Resolve LLM + model + tools from the session
        session = context.session
        llm = getattr(session, "llm", None)
        model = getattr(session, "model", "")
        tool_registry = getattr(session, "tool_registry", None)
        spec_service = getattr(session, "spec_service", None)

        if not llm or not tool_registry:
            return ToolResult.fail(
                "Cannot launch minion: missing LLM or tool registry in session."
            )

        if not spec_ref:
            spec_ref = "root"

        try:
            runner = await agent_manager.launch(
                spec_ref=spec_ref,
                task=task_desc,
                tier="low",
                llm=llm,
                model=model,
                tool_registry=tool_registry,
                spec_service=spec_service,
                working_dir=context.working_dir,
                agent_type="minion",
            )

            minion_id = runner.agent_id

            # Notify frontend: minion launched
            _emit(
                context,
                "prime/minionLaunched",
                {
                    "minion_id": minion_id,
                    "task": task_desc,
                },
            )

            # Block until the minion finishes
            if runner._task is not None:
                try:
                    await asyncio.wait_for(runner._task, timeout=120.0)
                except asyncio.TimeoutError:
                    await runner.stop_safely()
                    _emit(
                        context,
                        "prime/minionDone",
                        {
                            "minion_id": minion_id,
                            "result": f"Minion timed out after 120 seconds. Task: {task_desc[:200]}",
                        },
                    )
                    return ToolResult.fail(
                        f"Minion timed out after 120 seconds. Task: {task_desc[:200]}"
                    )

            # Gather the final assistant message from the minion
            final_messages = runner._messages
            result_text = ""
            for msg in reversed(final_messages):
                if msg.role == "assistant" and msg.content:
                    result_text = msg.content
                    break

            if not result_text:
                result_text = "Minion completed task without producing a summary."

            # Notify frontend: minion done
            _emit(
                context,
                "prime/minionDone",
                {
                    "minion_id": minion_id,
                    "result": result_text,
                },
            )

            return ToolResult.ok(
                f"Minion result:\n\n{result_text}",
                metadata={
                    "minion_id": minion_id,
                    "task": task_desc,
                },
            )

        except Exception as exc:
            logger.exception("Failed to launch minion: %s", exc)
            return ToolResult.fail(f"Failed to launch minion: {exc}")


# ── LaunchRootTool ────────────────────────────────────────────────────────────


@dataclass(slots=True)
class LaunchRootTool:
    """Launch a root agent for a large autonomous task.

    Unlike minions, root agents are non-blocking — they run in the
    background and appear as a new tab in the agent pane. Prime can
    reference them but doesn't wait for them to finish.
    """

    name: str = "launch_root"
    description: str = (
        "Launch a root agent for a large, autonomous task that will run "
        "in the background.\n\n"
        "The root agent appears as a new color-named tab in the agent pane. "
        "Use this for substantial tasks like implementing features, refactoring "
        "code, or writing tests — tasks that need multiple tool calls and "
        "sustained reasoning.\n\n"
        "Parameters:\n"
        "  task (required): description of what the agent should do\n"
        "  spec_ref (required): the spec branch the agent works on\n"
        "  tier: agent tier — 'high', 'medium', or 'low' (default: medium)"
    )
    schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Description of the task for the root agent.",
                },
                "spec_ref": {
                    "type": "string",
                    "description": "Spec ref branch for the agent to work on.",
                },
                "tier": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "Agent tier (default: medium).",
                },
            },
            "required": ["task", "spec_ref"],
            "additionalProperties": False,
        }
    )
    origin: str = "builtin"
    category: ToolCategory = ToolCategory.AGENT

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        task_desc = arguments.get("task", "")
        spec_ref = arguments.get("spec_ref", "")
        tier = arguments.get("tier", "medium")

        if not task_desc:
            return ToolResult.fail("task is required.")
        if not spec_ref:
            return ToolResult.fail("spec_ref is required.")
        if tier not in ("high", "medium", "low"):
            return ToolResult.fail("tier must be 'high', 'medium', or 'low'.")

        agent_manager = _get_agent_manager(context)
        if agent_manager is None:
            return ToolResult.fail(
                "No agent manager available — root agent launching requires "
                "an active Prime session with an AgentManager."
            )

        session = context.session
        llm = getattr(session, "llm", None)
        model = getattr(session, "model", "")
        tool_registry = getattr(session, "tool_registry", None)
        spec_service = getattr(session, "spec_service", None)

        if not llm or not tool_registry:
            return ToolResult.fail(
                "Cannot launch root agent: missing LLM or tool registry in session."
            )

        try:
            runner = await agent_manager.launch(
                spec_ref=spec_ref,
                task=task_desc,
                tier=tier,
                llm=llm,
                model=model,
                tool_registry=tool_registry,
                spec_service=spec_service,
                working_dir=context.working_dir,
                agent_type="root",
            )

            # Notify frontend: agent launched (from Prime)
            _emit(
                context,
                "prime/agentLaunched",
                {
                    "agent_id": runner.agent_id,
                    "display_name": runner.display_name,
                    "task": task_desc,
                },
            )

            return ToolResult.ok(
                f"Root agent launched: {runner.display_name} (id: {runner.agent_id})\n"
                f"Task: {task_desc}\n"
                f"The agent is now running in the background. "
                f"It will appear as a new tab in the agent pane.",
                metadata={
                    "agent_id": runner.agent_id,
                    "display_name": runner.display_name,
                    "agent_type": "root",
                    "spec_ref": spec_ref,
                },
            )

        except Exception as exc:
            logger.exception("Failed to launch root agent: %s", exc)
            return ToolResult.fail(f"Failed to launch root agent: {exc}")
