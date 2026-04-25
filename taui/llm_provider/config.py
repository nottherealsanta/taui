"""
Config persistence for taui.

All providers save credentials under [providers.<name>] in ~/.config/taui/config.toml.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

CONFIG_PATH: Path = Path.home() / ".config" / "taui" / "config.toml"


def load_config() -> dict:
    """Read and parse the full TOML file. Returns {} if missing or parse error."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        return tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_provider_config(provider: str, data: dict) -> None:
    """Merge data into config["providers"][provider] and write back."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = load_config()
    providers = existing.setdefault("providers", {})
    entry = providers.setdefault(provider, {})
    entry.update(data)
    CONFIG_PATH.write_text(_dict_to_toml(existing), encoding="utf-8")


def load_provider_config(provider: str) -> dict | None:
    """Return config["providers"][provider], or None if not present."""
    config = load_config()
    return config.get("providers", {}).get(provider) or None


def _dict_to_toml(data: dict, _prefix: str = "") -> str:
    """Minimal TOML serialiser sufficient for round-tripping config.toml."""
    lines: list[str] = []
    deferred: list[tuple[str, dict]] = []

    for key, value in data.items():
        full_key = f"{_prefix}.{key}" if _prefix else key
        if isinstance(value, dict):
            deferred.append((full_key, value))
        elif isinstance(value, bool):
            lines.append(f"{key} = {str(value).lower()}")
        elif isinstance(value, int):
            lines.append(f"{key} = {value}")
        elif isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
        elif isinstance(value, list):
            items = ", ".join(f'"{v}"' if isinstance(v, str) else str(v) for v in value)
            lines.append(f"{key} = [{items}]")

    result = "\n".join(lines)

    for full_key, sub_dict in deferred:
        section = _dict_to_toml(sub_dict, _prefix=full_key)
        header = f"[{full_key}]"
        result = (
            f"{result}\n\n{header}\n{section}"
            if result.strip()
            else f"{header}\n{section}"
        )

    return result
