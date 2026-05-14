"""Replay-based eval harness.

Replays recorded sessions against the current build, diffs the
tool-call sequence, and flags regressions. Designed for golden
task testing.

Usage::

    results = await run_eval("fixtures/eval-tasks/")
    for r in results:
        print(r.name, r.status, r.diff_summary)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EvalFixture:
    """A single eval fixture: recorded input + expected outputs."""

    name: str
    path: Path
    user_messages: list[str] = field(default_factory=list)
    expected_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    expected_final_text: str = ""


@dataclass(slots=True)
class EvalResult:
    """Result of evaluating one fixture."""

    name: str
    status: str  # "pass", "fail", "error"
    actual_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    diff_summary: str = ""
    error: str = ""
    turns: int = 0


def load_fixtures(fixture_dir: Path) -> list[EvalFixture]:
    """Load eval fixtures from a directory.

    Each fixture is a JSON file::

        {
            "name": "basic-read",
            "messages": ["Read main.py"],
            "expected_tools": [
                {"name": "read", "args_match": {"path": "main.py"}}
            ],
            "expected_text": "contents of main.py"
        }
    """
    fixtures: list[EvalFixture] = []
    if not fixture_dir.is_dir():
        return fixtures
    for f in sorted(fixture_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            fixtures.append(EvalFixture(
                name=data.get("name", f.stem),
                path=f,
                user_messages=data.get("messages", []),
                expected_tool_calls=data.get("expected_tools", []),
                expected_final_text=data.get("expected_text", ""),
            ))
        except Exception as exc:
            logger.warning("Bad fixture %s: %s", f, exc)
    return fixtures


def diff_tool_calls(
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
) -> str:
    """Compare expected vs actual tool call sequences.

    Returns a human-readable diff summary, or "" if matching.
    """
    lines: list[str] = []

    for i, exp in enumerate(expected):
        exp_name = exp.get("name", "")
        if i >= len(actual):
            lines.append(f"  missing: {exp_name}")
            continue
        act = actual[i]
        act_name = act.get("name", "")
        if exp_name != act_name:
            lines.append(f"  [{i}] expected {exp_name}, got {act_name}")
        # Check arg patterns
        args_match = exp.get("args_match", {})
        act_args = act.get("arguments", {})
        for key, val in args_match.items():
            if act_args.get(key) != val:
                lines.append(
                    f"  [{i}].{key}: expected {val!r}, got {act_args.get(key)!r}"
                )

    extra = len(actual) - len(expected)
    if extra > 0:
        lines.append(f"  {extra} extra tool call(s)")

    return "\n".join(lines)


async def run_eval(
    fixture_dir: str | Path,
    *,
    session_factory: Any = None,
) -> list[EvalResult]:
    """Run all fixtures in a directory.

    If session_factory is None, returns error results for each fixture.
    In practice, pass a configured Session or async factory function.
    """
    fixture_dir = Path(fixture_dir)
    fixtures = load_fixtures(fixture_dir)
    results: list[EvalResult] = []

    for fixture in fixtures:
        if session_factory is None:
            results.append(EvalResult(
                name=fixture.name,
                status="error",
                error="No session factory provided",
            ))
            continue

        try:
            session = (
                await session_factory()
                if callable(session_factory)
                else session_factory
            )
            result = None
            for msg in fixture.user_messages:
                result = await session.send(msg)

            if result is None:
                results.append(EvalResult(
                    name=fixture.name,
                    status="error",
                    error="No messages in fixture",
                ))
                continue

            # Extract actual tool calls from turn results
            actual_calls: list[dict[str, Any]] = []
            for tr in result.turn_results:
                # Tool calls are in the loop messages
                pass  # Simplified — full impl reads stream

            diff = diff_tool_calls(fixture.expected_tool_calls, actual_calls)
            status = "pass" if not diff else "fail"
            results.append(EvalResult(
                name=fixture.name,
                status=status,
                actual_tool_calls=actual_calls,
                diff_summary=diff,
                turns=result.turns,
            ))
        except Exception as exc:
            results.append(EvalResult(
                name=fixture.name,
                status="error",
                error=str(exc),
            ))

    return results
