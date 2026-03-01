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
import sys

from taui.auth import PROVIDER_NAMES, get_credentials
from taui.llms import DEFAULT_MODELS, get_llm_client

PROVIDERS = list(PROVIDER_NAMES.keys())


def main() -> None:
    parser = argparse.ArgumentParser(description="taui — multi-provider LLM chat")
    parser.add_argument(
        "-p",
        "--provider",
        choices=PROVIDERS,
        default="copilot",
        help="LLM provider to use (default: copilot)",
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
    model = args.model or DEFAULT_MODELS[args.provider]

    asyncio.run(_repl(client, model, args.provider))


async def _repl(client, model: str, provider: str) -> None:
    messages: list[dict[str, str]] = []
    print(f"Provider: {PROVIDER_NAMES[provider]}")
    print(f"Model:    {model}")
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
            response_text = await client.stream_chat(messages, model)
        except PermissionError as exc:
            print(f"\nError: {exc}", file=sys.stderr)
            break
        except Exception as exc:
            print(f"\nError: {exc}", file=sys.stderr)
            messages.pop()
            continue

        messages.append({"role": "assistant", "content": response_text})
        print()


if __name__ == "__main__":
    main()
