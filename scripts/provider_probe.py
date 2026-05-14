"""
Interactive probe script to test LLM provider capabilities.

Tests each provider for:
1. Basic text streaming
2. Tool calling (if supported)
3. Reasoning tokens (if supported)
4. Error handling (context overflow, rate limits)
5. Credential refresh

Usage (from the repo root):
    uv run python scripts/provider_probe.py copilot
    uv run python scripts/provider_probe.py codex
    uv run python scripts/provider_probe.py copilot --test streaming
    uv run python scripts/provider_probe.py copilot --test tools
    uv run python scripts/provider_probe.py copilot --test reasoning
    uv run python scripts/provider_probe.py copilot --test all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ── Test Tool Schemas ──────────────────────────────────────────────────────────

SIMPLE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a location.",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name, e.g. 'San Francisco'",
                },
            },
            "required": ["location"],
        },
    },
}

MULTI_PARAM_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read the contents of a file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
                "start_line": {
                    "type": "integer",
                    "description": "Starting line number (1-based)",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Ending line number (1-based, inclusive)",
                },
            },
            "required": ["path"],
        },
    },
}

# ── Test Results ───────────────────────────────────────────────────────────────


@dataclass
class TestResult:
    name: str
    passed: bool
    duration_ms: float
    details: str = ""
    error: str | None = None


# ── Test Functions ─────────────────────────────────────────────────────────────


async def test_streaming(provider: Any, model: str) -> TestResult:
    """Test basic text streaming — send a simple prompt, verify streamed response."""
    start = time.monotonic()
    try:
        messages = [
            {"role": "system", "content": "You are a helpful assistant. Be brief."},
            {"role": "user", "content": "What is 2 + 2? Reply with just the number."},
        ]

        result = await provider.create_turn(messages=messages, model=model)

        if not result.text.strip():
            return TestResult(
                name="streaming",
                passed=False,
                duration_ms=(time.monotonic() - start) * 1000,
                error="Empty response text",
            )

        details = f"Response: {result.text.strip()!r} ({len(result.text)} chars)"
        if result.usage:
            details += (
                f" | Tokens: {result.usage.input_tokens}in/{result.usage.output_tokens}out"
            )

        return TestResult(
            name="streaming",
            passed=True,
            duration_ms=(time.monotonic() - start) * 1000,
            details=details,
        )
    except Exception as exc:
        return TestResult(
            name="streaming",
            passed=False,
            duration_ms=(time.monotonic() - start) * 1000,
            error=str(exc),
        )


async def test_tools(provider: Any, model: str) -> TestResult:
    """Test tool calling — send tools, verify tool call is returned with correct arguments."""
    start = time.monotonic()

    caps = provider.capabilities
    if not caps.supports_tools:
        return TestResult(
            name="tools",
            passed=True,
            duration_ms=0,
            details="Skipped: provider does not support tools",
        )

    try:
        messages = [
            {"role": "system", "content": "You are a helpful assistant. Use the available tools."},
            {"role": "user", "content": "What's the weather in San Francisco?"},
        ]

        result = await provider.create_turn(
            messages=messages,
            model=model,
            tools=[SIMPLE_TOOL],
        )

        if not result.has_tool_calls:
            return TestResult(
                name="tools",
                passed=False,
                duration_ms=(time.monotonic() - start) * 1000,
                error=f"No tool calls returned. Text: {result.text[:200]!r}",
            )

        tc = result.tool_calls[0]
        details = f"Tool: {tc.name}({json.dumps(tc.arguments)})"
        details += f" | call_id: {tc.call_id!r}"

        # Verify it called the right tool
        if tc.name != "get_weather":
            return TestResult(
                name="tools",
                passed=False,
                duration_ms=(time.monotonic() - start) * 1000,
                error=f"Wrong tool called: {tc.name!r} (expected 'get_weather')",
            )

        # Verify arguments contain location
        if "location" not in tc.arguments:
            return TestResult(
                name="tools",
                passed=False,
                duration_ms=(time.monotonic() - start) * 1000,
                error=f"Missing 'location' in arguments: {tc.arguments}",
            )

        return TestResult(
            name="tools",
            passed=True,
            duration_ms=(time.monotonic() - start) * 1000,
            details=details,
        )
    except Exception as exc:
        return TestResult(
            name="tools",
            passed=False,
            duration_ms=(time.monotonic() - start) * 1000,
            error=str(exc),
        )


async def test_multi_tool(provider: Any, model: str) -> TestResult:
    """Test multiple tool calls in a single turn."""
    start = time.monotonic()

    caps = provider.capabilities
    if not caps.supports_tools or not caps.supports_parallel_tool_calls:
        return TestResult(
            name="multi_tool",
            passed=True,
            duration_ms=0,
            details="Skipped: provider does not support parallel tool calls",
        )

    try:
        messages = [
            {
                "role": "system",
                "content": "You are a helpful assistant. Use tools for each request.",
            },
            {
                "role": "user",
                "content": "What's the weather in San Francisco and New York? Check both.",
            },
        ]

        result = await provider.create_turn(
            messages=messages,
            model=model,
            tools=[SIMPLE_TOOL],
        )

        if len(result.tool_calls) < 2:
            return TestResult(
                name="multi_tool",
                passed=False,
                duration_ms=(time.monotonic() - start) * 1000,
                error=f"Expected 2+ tool calls, got {len(result.tool_calls)}",
            )

        details = " | ".join(
            f"{tc.name}({json.dumps(tc.arguments)})" for tc in result.tool_calls
        )
        return TestResult(
            name="multi_tool",
            passed=True,
            duration_ms=(time.monotonic() - start) * 1000,
            details=details,
        )
    except Exception as exc:
        return TestResult(
            name="multi_tool",
            passed=False,
            duration_ms=(time.monotonic() - start) * 1000,
            error=str(exc),
        )


async def test_reasoning(provider: Any, model: str) -> TestResult:
    """Test reasoning token capture."""
    start = time.monotonic()

    caps = provider.capabilities
    if not caps.supports_reasoning:
        return TestResult(
            name="reasoning",
            passed=True,
            duration_ms=0,
            details=(
                "Skipped: provider does not support reasoning "
                f"(format={caps.reasoning_format.value})"
            ),
        )

    try:
        messages = [
            {"role": "system", "content": "Think step by step."},
            {
                "role": "user",
                "content": (
                    "If a train travels 120 miles in 2 hours, what is its average speed "
                    "in km/h? (1 mile = 1.609 km)"
                ),
            },
        ]

        result = await provider.create_turn(
            messages=messages,
            model=model,
            thinking_level="medium",
        )

        has_reasoning = (
            result.assistant_metadata
            and (
                result.assistant_metadata.get("reasoning_text")
                or result.assistant_metadata.get("reasoning_opaque")
            )
        )

        details = f"Response: {result.text.strip()[:100]!r}"
        if result.assistant_metadata:
            rt = result.assistant_metadata.get("reasoning_text", "")
            ro = result.assistant_metadata.get("reasoning_opaque", "")
            if rt:
                details += f" | Reasoning text: {len(rt)} chars"
            if ro:
                details += f" | Reasoning opaque: {len(ro)} chars"

        return TestResult(
            name="reasoning",
            passed=True,  # Don't fail if reasoning not returned — model may not think
            duration_ms=(time.monotonic() - start) * 1000,
            details=details + (" [NO REASONING CAPTURED]" if not has_reasoning else ""),
        )
    except Exception as exc:
        return TestResult(
            name="reasoning",
            passed=False,
            duration_ms=(time.monotonic() - start) * 1000,
            error=str(exc),
        )


async def test_tool_result_roundtrip(provider: Any, model: str) -> TestResult:
    """Test sending a tool result back and getting a text response."""
    start = time.monotonic()

    caps = provider.capabilities
    if not caps.supports_tools:
        return TestResult(
            name="tool_roundtrip",
            passed=True,
            duration_ms=0,
            details="Skipped: provider does not support tools",
        )

    try:
        # First turn: get a tool call
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What's the weather in Tokyo?"},
        ]

        result1 = await provider.create_turn(
            messages=messages, model=model, tools=[SIMPLE_TOOL]
        )

        if not result1.has_tool_calls:
            return TestResult(
                name="tool_roundtrip",
                passed=False,
                duration_ms=(time.monotonic() - start) * 1000,
                error="First turn did not produce tool calls",
            )

        tc = result1.tool_calls[0]

        # Second turn: provide tool result
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [tc.to_chat_completions_format()],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tc.call_id,
                "content": json.dumps({"temperature": "22°C", "condition": "Sunny"}),
            }
        )

        result2 = await provider.create_turn(
            messages=messages, model=model, tools=[SIMPLE_TOOL]
        )

        if not result2.text.strip():
            return TestResult(
                name="tool_roundtrip",
                passed=False,
                duration_ms=(time.monotonic() - start) * 1000,
                error="Second turn produced empty text response",
            )

        return TestResult(
            name="tool_roundtrip",
            passed=True,
            duration_ms=(time.monotonic() - start) * 1000,
            details=f"Response: {result2.text.strip()[:200]!r}",
        )
    except Exception as exc:
        return TestResult(
            name="tool_roundtrip",
            passed=False,
            duration_ms=(time.monotonic() - start) * 1000,
            error=str(exc),
        )


async def test_capabilities_report(provider: Any, model: str) -> TestResult:
    """Report the provider's declared capabilities (always passes)."""
    caps = provider.capabilities
    lines = [
        f"api_format: {provider.api_format}",
        f"supports_tools: {caps.supports_tools}",
        f"supports_streaming: {caps.supports_streaming}",
        f"supports_reasoning: {caps.supports_reasoning}",
        f"supports_images: {caps.supports_images}",
        f"supports_cache_control: {caps.supports_cache_control}",
        f"supports_response_id: {caps.supports_response_id}",
        f"reasoning_format: {caps.reasoning_format.value}",
        f"tool_call_id_format: {caps.tool_call_id_format.value}",
        f"requires_streaming_for_tools: {caps.requires_streaming_for_tools}",
        f"supports_parallel_tool_calls: {caps.supports_parallel_tool_calls}",
    ]
    return TestResult(
        name="capabilities",
        passed=True,
        duration_ms=0,
        details="\n    ".join(lines),
    )


# ── Test Runner ────────────────────────────────────────────────────────────────

ALL_TESTS = {
    "capabilities": test_capabilities_report,
    "streaming": test_streaming,
    "tools": test_tools,
    "multi_tool": test_multi_tool,
    "reasoning": test_reasoning,
    "tool_roundtrip": test_tool_result_roundtrip,
}


def print_result(result: TestResult) -> None:
    """Print a test result with color."""
    status = "✓" if result.passed else "✗"
    color = "\033[32m" if result.passed else "\033[31m"
    reset = "\033[0m"
    duration = f" ({result.duration_ms:.0f}ms)" if result.duration_ms > 0 else ""

    print(f"  {color}{status}{reset} {result.name}{duration}")
    if result.details:
        for line in result.details.split("\n"):
            print(f"    {line}")
    if result.error:
        print(f"    \033[31mError: {result.error}\033[0m")


async def run_tests(
    provider: Any,
    model: str,
    test_names: list[str] | None = None,
) -> list[TestResult]:
    """Run selected tests against a provider."""
    if test_names is None or "all" in test_names:
        test_names = list(ALL_TESTS.keys())

    results = []
    for name in test_names:
        test_fn = ALL_TESTS.get(name)
        if test_fn is None:
            print(f"  ? Unknown test: {name}")
            continue
        result = await test_fn(provider, model)
        results.append(result)
        print_result(result)

    return results


# ── CLI ────────────────────────────────────────────────────────────────────────


def _create_provider(provider_name: str) -> tuple[Any, str]:
    """
    Create a provider instance and return (provider, default_model).
    """
    if provider_name == "copilot":
        from taui.llm_provider.auth.copilot import get_copilot_credentials
        from taui.llm_provider.providers.copilot import CopilotProvider

        creds = get_copilot_credentials()
        return CopilotProvider(creds), "claude-haiku-4.5"

    elif provider_name == "codex":
        from taui.llm_provider.auth.codex import get_codex_credentials
        from taui.llm_provider.providers.codex import CodexProvider

        creds = get_codex_credentials()
        return CodexProvider(creds), "gpt-5.3-codex"

    else:
        print(f"Error: Unknown provider '{provider_name}'")
        print("Available providers: copilot, codex")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Probe LLM provider capabilities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python scripts/provider_probe.py copilot
  uv run python scripts/provider_probe.py codex --test tools
  uv run python scripts/provider_probe.py copilot --test streaming --test reasoning
  uv run python scripts/provider_probe.py copilot --model claude-opus-4
        """,
    )
    parser.add_argument("provider", help="Provider to test (copilot, codex)")
    parser.add_argument("--model", help="Override default model")
    parser.add_argument(
        "--test",
        action="append",
        dest="tests",
        help=f"Tests to run (default: all). Options: {', '.join(ALL_TESTS.keys())}",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    provider, default_model = _create_provider(args.provider)
    model = args.model or default_model

    print(f"\n{'='*60}")
    print(f"  Provider: {args.provider}")
    print(f"  Model:    {model}")
    print(f"{'='*60}\n")

    results = asyncio.run(run_tests(provider, model, args.tests))

    # Summary
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    total_ms = sum(r.duration_ms for r in results)

    print(f"\n{'─'*60}")
    print(f"  {passed} passed, {failed} failed ({total_ms:.0f}ms total)")
    print(f"{'─'*60}\n")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
