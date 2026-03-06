"""
taui entry point — multi-provider LLM chat REPL.

Run with:
    taui [-p PROVIDER] [-m MODEL]
    python -m taui [-p PROVIDER] [-m MODEL]

Providers: copilot (default), gemini, antigravity, codex

On first run the selected provider triggers an interactive login flow.
Subsequent runs reuse saved tokens from ~/.config/taui/config.toml.

Type your message and press Enter to chat.
Press Ctrl-C or Ctrl-D (empty input) to exit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Any

import httpx

from taui.agent.session import Session
from taui.auth import PROVIDER_NAMES, get_credentials
from taui.config.policies import Policy
from taui.config.settings import load_settings
from taui.llms import DEFAULT_MODELS, get_llm_client
from taui.llms.base import BaseLLMClient
from taui.tools.base import ToolContext, ToolResult
from taui.tools.builtins import register_builtin_tools
from taui.tools.executor import ToolExecutor
from taui.tools.registry import ToolRegistry

PROVIDERS = list(PROVIDER_NAMES.keys())


def main() -> None:
    settings = load_settings()
    configured_provider, configured_model = _resolve_configured_default(
        settings.model.default
    )

    parser = argparse.ArgumentParser(description="taui — multi-provider LLM chat")
    parser.add_argument(
        "-p",
        "--provider",
        choices=PROVIDERS,
        default=configured_provider,
        help=f"LLM provider to use (default: {configured_provider})",
    )
    parser.add_argument(
        "-m",
        "--model",
        default=None,
        help="Model name override (default: provider default)",
    )
    args = parser.parse_args()

    try:
        credentials = get_credentials(args.provider)
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
    except Exception as exc:
        import os, traceback

        if os.environ.get("TAUI_DEBUG"):
            traceback.print_exc()
        print(f"Login failed: {exc}", file=sys.stderr)
        sys.exit(1)

    client = get_llm_client(args.provider, credentials)
    if args.model:
        model = args.model
    elif args.provider == configured_provider:
        model = configured_model
    else:
        model = DEFAULT_MODELS[args.provider]

    asyncio.run(_repl(client, model, args.provider))


async def _repl(client, model: str, provider: str) -> None:
    messages: list[dict[str, Any]] = []
    settings = load_settings()
    policy = Policy.from_settings(settings)
    tool_session = Session()
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)
    tool_context = ToolContext(
        working_dir=Path.cwd(),
        session=tool_session,
        policy=policy,
    )
    print(f"Provider: {PROVIDER_NAMES[provider]}")
    print(f"Model:    {model}")
    if getattr(client, "supports_tools", False):
        print(f"Tools:    {', '.join(registry.names())}")
    print("Type your message. Press Ctrl-D or enter blank line twice to exit.\n")

    blank_count = 0

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            blank_count += 1
            if blank_count >= 2:
                print("Goodbye.")
                break
            continue
        blank_count = 0

        messages.append({"role": "user", "content": user_input})
        print("\nAssistant: ", end="", flush=True)

        try:
            response_text, assistant_message = await _run_with_tools(
                client=client,
                messages=messages,
                model=model,
                registry=registry,
                executor=executor,
                tool_context=tool_context,
            )
        except PermissionError as exc:
            print(f"\nError: {exc}", file=sys.stderr)
            break
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = exc.response.text.strip()
            if detail:
                print(f"\nError: HTTP {status}: {detail}", file=sys.stderr)
            else:
                print(f"\nError: HTTP {status}", file=sys.stderr)
            messages.pop()
            continue
        except Exception as exc:
            print(f"\nError: {exc}", file=sys.stderr)
            messages.pop()
            continue

        if assistant_message is None:
            messages.append({"role": "assistant", "content": response_text})
        else:
            messages.append(assistant_message)
        print()


async def _run_with_tools(
    *,
    client: BaseLLMClient,
    messages: list[dict[str, Any]],
    model: str,
    registry: ToolRegistry,
    executor: ToolExecutor,
    tool_context: ToolContext,
) -> tuple[str, dict[str, Any] | None]:
    tools = registry.list_schemas()
    tool_mode = getattr(client, "tool_call_mode", "none")
    previous_response_id: str | None = None
    input_items: list[dict[str, object]] | None = None
    turn_messages: list[dict[str, Any]] = [dict(msg) for msg in messages]
    final_text = ""
    final_assistant_metadata: dict[str, Any] | None = None

    for _ in range(12):
        response = await client.create_turn(
            messages=turn_messages,
            model=model,
            tools=tools,
            input_items=input_items if tool_mode == "responses" else None,
            previous_response_id=(
                previous_response_id if tool_mode == "responses" else None
            ),
        )
        previous_response_id = response.response_id or previous_response_id
        final_assistant_metadata = response.assistant_metadata
        if response.text:
            final_text += response.text
        if not response.tool_calls:
            if getattr(client, "supports_tools", False):
                print(final_text, end="", flush=True)
            assistant_message: dict[str, Any] = {"role": "assistant", "content": final_text}
            if final_assistant_metadata:
                assistant_message.update(final_assistant_metadata)
            return final_text, assistant_message
        if tool_mode == "responses":
            if not previous_response_id:
                raise RuntimeError(
                    "Model returned tool calls without a response id; cannot continue tool loop."
                )
            input_items = []
            for call in response.tool_calls:
                outcome = await executor.run(
                    tool_call_id=call.call_id,
                    tool_name=call.name,
                    arguments=call.arguments,
                    context=tool_context,
                )
                result = await _resolve_tool_outcome(
                    call_id=call.call_id,
                    outcome=outcome,
                    executor=executor,
                    tool_name=call.name,
                    arguments=call.arguments,
                    context=tool_context,
                )
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": result.content,
                    }
                )
            continue

        if tool_mode == "chat":
            assistant_call_items: list[dict[str, object]] = []
            tool_result_messages: list[dict[str, str]] = []
            for call in response.tool_calls:
                outcome = await executor.run(
                    tool_call_id=call.call_id,
                    tool_name=call.name,
                    arguments=call.arguments,
                    context=tool_context,
                )
                result = await _resolve_tool_outcome(
                    call_id=call.call_id,
                    outcome=outcome,
                    executor=executor,
                    tool_name=call.name,
                    arguments=call.arguments,
                    context=tool_context,
                )
                assistant_call_items.append(
                    {
                        "id": call.call_id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, sort_keys=True),
                        },
                    }
                )
                tool_result_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.call_id,
                        "content": result.content,
                    }
                )

            assistant_message: dict[str, object] = {
                "role": "assistant",
                "content": response.text,
                "tool_calls": assistant_call_items,
            }
            if final_assistant_metadata:
                assistant_message.update(final_assistant_metadata)
            turn_messages.append(assistant_message)
            turn_messages.extend(tool_result_messages)
            continue

        raise RuntimeError("Provider returned tool calls but does not support tool mode.")

    raise RuntimeError("Exceeded tool-call turn limit (12).")


async def _resolve_tool_outcome(
    *,
    call_id: str,
    outcome: Any,
    executor: ToolExecutor,
    tool_name: str,
    arguments: dict[str, object],
    context: ToolContext,
) -> ToolResult:
    state = getattr(outcome, "state", "")
    if state == "completed" or state == "denied":
        return outcome.result

    if state == "approval_required":
        approved = _confirm_tool_use(
            tool_name=outcome.tool_name,
            reason=outcome.reason,
            arguments_preview=outcome.arguments_preview,
        )
        follow_up = await executor.run(
            tool_call_id=call_id,
            tool_name=tool_name,
            arguments=arguments,
            context=context,
            approved=approved,
        )
        follow_up_state = getattr(follow_up, "state", "")
        if follow_up_state in {"completed", "denied"}:
            return follow_up.result
        return ToolResult.fail("Tool approval flow did not complete as expected.")

    return ToolResult.fail("Tool execution returned unknown state.")


def _confirm_tool_use(*, tool_name: str, reason: str, arguments_preview: str) -> bool:
    print(
        f"\n\nTool approval required: {tool_name}\nReason: {reason}\nArguments: {arguments_preview}"
    )
    answer = input("Approve? [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def _resolve_configured_default(configured: str) -> tuple[str, str]:
    if ":" in configured:
        provider, model = configured.split(":", 1)
        if provider in PROVIDERS and model:
            return provider, model

    for provider, model in DEFAULT_MODELS.items():
        if model == configured:
            return provider, model

    return "copilot", configured or DEFAULT_MODELS["copilot"]


if __name__ == "__main__":
    main()
