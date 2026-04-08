from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path


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
    sections = _load_sections()
    key = role.strip().lower()
    if key in sections:
        return sections[key]

    aliases = {
        "sub_agent": "sub-agent",
        "subagent": "sub-agent",
        "sub": "sub-agent",
    }
    alias = aliases.get(key)
    if alias:
        return sections.get(alias)
    return None


def render_prompt_template(template: str, values: dict[str, str]) -> str:
    rendered = template
    for k, v in values.items():
        rendered = rendered.replace("{" + k + "}", v)
    return rendered
