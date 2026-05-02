"""
Model discovery via models.dev API.

Fetches available models for each provider, caches them locally,
and provides interactive model selection.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

MODELS_API_URL = "https://models.dev/api.json"
CACHE_DIR = Path.home() / ".cache" / "taui"
CACHE_FILE = CACHE_DIR / "models.json"
CACHE_TTL = 86400  # 24 hours

# Map taui provider names → models.dev provider IDs
PROVIDER_MAP: dict[str, str] = {
    "copilot": "github-copilot",
    "codex": "openai",
}

# Default models per provider (fallback when API is unavailable)
DEFAULT_MODELS: dict[str, str] = {
    "copilot": "claude-sonnet-4.6",
    "codex": "gpt-5.3-codex",
}


def _load_cache() -> dict | None:
    """Load cached models data if fresh enough."""
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if time.time() - data.get("_fetched_at", 0) < CACHE_TTL:
            return data
    except Exception:
        pass
    return None


def _save_cache(data: dict) -> None:
    """Write models data to cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data["_fetched_at"] = time.time()
    CACHE_FILE.write_text(json.dumps(data), encoding="utf-8")


def fetch_models(*, force: bool = False) -> dict:
    """Fetch the full models.dev catalog. Uses cache unless force=True."""
    if not force:
        cached = _load_cache()
        if cached is not None:
            return cached

    try:
        resp = httpx.get(MODELS_API_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        _save_cache(data)
        return data
    except Exception as e:
        logger.debug("Failed to fetch models.dev: %s", e)
        # Fall back to stale cache if available
        if CACHE_FILE.exists():
            try:
                return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}


def list_models(provider: str, *, force_refresh: bool = False) -> list[dict]:
    """Return available models for a taui provider.

    Each entry: {"id": str, "name": str, "family": str, "context": int, ...}
    """
    api_provider = PROVIDER_MAP.get(provider)
    if not api_provider:
        return []

    catalog = fetch_models(force=force_refresh)
    provider_data = catalog.get(api_provider, {})
    raw_models = provider_data.get("models", {})

    models = []
    for model_id, info in raw_models.items():
        # Only include models that support tool calling (needed for agentic use)
        if not info.get("tool_call", False):
            continue
        context = info.get("limit", {}).get("context", 0)
        models.append({
            "id": model_id,
            "name": info.get("name", model_id),
            "family": info.get("family", ""),
            "context": context,
            "output": info.get("limit", {}).get("output", 0),
            "reasoning": info.get("reasoning", False),
        })

    # Sort: reasoning models first, then by context window descending
    models.sort(key=lambda m: (not m["reasoning"], -m["context"]))
    return models


# Preferred model patterns per provider (first match wins)
PREFERRED_MODELS: dict[str, list[str]] = {
    "copilot": ["claude-sonnet-4.6", "claude-sonnet-4.5", "claude-sonnet-4", "gpt-5.3-codex"],
    "codex": ["gpt-5.3-codex", "gpt-5.2-codex", "gpt-5.1-codex"],
}


def get_default_model(provider: str) -> str:
    """Return the best default model for a provider from the live catalog."""
    models = list_models(provider)
    if not models:
        return DEFAULT_MODELS.get(provider, "claude-sonnet-4.6")

    model_ids = {m["id"] for m in models}

    # Try preferred models first (exact prefix match)
    for prefix in PREFERRED_MODELS.get(provider, []):
        for m in models:
            if m["id"].startswith(prefix):
                return m["id"]

    # Fall back to first available
    return models[0]["id"]


def prompt_model_selection(provider: str) -> str:
    """Interactive model picker using prompt_toolkit.

    Falls back to simple input() if prompt_toolkit is unavailable.
    """
    models = list_models(provider)
    if not models:
        return DEFAULT_MODELS.get(provider, "claude-sonnet-4.6")

    try:
        return _prompt_toolkit_select(models, provider)
    except ImportError:
        return _simple_select(models, provider)


def _prompt_toolkit_select(models: list[dict], provider: str) -> str:
    """Interactive selection with arrow keys."""
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    selected = [0]
    # Show at most 15 models to keep the UI clean
    display_models = models[:15]

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(event):
        selected[0] = (selected[0] - 1) % len(display_models)

    @kb.add("down")
    @kb.add("j")
    def _down(event):
        selected[0] = (selected[0] + 1) % len(display_models)

    @kb.add("enter")
    def _enter(event):
        event.app.exit(result=display_models[selected[0]]["id"])

    @kb.add("c-c")
    @kb.add("c-d")
    def _quit(event):
        event.app.exit(result=None)

    def _get_text():
        lines = [("bold", f"Select model for {provider}:\n\n")]
        for i, m in enumerate(display_models):
            ctx = f"{m['context'] // 1000}k" if m["context"] else "?"
            tag = " 🧠" if m["reasoning"] else ""
            label = f"{m['name']}  ({ctx} ctx){tag}"
            if i == selected[0]:
                lines.append(("bold fg:cyan", f"  ❯ {label}\n"))
            else:
                lines.append(("class:dim", f"    {label}\n"))
        lines.append(("", "\n"))
        lines.append(("class:dim", "↑/↓ to move, Enter to select, Ctrl+C to skip"))
        return lines

    app: Application[str | None] = Application(
        layout=Layout(HSplit([Window(FormattedTextControl(_get_text))])),
        key_bindings=kb,
        full_screen=False,
    )

    result = app.run()
    if result is None:
        # User skipped — return default
        return DEFAULT_MODELS.get(provider, models[0]["id"])
    return result


def _simple_select(models: list[dict], provider: str) -> str:
    """Fallback text-based selection."""
    print(f"\nAvailable models for {provider}:")
    display = models[:15]
    for i, m in enumerate(display, 1):
        ctx = f"{m['context'] // 1000}k" if m["context"] else "?"
        tag = " (reasoning)" if m["reasoning"] else ""
        print(f"  {i:2}. {m['name']}  [{ctx} ctx]{tag}")
    print()
    try:
        choice = input(f"Choose [1-{len(display)}] or Enter for default: ").strip()
        if not choice:
            return DEFAULT_MODELS.get(provider, models[0]["id"])
        idx = int(choice) - 1
        if 0 <= idx < len(display):
            return display[idx]["id"]
    except (ValueError, EOFError, KeyboardInterrupt):
        pass
    return DEFAULT_MODELS.get(provider, models[0]["id"])
