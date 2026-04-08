from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from taui.config.project_settings import ProjectSettingsStore


_PROMPTS_PATH = Path(__file__).with_name("system_prompts.md")


@lru_cache(maxsize=1)
def _load_sections() -> dict[str, str]:
    try:
        text = _PROMPTS_PATH.read_text(encoding="utf-8")
    except OSError:
        return {}

    matches = list(re.finditer(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE))
    sections: dict[str, str] = {}
    for i, match in enumerate(matches):
        title = match.group(1).strip().lower()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            sections[title] = body
    return sections


def get_prompt_template(role: str) -> str | None:
    return get_prompt_template_for_workspace(role, workspace=None)


def get_prompt_template_for_workspace(
    role: str, workspace: Path | str | None
) -> str | None:
    settings_key_map = {
        "prime": "prime_system",
        "root": "root_agent_system",
        "sub-agent": "sub_agent_system",
    }
    sections = _load_sections()
    key = role.strip().lower()

    if workspace is not None:
        try:
            store = ProjectSettingsStore(Path(workspace))
            settings = store.get_prompt(settings_key_map.get(key, ""))
            if settings and isinstance(settings.get("content"), str):
                content = settings.get("content", "").strip()
                if content:
                    return content
        except Exception:
            pass

    if key in sections:
        return sections[key]

    aliases = {
        "sub_agent": "sub-agent",
        "subagent": "sub-agent",
        "sub": "sub-agent",
    }
    alias = aliases.get(key)
    if alias:
        if workspace is not None:
            try:
                store = ProjectSettingsStore(Path(workspace))
                settings = store.get_prompt(settings_key_map.get(alias, ""))
                if settings and isinstance(settings.get("content"), str):
                    content = settings.get("content", "").strip()
                    if content:
                        return content
            except Exception:
                pass
        return sections.get(alias)
    return None


def render_prompt_template(template: str, values: dict[str, str]) -> str:
    rendered = template
    for k, v in values.items():
        rendered = rendered.replace("{" + k + "}", v)
    return rendered
