"""
Auth package — provider credential registry.

Re-exports credential types and provides get_credentials() factory.
"""

from ..config import load_provider_config
from .codex import CodexCredentials, get_codex_credentials
from .copilot import CopilotCredentials, get_copilot_credentials


def _get_provider_names() -> dict[str, str]:
    """Get provider names from the registry."""
    from taui.llm_provider.registry import get_provider_entry, get_provider_names

    return {name: get_provider_entry(name).label for name in get_provider_names()}


# Lazy-loaded provider names dict (populated on first access via functions that use it)
PROVIDER_NAMES: dict[str, str] = {
    "copilot": "GitHub Copilot",
    "codex": "OpenAI Codex (ChatGPT Plus/Pro)",
}


def get_credentials(provider: str):
    """Return credentials for the given provider name. Triggers interactive login if needed."""
    from taui.llm_provider.registry import get_provider_entry

    entry = get_provider_entry(provider)
    return entry.auth()


def has_any_credentials() -> bool:
    """Return True if at least one provider has saved credentials."""
    for provider in PROVIDER_NAMES:
        saved = load_provider_config(provider)
        if saved:
            return True
    return False


def get_saved_provider() -> str | None:
    """Return the first provider that has saved credentials, or None."""
    for provider in PROVIDER_NAMES:
        saved = load_provider_config(provider)
        if saved:
            return provider
    return None


def prompt_provider_selection() -> str:
    """Interactively ask the user which provider(s) to authenticate with.

    Allows multi-select with Space, runs auth for each selected provider,
    then returns the first successfully authenticated provider key.
    """
    try:
        from prompt_toolkit import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import HSplit, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
    except ImportError:
        return _simple_provider_selection()

    providers = list(PROVIDER_NAMES.items())
    cursor = [0]
    checked: set[int] = set()

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(event):
        cursor[0] = (cursor[0] - 1) % len(providers)

    @kb.add("down")
    @kb.add("j")
    def _down(event):
        cursor[0] = (cursor[0] + 1) % len(providers)

    @kb.add("space")
    def _toggle(event):
        if cursor[0] in checked:
            checked.discard(cursor[0])
        else:
            checked.add(cursor[0])

    @kb.add("enter")
    def _enter(event):
        # If nothing toggled, select current item
        if not checked:
            checked.add(cursor[0])
        event.app.exit(result=[providers[i][0] for i in sorted(checked)])

    @kb.add("c-c")
    @kb.add("c-d")
    def _quit(event):
        event.app.exit(result=None)

    def _get_text():
        lines = [("bold", "Welcome to taui!\n")]
        lines.append(("", "Select providers to authenticate:\n\n"))
        for i, (key, label) in enumerate(providers):
            mark = "◉" if i in checked else "○"
            if i == cursor[0]:
                lines.append(("bold fg:cyan", f"  ❯ {mark} {label}\n"))
            else:
                lines.append(("class:dim", f"    {mark} {label}\n"))
        lines.append(("", "\n"))
        lines.append(("class:dim", "↑/↓ move, Space toggle, Enter confirm"))
        return lines

    app: Application[list[str] | None] = Application(
        layout=Layout(HSplit([Window(FormattedTextControl(_get_text))])),
        key_bindings=kb,
        full_screen=False,
    )

    selected = app.run()
    if not selected:
        raise SystemExit(0)

    # Run auth flow for each selected provider
    authenticated: list[str] = []
    for provider in selected:
        label = PROVIDER_NAMES[provider]
        print(f"\n── Authenticating {label} ──")
        try:
            get_credentials(provider)
            authenticated.append(provider)
        except Exception as e:
            print(f"  Failed: {e}")

    if not authenticated:
        print("\nNo providers authenticated.")
        raise SystemExit(1)

    if len(authenticated) > 1:
        print(f"\nAuthenticated: {', '.join(PROVIDER_NAMES[p] for p in authenticated)}")

    # Return the first authenticated provider
    return authenticated[0]


def _simple_provider_selection() -> str:
    """Fallback provider selector when prompt_toolkit is unavailable."""
    providers = list(PROVIDER_NAMES.items())
    print("Select provider to authenticate:")
    for index, (_key, label) in enumerate(providers, start=1):
        print(f"  {index}. {label}")
    choice = input("Provider [1]: ").strip() or "1"
    try:
        provider = providers[int(choice) - 1][0]
    except (ValueError, IndexError):
        raise SystemExit(f"Invalid provider selection: {choice}") from None

    print(f"\n── Authenticating {PROVIDER_NAMES[provider]} ──")
    get_credentials(provider)
    return provider


__all__ = [
    "get_credentials",
    "has_any_credentials",
    "prompt_provider_selection",
    "PROVIDER_NAMES",
    "CopilotCredentials",
    "CodexCredentials",
    "get_copilot_credentials",
    "get_codex_credentials",
]
