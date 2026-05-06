"""Scaffolding helpers for self-edit-created artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_AGENT_ID_RE = re.compile(r"^[A-Z]{3}$")


@dataclass(slots=True)
class NewToolRequest:
    name: str
    description: str
    category: str
    prompt: str


@dataclass(slots=True)
class NewExtensionRequest:
    name: str
    prompt: str


def slug(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-_").lower()
    return cleaned or fallback


def slug_from_prompt(prompt: str, fallback: str) -> str:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9]*", prompt.lower())
    stop = {
        "a", "an", "and", "as", "build", "create", "for", "from", "in", "make",
        "new", "of", "on", "that", "the", "to", "tool", "with",
    }
    useful = [word for word in words if word not in stop]
    return "_".join(useful[:4]) or fallback


def summary_from_prompt(prompt: str, fallback: str) -> str:
    cleaned = " ".join(prompt.split())
    if not cleaned:
        return fallback
    sentence = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0].strip()
    if len(sentence) <= 140:
        return sentence
    return f"{sentence[:137].rstrip()}..."


def title_from_prompt(prompt: str, fallback: str) -> str:
    value = slug_from_prompt(prompt, fallback.lower())
    return " ".join(part.capitalize() for part in value.split("_")) or fallback


def agent_id_from_prompt(prompt: str, existing_ids: set[str]) -> str:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9]*", prompt.upper())
    useful = [word for word in words if len(word) >= 3]
    candidates = [word[:3] for word in useful]
    if len(useful) >= 3:
        candidates.append("".join(word[0] for word in useful[:3]))
    candidates.append("AGT")
    for candidate in candidates:
        if _AGENT_ID_RE.match(candidate) and candidate not in existing_ids:
            return candidate
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for first in alphabet:
        for second in alphabet:
            candidate = f"A{first}{second}"
            if candidate not in existing_ids:
                return candidate
    return "AGT"


def agent_prompt_from_request(prompt: str) -> str:
    cleaned = prompt.strip()
    if re.search(r"\byou are\b", cleaned, flags=re.IGNORECASE):
        return cleaned
    return f"You are a focused Taui sub-agent. {cleaned}"


def infer_tool_category(prompt: str) -> str:
    text = prompt.lower()
    categories = [
        ("file_write", ("write", "edit", "modify", "save", "patch", "create file")),
        ("file_read", ("read", "inspect file", "open file", "load file")),
        ("search", ("search", "find", "grep", "discover", "analyze", "scan")),
        ("shell", ("shell", "command", "terminal", "run", "execute")),
        ("git", ("git", "commit", "branch", "diff", "status", "pr")),
        ("memory", ("memory", "remember", "recall", "note")),
        ("question", ("ask", "question", "confirm", "choose")),
    ]
    for category, keywords in categories:
        if any(keyword in text for keyword in keywords):
            return category
    return "agent"


def class_name_from_slug(value: str, suffix: str) -> str:
    parts = re.findall(r"[a-zA-Z0-9]+", value)
    name = "".join(part[:1].upper() + part[1:] for part in parts) or "Custom"
    if name[:1].isdigit():
        name = f"Custom{name}"
    return f"{name}{suffix}"


def unique_path(base: Path, stem: str, suffix: str) -> Path:
    path = base / f"{stem}{suffix}"
    index = 2
    while path.exists():
        path = base / f"{stem}_{index}{suffix}"
        index += 1
    return path


def scope_extension_base(working_dir: Path, scope: str) -> Path:
    if scope == "project":
        return working_dir / ".taui" / "extensions"
    return Path.home() / ".taui" / "extensions"


def tool_extension_template(request: NewToolRequest) -> str:
    class_name = class_name_from_slug(request.name, "Tool")
    prompt_literal = repr(request.prompt)
    description_literal = repr(request.description)
    return f'''from dataclasses import dataclass, field
from typing import Any

from taui.tools.base import ToolCategory, ToolResult


@dataclass(slots=True)
class {class_name}:
    name: str = "{request.name}"
    description: str = {description_literal}
    category: ToolCategory = ToolCategory.{request.category.upper()}
    schema: dict[str, Any] = field(default_factory=lambda: {{
        "type": "object",
        "properties": {{
            "input": {{"type": "string", "description": "Tool input."}},
        }},
        "required": ["input"],
    }})
    construction_prompt: str = {prompt_literal}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        user_input = str(arguments.get("input", "")).strip()
        if not user_input:
            user_input = self.construction_prompt
        return ToolResult.ok(
            "Tool scaffold created from prompt. Edit this execute() method "
            f"to implement behavior.\\n\\nPrompt: {{self.construction_prompt}}"
            f"\\n\\nInput: {{user_input}}"
        )


def register(tools, commands, hooks):
    tools.register({class_name}())
'''


def extension_template(request: NewExtensionRequest) -> str:
    prompt_literal = repr(request.prompt)
    description_literal = repr(summary_from_prompt(request.prompt, "Custom Taui extension."))
    return f'''"""Taui extension generated from a prompt."""

DESCRIPTION = {description_literal}
CONSTRUCTION_PROMPT = {prompt_literal}


def register(tools, commands, hooks):
    """Register extension components."""
    # Prompt: {{CONSTRUCTION_PROMPT}}
    return None
'''


def find_tool_source(tool_name: str, extension_paths: list[Path]) -> Path | None:
    patterns = (
        f'name: str = "{tool_name}"',
        f"name: str = '{tool_name}'",
        f'name = "{tool_name}"',
        f"name = '{tool_name}'",
    )
    preferred = {f"tool_{tool_name}.py", f"{tool_name}.py"}
    for path in extension_paths:
        if path.name in preferred:
            return path
    for path in extension_paths:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if any(pattern in content for pattern in patterns):
            return path
    return None
