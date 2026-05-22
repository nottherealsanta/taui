"""
Model discovery via models.dev API.

Fetches available models for each provider, caches them locally,
and provides interactive model selection.
"""

from __future__ import annotations

import json
import logging
import re
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
    "copilot": "claude-haiku-4.5",
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

    Each entry: {"id": str, "name": str, "family": str, "context": int,
    "variants": list[str], ...}. ``variants`` is the list of reasoning-effort
    tiers the model accepts (e.g. ``["low", "medium", "high"]``); empty when
    the model has no reasoning controls.
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
        reasoning = bool(info.get("reasoning", False))
        models.append({
            "id": model_id,
            "name": info.get("name", model_id),
            "family": info.get("family", ""),
            "context": context,
            "output": info.get("limit", {}).get("output", 0),
            "reasoning": reasoning,
            "variants": compute_variants(
                provider,
                model_id,
                release_date=str(info.get("release_date", "") or ""),
                reasoning=reasoning,
            ),
        })

    # Sort: reasoning models first, then by context window descending
    models.sort(key=lambda m: (not m["reasoning"], -m["context"]))
    return models


def get_model_variants(provider: str, model_id: str) -> list[str]:
    """Return the variant list for a single model (empty if unknown)."""
    for entry in list_models(provider):
        if entry["id"] == model_id:
            return list(entry.get("variants") or [])
    return []


# ── Variant computation (ported from opencode/transform.ts) ──────────────
# Source: tmp/opencode/packages/opencode/src/provider/transform.ts. Only the
# branches relevant to taui's two providers (copilot, codex) are reproduced.

_WIDELY_SUPPORTED_EFFORTS = ["low", "medium", "high"]
_OPENAI_GPT5_1_EFFORTS = ["none", *_WIDELY_SUPPORTED_EFFORTS]
_OPENAI_GPT5_2_PLUS_EFFORTS = [*_OPENAI_GPT5_1_EFFORTS, "xhigh"]
_OPENAI_GPT5_PRO_EFFORTS = ["high"]
_OPENAI_GPT5_PRO_2_PLUS_EFFORTS = ["medium", "high", "xhigh"]
_OPENAI_GPT5_CHAT_EFFORTS = ["medium"]
_OPENAI_GPT5_CODEX_XHIGH_EFFORTS = [*_WIDELY_SUPPORTED_EFFORTS, "xhigh"]
_OPENAI_GPT5_CODEX_3_PLUS_EFFORTS = ["none", *_OPENAI_GPT5_CODEX_XHIGH_EFFORTS]

_OPENAI_NONE_EFFORT_RELEASE_DATE = "2025-11-13"
_OPENAI_XHIGH_EFFORT_RELEASE_DATE = "2025-12-04"

_GPT5_FAMILY_RE = re.compile(r"(?:^|/)gpt-5(?:[.-]|$)")
_GPT5_VERSION_RE = re.compile(r"(?:^|/)gpt-5[.-](\d+)(?:[.-]|$)")
_GPT5_PRO_RE = re.compile(r"(?:^|/)gpt-5[.-]?pro(?:[.-]|$)")
_GPT5_VERSIONED_PRO_RE = re.compile(r"(?:^|/)gpt-5[.-]\d+[.-]pro(?:[.-]|$)")


def _gpt5_version(api_id: str) -> int | None:
    m = _GPT5_VERSION_RE.search(api_id)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _versioned_gpt5_efforts(api_id: str) -> list[str] | None:
    if _GPT5_VERSIONED_PRO_RE.search(api_id):
        return list(_OPENAI_GPT5_PRO_2_PLUS_EFFORTS)
    v = _gpt5_version(api_id)
    if v is None:
        return None
    if v == 1:
        return list(_OPENAI_GPT5_1_EFFORTS)
    return list(_OPENAI_GPT5_2_PLUS_EFFORTS)


def _gpt5_codex_efforts(api_id: str) -> list[str] | None:
    if not _GPT5_FAMILY_RE.search(api_id) or "codex" not in api_id:
        return None
    v = _gpt5_version(api_id)
    if v is not None and v >= 3:
        return list(_OPENAI_GPT5_CODEX_3_PLUS_EFFORTS)
    if "codex-max" in api_id or (v is not None and v >= 2):
        return list(_OPENAI_GPT5_CODEX_XHIGH_EFFORTS)
    return list(_WIDELY_SUPPORTED_EFFORTS)


def _gpt5_chat_efforts(api_id: str) -> list[str] | None:
    if not _GPT5_FAMILY_RE.search(api_id) or "-chat" not in api_id:
        return None
    return [] if _gpt5_version(api_id) is None else list(_OPENAI_GPT5_CHAT_EFFORTS)


def _openai_reasoning_efforts(api_id: str, release_date: str) -> list[str]:
    """Port of openaiReasoningEfforts() — used by the codex provider."""
    api_id = api_id.lower()
    if "deep-research" in api_id:
        return ["medium"]
    chat = _gpt5_chat_efforts(api_id)
    if chat is not None:
        return chat
    if _GPT5_PRO_RE.search(api_id):
        return list(_OPENAI_GPT5_PRO_EFFORTS)
    codex = _gpt5_codex_efforts(api_id)
    if codex is not None:
        return codex
    versioned = _versioned_gpt5_efforts(api_id)
    if versioned is not None:
        return versioned
    efforts = list(_WIDELY_SUPPORTED_EFFORTS)
    if _GPT5_FAMILY_RE.search(api_id):
        efforts.insert(0, "minimal")
    if release_date >= _OPENAI_NONE_EFFORT_RELEASE_DATE:
        efforts.insert(0, "none")
    if release_date >= _OPENAI_XHIGH_EFFORT_RELEASE_DATE:
        efforts.append("xhigh")
    return efforts


def _copilot_reasoning_efforts(model_id: str, release_date: str) -> list[str]:
    """Port of the ``@ai-sdk/github-copilot`` branch in opencode transform."""
    mid = model_id.lower()
    if "gemini" in mid:
        # Copilot's gemini endpoint only exposes thinking (not effort tiers).
        return []
    if "claude" in mid:
        return list(_WIDELY_SUPPORTED_EFFORTS)
    # GPT-5 family on copilot
    if "5.1-codex-max" in mid or "5.2" in mid or "5.3" in mid:
        return [*_WIDELY_SUPPORTED_EFFORTS, "xhigh"]
    efforts = list(_WIDELY_SUPPORTED_EFFORTS)
    if "gpt-5" in mid and release_date >= _OPENAI_XHIGH_EFFORT_RELEASE_DATE:
        efforts.append("xhigh")
    return efforts


def compute_variants(
    provider: str,
    model_id: str,
    *,
    release_date: str = "",
    reasoning: bool = True,
) -> list[str]:
    """Return the variant (reasoning effort) list a model accepts.

    Empty list means the model has no variant axis — UI should hide the
    picker in that case.
    """
    if not reasoning or not model_id:
        return []
    if provider == "copilot":
        return _copilot_reasoning_efforts(model_id, release_date)
    if provider == "codex":
        return _openai_reasoning_efforts(model_id, release_date)
    return []


# Preferred model patterns per provider (first match wins)
PREFERRED_MODELS: dict[str, list[str]] = {
    "copilot": [
        "claude-haiku-4.5",
        "claude-sonnet-4.6",
        "claude-sonnet-4.5",
        "claude-sonnet-4",
        "gpt-5.3-codex",
    ],
    "codex": ["gpt-5.3-codex", "gpt-5.2-codex", "gpt-5.1-codex"],
}


def get_default_model(provider: str) -> str:
    """Return the best default model for a provider from the live catalog."""
    models = list_models(provider)
    if not models:
        return DEFAULT_MODELS.get(provider, "claude-haiku-4.5")

    # Try preferred models first (exact prefix match)
    for prefix in PREFERRED_MODELS.get(provider, []):
        for m in models:
            if m["id"].startswith(prefix):
                return m["id"]

    # Fall back to first available
    return models[0]["id"]


def get_model_limits(provider: str, model_id: str) -> dict[str, int]:
    """Retrieve limits (context, input, output) for a model from models.json cache."""
    # Strip any provider prefix
    if "/" in model_id:
        parts = model_id.split("/", 1)
        if parts[0] in PROVIDER_MAP:
            provider = parts[0]
            model_id = parts[1]
        else:
            model_id = parts[1]

    # Map to api provider ID
    api_provider = PROVIDER_MAP.get(provider, provider)

    try:
        catalog = fetch_models()
        provider_data = catalog.get(api_provider, {})
        raw_models = provider_data.get("models", {})

        info = raw_models.get(model_id)
        if not info:
            # Prefix or substring match in keys
            for key, val in raw_models.items():
                if key.startswith(model_id) or model_id.startswith(key):
                    info = val
                    break

        if info and "limit" in info:
            limit = info["limit"]
            return {
                "context": limit.get("context", 180_000),
                "input": limit.get("input", 128_000),
                "output": limit.get("output", 32_000),
            }
    except Exception:
        pass

    return {
        "context": 180_000,
        "input": 128_000,
        "output": 32_000,
    }



def prompt_model_selection(provider: str) -> str:
    """Interactive model picker using prompt_toolkit.

    Falls back to simple input() if prompt_toolkit is unavailable.
    """
    models = list_models(provider)
    if not models:
        return DEFAULT_MODELS.get(provider, "claude-haiku-4.5")

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
            tag = " reasoning" if m["reasoning"] else ""
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
