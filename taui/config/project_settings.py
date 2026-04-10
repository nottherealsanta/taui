from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import Any


def _today_iso() -> str:
    return date.today().isoformat()


def default_prompt_content() -> dict[str, str]:
    return {
        "prime_system": (
            "You are Prime, the user's main AI assistant in Taui. "
            "Stay concise, practical, and delegate substantial implementation work "
            "to root and sub agents when appropriate."
        ),
        "root_agent_system": (
            "You are a Root agent in Taui. Execute assigned work end-to-end using tools, "
            "keep scope tight, and report concrete outcomes."
        ),
        "sub_agent_system": (
            "You are a Sub-agent in Taui. Complete one focused task quickly, use tools "
            "immediately, and return concise evidence-backed results."
        ),
        "tangle_maker": (
            "When writing a tangle, require minimal frontmatter (title, last_updated). "
            "Include clear prose, inline code references, and markdown links to related tangles."
        ),
        "tangle_reviewer": (
            "When reviewing a tangle, preserve intent, tighten clarity, validate references, "
            "and keep edits minimal and actionable."
        ),
    }


def default_settings() -> dict[str, Any]:
    today = _today_iso()
    prompts = {
        key: {"content": value, "is_default": True, "last_updated": today}
        for key, value in default_prompt_content().items()
    }
    return {
        "tabs": {"open": ["tangles/index.md"], "active": "tangles/index.md"},
        "layout": {"sidebarCollapsed": False, "splitSizes": [20, 50, 30]},
        "theme": None,
        "prompts": prompts,
    }


class ProjectSettingsStore:
    def __init__(self, workspace: Path | str) -> None:
        self.workspace = Path(workspace).resolve()
        self.settings_dir = self.workspace / ".taui"
        self.settings_path = self.settings_dir / "settings.json"

    def load(self) -> dict[str, Any]:
        defaults = default_settings()
        if not self.settings_path.exists():
            self.save(defaults)
            return defaults
        try:
            raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except Exception:
            self.save(defaults)
            return defaults
        if not isinstance(raw, dict):
            self.save(defaults)
            return defaults
        merged = self._merge_defaults(raw, defaults)
        if merged != raw:
            self.save(merged)
        return merged

    def save(self, payload: dict[str, Any]) -> None:
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )

    def list_prompts(self) -> dict[str, Any]:
        settings = self.load()
        prompts = settings.get("prompts", {})
        return prompts if isinstance(prompts, dict) else {}

    def get_prompt(self, key: str) -> dict[str, Any] | None:
        prompts = self.list_prompts()
        value = prompts.get(key)
        return value if isinstance(value, dict) else None

    def update_prompt(self, key: str, content: str) -> dict[str, Any]:
        settings = self.load()
        prompts = settings.setdefault("prompts", {})
        if not isinstance(prompts, dict):
            prompts = {}
            settings["prompts"] = prompts
        prompts[key] = {
            "content": content,
            "is_default": False,
            "last_updated": _today_iso(),
        }
        self.save(settings)
        return prompts[key]

    def reset_prompt(self, key: str) -> dict[str, Any] | None:
        defaults = default_settings()["prompts"]
        default_value = defaults.get(key)
        if default_value is None:
            return None
        settings = self.load()
        prompts = settings.setdefault("prompts", {})
        if not isinstance(prompts, dict):
            prompts = {}
            settings["prompts"] = prompts
        prompts[key] = default_value
        self.save(settings)
        return default_value

    def _merge_defaults(
        self, payload: dict[str, Any], defaults: dict[str, Any]
    ) -> dict[str, Any]:
        out = dict(payload)
        for key, value in defaults.items():
            if key not in out:
                out[key] = value
                continue
            if isinstance(value, dict) and isinstance(out[key], dict):
                out[key] = self._merge_defaults(out[key], value)
        return out
