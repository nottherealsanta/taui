"""Example: read-only plan agent variant.

Register a 'plan' agent variant that can only read and search,
never write or execute. Use with `/agent plan` to switch.
"""

from __future__ import annotations

from taui.agent.variants import AgentVariant


def register(ctx):
    ctx.agents.register(AgentVariant(
        name="plan",
        description="Read-only planning agent",
        read_only=True,
        system_prompt=(
            "You are a planning agent. Analyze the codebase "
            "and produce a detailed plan. You CANNOT modify "
            "files — only read and search. Output your plan "
            "as a structured markdown document."
        ),
    ))
