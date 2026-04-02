"""ToolSearch — search for tools by keyword (claw-code pattern).

Allows the agent to discover tools that aren't immediately visible,
matching by name/description with fuzzy scoring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from taui.tools.base import Tool, ToolCategory, ToolContext, ToolResult
from taui.tools.define import define_tool


def _canonical(value: str) -> str:
    """Normalize a tool name for matching: lowercase, strip 'tool' suffix."""
    canonical = re.sub(r"[^a-z0-9]", "", value.lower())
    if canonical.endswith("tool"):
        canonical = canonical[:-4]
    return canonical


def _score(query_terms: list[str], name: str, description: str) -> int:
    """Score a tool against query terms (higher = better match)."""
    name_lower = name.lower()
    canonical_name = _canonical(name)
    desc_lower = description.lower()
    score = 0
    for term in query_terms:
        canonical_term = _canonical(term)
        if term in name_lower:
            score += 4
        if name_lower == term:
            score += 8
        if canonical_name == canonical_term:
            score += 12
        if term in desc_lower:
            score += 2
        if canonical_term and canonical_term in canonical_name:
            score += 3
    return score


async def _execute_tool_search(
    arguments: dict[str, Any], context: ToolContext
) -> ToolResult:
    query = arguments.get("query", "").strip()
    max_results = max(1, int(arguments.get("max_results", 5)))

    if not query:
        return ToolResult.fail("query must not be empty")

    # Access registry from context session if available
    registry = None
    if hasattr(context, "session") and context.session is not None:
        agent_runner = getattr(context.session, "agent_runner", None)
        if agent_runner is not None:
            registry = getattr(agent_runner, "tool_registry", None)

    if registry is None:
        return ToolResult.fail("Tool registry not available in this context")

    # Collect all tool names and descriptions
    all_tools: list[tuple[str, str]] = []
    for tool_name in registry.names():
        try:
            tool = registry.get(tool_name)
            all_tools.append((tool.name, tool.description))
        except ValueError:
            pass

    query_terms = query.lower().split()

    # Score and rank
    scored = []
    for name, description in all_tools:
        s = _score(query_terms, name, description)
        if s > 0 or not query:
            scored.append((s, name))

    scored.sort(key=lambda x: (-x[0], x[1]))
    matches = [name for _, name in scored[:max_results]]

    import json

    result = {
        "matches": matches,
        "query": query,
        "normalized_query": " ".join(_canonical(t) for t in query_terms),
        "total_tools": len(all_tools),
    }
    return ToolResult.ok(json.dumps(result, indent=2))


TOOL_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search query — keywords or tool name patterns.",
        },
        "max_results": {
            "type": "integer",
            "minimum": 1,
            "description": "Maximum number of matching tools to return (default: 5).",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}

tool_search = define_tool(
    name="tool_search",
    description=(
        "Search for available tools by keyword or name pattern. "
        "Use this to discover tools you might not know about."
    ),
    schema=TOOL_SEARCH_SCHEMA,
    execute=_execute_tool_search,
    origin="builtin",
    category=ToolCategory.SEARCH,
)
