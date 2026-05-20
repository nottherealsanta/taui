"""Unified inventory + CRUD for self-edit modal categories.

This module gives the SelfEditModal a single, consistent interface across
the very different on-disk shapes of agents, skills, commands, extensions,
prompts, and MCP servers. Each category is exposed as a `Category` and a
list of `Item`s, both keyed by `(scope, identifier)`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from taui.self_edit.store import SelfEditStore


@dataclass(frozen=True, slots=True)
class Item:
    """A single self-edit artifact (agent, skill, command, etc.)."""

    category: str
    scope: str
    identifier: str
    label: str
    summary: str
    path: Path
    body: str = ""
    builtin: bool = False
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Category:
    """Metadata for a category shown in the modal."""

    key: str
    label: str
    description: str
    new_template: str = ""
    new_extension: str = ".md"


CATEGORIES: tuple[Category, ...] = (
    Category(
        key="agents",
        label="AGENTS",
        description="Custom agent profiles with prompt, model, allowed tools.",
        new_template=(
            "You are a focused agent. Describe what this agent should do here.\n"
        ),
        new_extension=".md",
    ),
    Category(
        key="skills",
        label="SKILLS",
        description="SKILL.md-backed playbooks discoverable by the agent.",
        new_template=(
            "---\nname: new-skill\ndescription: One-line trigger description.\n---\n\n"
            "# How to use this skill\n\nSteps:\n"
        ),
        new_extension="/SKILL.md",
    ),
    Category(
        key="commands",
        label="COMMANDS",
        description="Slash commands (`.py` files exposing a Command class).",
        new_template=(
            '"""Custom slash command."""\n\n'
            "from dataclasses import dataclass\n\n\n"
            "@dataclass(slots=True)\n"
            "class MyCommand:\n"
            '    name: str = "mycmd"\n'
            '    description: str = "Describe what this command does."\n'
            "    accepts_args: bool = True\n\n"
            "    async def execute(self, ctx):\n"
            "        from taui.commands.base import CommandResult\n\n"
            '        return CommandResult.ok("hello from /mycmd")\n'
        ),
        new_extension=".py",
    ),
    Category(
        key="tools",
        label="TOOLS",
        description="Custom tool extensions (`.py` modules exporting tools).",
        new_template=(
            '"""Custom tool extension."""\n\n'
            "from taui.tools.base import ToolResult\n\n\n"
            "class MyTool:\n"
            '    name = "mytool"\n'
            '    description = "Describe what this tool does."\n'
            "    schema = {\n"
            '        "type": "object",\n'
            '        "properties": {},\n'
            '        "required": [],\n'
            "    }\n\n"
            "    async def execute(self, arguments):\n"
            '        return ToolResult.ok("ok")\n'
        ),
        new_extension=".py",
    ),
    Category(
        key="prompts",
        label="PROMPTS",
        description="Standalone prompt fragments stored as .md files.",
        new_template="# Prompt\n\n",
        new_extension=".md",
    ),
    Category(
        key="mcp",
        label="MCP",
        description="MCP server entries (servers table in mcp.toml).",
        new_template=(
            '[servers.NAME]\ncommand = "python"\nargs = ["-m", "your_mcp_server"]\n'
        ),
        new_extension=".toml-entry",
    ),
)


def category_by_key(key: str) -> Category:
    for cat in CATEGORIES:
        if cat.key == key:
            return cat
    raise KeyError(key)


def scope_root(working_dir: Path, scope: str) -> Path:
    if scope == "project":
        return working_dir / ".taui"
    return Path.home() / ".taui"


# ── Listers ──────────────────────────────────────────────────────────


def list_items(working_dir: Path, category: str, scope: str) -> list[Item]:
    """List items for one (category, scope) tuple."""
    lister = _LISTERS.get(category)
    if lister is None:
        return []
    try:
        return lister(working_dir, scope)
    except Exception:
        return []


def _list_agents(working_dir: Path, scope: str) -> list[Item]:
    store = SelfEditStore(working_dir)
    agents = store.load_agents()
    out: list[Item] = []
    for profile in agents.values():
        prompt_path = profile.prompt_path
        if prompt_path is None:
            continue
        in_scope = (
            (scope == "global" and Path.home() in prompt_path.parents)
            or (scope == "project" and prompt_path.is_relative_to(working_dir))
        )
        if not in_scope and not (profile.id in ("DEF", "PLN") and scope == "project"):
            continue
        builtin = profile.id in ("DEF", "PLN")
        model_label = "/".join(
            part for part in (profile.provider, profile.model) if part
        ) or "—"
        summary = f"{profile.name}  ·  {model_label}"
        out.append(
            Item(
                category="agents",
                scope=scope,
                identifier=profile.id,
                label=profile.id,
                summary=summary,
                path=prompt_path,
                body=profile.prompt,
                builtin=builtin,
                extra={
                    "name": profile.name,
                    "provider": profile.provider,
                    "model": profile.model,
                    "allowed_tools": list(profile.allowed_tools),
                    "auto_approve_all": profile.auto_approve_all,
                },
            )
        )
    return sorted(out, key=lambda i: (not i.builtin, i.identifier))


def _list_skills(working_dir: Path, scope: str) -> list[Item]:
    root = scope_root(working_dir, scope) / "skills"
    if not root.is_dir():
        return []
    out: list[Item] = []
    for entry in sorted(root.iterdir()):
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            body = skill_md.read_text(encoding="utf-8")
        except OSError:
            body = ""
        out.append(
            Item(
                category="skills",
                scope=scope,
                identifier=entry.name,
                label=entry.name,
                summary=_first_meaningful_line(body) or "(no description)",
                path=skill_md,
                body=body,
            )
        )
    return out


def _list_py_dir(
    working_dir: Path, scope: str, *, subdir: str, category: str
) -> list[Item]:
    root = scope_root(working_dir, scope) / subdir
    if not root.is_dir():
        return []
    out: list[Item] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_file() or entry.suffix != ".py":
            continue
        if entry.name.startswith("_"):
            continue
        try:
            body = entry.read_text(encoding="utf-8")
        except OSError:
            body = ""
        out.append(
            Item(
                category=category,
                scope=scope,
                identifier=entry.stem,
                label=entry.stem,
                summary=_first_docstring(body) or "(no docstring)",
                path=entry,
                body=body,
            )
        )
    return out


def _list_commands(working_dir: Path, scope: str) -> list[Item]:
    return _list_py_dir(working_dir, scope, subdir="commands", category="commands")


def _list_tools(working_dir: Path, scope: str) -> list[Item]:
    return _list_py_dir(working_dir, scope, subdir="extensions", category="tools")


def _list_prompts(working_dir: Path, scope: str) -> list[Item]:
    """Standalone prompts: any .md under self_edit/prompts/."""
    root = scope_root(working_dir, scope) / "self_edit" / "prompts"
    if not root.is_dir():
        return []
    out: list[Item] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_file() or entry.suffix != ".md":
            continue
        try:
            body = entry.read_text(encoding="utf-8")
        except OSError:
            body = ""
        out.append(
            Item(
                category="prompts",
                scope=scope,
                identifier=entry.stem,
                label=entry.stem,
                summary=_first_meaningful_line(body) or "(empty)",
                path=entry,
                body=body,
            )
        )
    return out


def _list_mcp(working_dir: Path, scope: str) -> list[Item]:
    path = scope_root(working_dir, scope) / "mcp.toml"
    if not path.is_file():
        return []
    try:
        import tomllib

        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return []
    servers = data.get("servers", {})
    if not isinstance(servers, dict):
        return []
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError:
        raw_text = ""
    out: list[Item] = []
    for name, conf in servers.items():
        cmd = conf.get("command", "") if isinstance(conf, dict) else ""
        args = conf.get("args", []) if isinstance(conf, dict) else []
        summary = f"{cmd} {' '.join(str(a) for a in args)}".strip() or "(no command)"
        out.append(
            Item(
                category="mcp",
                scope=scope,
                identifier=str(name),
                label=str(name),
                summary=summary,
                path=path,
                body=_extract_mcp_server_block(raw_text, str(name)),
                extra={"server_name": str(name), "config": conf},
            )
        )
    return out


_LISTERS: dict[str, Callable[[Path, str], list[Item]]] = {
    "agents": _list_agents,
    "skills": _list_skills,
    "commands": _list_commands,
    "tools": _list_tools,
    "prompts": _list_prompts,
    "mcp": _list_mcp,
}


# ── Create / save / delete ──────────────────────────────────────────


def new_item_path(
    working_dir: Path, category: str, scope: str, identifier: str
) -> Path:
    """Path to where a new item with this identifier would be saved."""
    root = scope_root(working_dir, scope)
    if category == "agents":
        return root / "self_edit" / "agents" / f"{identifier.upper()}.md"
    if category == "skills":
        return root / "skills" / identifier / "SKILL.md"
    if category == "commands":
        return root / "commands" / f"{identifier}.py"
    if category == "tools":
        return root / "extensions" / f"{identifier}.py"
    if category == "prompts":
        return root / "self_edit" / "prompts" / f"{identifier}.md"
    if category == "mcp":
        return root / "mcp.toml"
    raise KeyError(category)


def save_item(
    working_dir: Path,
    category: str,
    scope: str,
    identifier: str,
    body: str,
    extra: dict | None = None,
) -> Path:
    """Write a new or updated item to disk and return the saved path."""
    extra = extra or {}
    if category == "agents":
        return _save_agent(working_dir, scope, identifier, body, extra)
    if category == "mcp":
        return _save_mcp(working_dir, scope, identifier, body)
    path = new_item_path(working_dir, category, scope, identifier)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def delete_item(working_dir: Path, category: str, scope: str, identifier: str) -> None:
    if category == "agents":
        SelfEditStore(working_dir).delete_agent(identifier, scope)
        return
    if category == "mcp":
        _delete_mcp(working_dir, scope, identifier)
        return
    path = new_item_path(working_dir, category, scope, identifier)
    if category == "skills":
        # Remove whole skill directory.
        skill_dir = path.parent
        if skill_dir.is_dir():
            for child in sorted(skill_dir.glob("**/*"), reverse=True):
                try:
                    if child.is_dir():
                        child.rmdir()
                    else:
                        child.unlink()
                except OSError:
                    pass
            try:
                skill_dir.rmdir()
            except OSError:
                pass
        return
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass


def _save_agent(
    working_dir: Path, scope: str, identifier: str, body: str, extra: dict
) -> Path:
    from taui.self_edit.store import AgentProfile, ToolConfig

    store = SelfEditStore(working_dir)
    profile = AgentProfile(
        id=identifier.upper(),
        name=str(extra.get("name", identifier)),
        prompt=body,
        provider=str(extra.get("provider", "")),
        model=str(extra.get("model", "")),
        allowed_tools=list(extra.get("allowed_tools", [])),
        tool_config={},
        auto_approve_all=bool(extra.get("auto_approve_all", False)),
    )
    store.save_agent(profile, scope)
    return store._agent_prompt_file(scope, identifier.upper())


def _save_mcp(working_dir: Path, scope: str, identifier: str, body: str) -> Path:
    """Replace or append the [servers.NAME] block in mcp.toml."""
    path = scope_root(working_dir, scope) / "mcp.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            existing = ""

    cleaned_body = body.strip() + "\n"
    block_header = f"[servers.{identifier}]"
    new_block = cleaned_body
    if block_header not in new_block:
        new_block = f"{block_header}\n{cleaned_body}"

    if block_header in existing:
        updated = _replace_toml_block(existing, identifier, new_block)
    else:
        sep = "" if not existing or existing.endswith("\n") else "\n"
        updated = existing + sep + ("\n" if existing.strip() else "") + new_block

    path.write_text(updated, encoding="utf-8")
    return path


def _delete_mcp(working_dir: Path, scope: str, identifier: str) -> None:
    path = scope_root(working_dir, scope) / "mcp.toml"
    if not path.exists():
        return
    try:
        existing = path.read_text(encoding="utf-8")
    except OSError:
        return
    updated = _replace_toml_block(existing, identifier, "")
    try:
        path.write_text(updated, encoding="utf-8")
    except OSError:
        pass


def _extract_mcp_server_block(raw: str, name: str) -> str:
    header = f"[servers.{name}]"
    lines = raw.splitlines()
    out: list[str] = []
    inside = False
    for line in lines:
        stripped = line.strip()
        if stripped == header:
            inside = True
            out.append(line)
            continue
        if inside and stripped.startswith("[") and stripped != header:
            break
        if inside:
            out.append(line)
    text = "\n".join(out).strip()
    return text or f"{header}\n"


def _replace_toml_block(raw: str, name: str, replacement: str) -> str:
    header = f"[servers.{name}]"
    lines = raw.splitlines(keepends=True)
    out: list[str] = []
    inside = False
    for line in lines:
        stripped = line.strip()
        if stripped == header:
            inside = True
            continue
        if inside and stripped.startswith("["):
            inside = False
        if not inside:
            out.append(line)
    result = "".join(out).rstrip()
    if replacement:
        sep = "\n\n" if result else ""
        result = f"{result}{sep}{replacement.strip()}\n"
    elif result:
        result = result + "\n"
    return result


# ── Helpers ─────────────────────────────────────────────────────────


def _first_meaningful_line(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("---") or stripped.startswith("#"):
            continue
        return stripped[:120]
    return ""


def _first_docstring(body: str) -> str:
    inside = False
    for line in body.splitlines():
        stripped = line.strip()
        if not inside and stripped.startswith('"""'):
            after = stripped.lstrip('"').strip()
            if after.endswith('"""') and len(stripped) > 6:
                return after.rstrip('"').strip()[:120]
            if after:
                return after[:120]
            inside = True
            continue
        if inside and stripped:
            return stripped.rstrip('"').strip()[:120]
    return ""


def counts(working_dir: Path) -> dict[str, dict[str, int]]:
    """Counts of items per (category, scope). Used for header badges."""
    result: dict[str, dict[str, int]] = {}
    for cat in CATEGORIES:
        result[cat.key] = {
            "global": len(list_items(working_dir, cat.key, "global")),
            "project": len(list_items(working_dir, cat.key, "project")),
        }
    return result
