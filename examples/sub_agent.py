"""Example: sub-agent usage via the composable session API.

Shows how to create a sub-session with restricted tools
and a custom prompt, run it, and collect the result.
"""

from __future__ import annotations


async def research_topic(session, topic: str) -> str:
    """Spawn a read-only sub-agent to research a topic."""
    sub = await session.create_sub_session(
        tools=["read", "glob", "grep"],
        system_prompt=(
            "You are a research agent. Find all relevant "
            "code and documentation about the given topic. "
            "Summarize your findings concisely."
        ),
        max_turns=5,
    )
    result = await sub.send(f"Research: {topic}")
    return result.text
