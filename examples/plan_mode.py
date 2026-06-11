"""Example: custom read-only agent variant.

Register a 'review' agent variant that can only read and search,
never write or execute. Use with `/agent review` to switch.

Copy this pattern to create any named agent variant with custom
tools, system prompt, or model. taui ships builtin 'build' and
'plan' variants; define your own here to extend or complement them.
"""

from __future__ import annotations

from taui.agent.variants import AgentVariant


def register(ctx):
    if ctx.agents is None:
        return
    ctx.agents.register(AgentVariant(
        name="review",
        description="Read-only code review agent",
        read_only=True,
        system_prompt=(
            "You are a code review agent. Analyze the codebase "
            "and produce a structured review. You CANNOT modify "
            "files — only read and search. Format your findings "
            "as a numbered list of issues with file:line citations."
        ),
    ))
