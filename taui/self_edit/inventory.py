"""Unified inventory + CRUD for self-edit modal categories.

This module gives the SelfEditModal a single, consistent interface across
the very different on-disk shapes of agents, skills, commands, extensions,
prompts, and MCP servers. Each category is exposed as a `Category` and a
list of `Item`s, both keyed by `(scope, identifier)`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from taui.self_edit.store import SelfEditStore
from taui.tools.schema_format import schema_param_rows


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
    Category(
        key="general",
        label="GENERAL",
        description="General settings: prefix characters and input behavior.",
        new_template="",
        new_extension="",
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
    # Ensure defaults exist before listing
    store.ensure_default_agents()
    agents = store.load_agents_for_scope(scope)
    out: list[Item] = []
    for profile in agents.values():
        prompt_path = profile.prompt_path
        if prompt_path is None:
            continue
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
                builtin=False,
                extra={
                    "name": profile.name,
                    "provider": profile.provider,
                    "model": profile.model,
                    "allowed_tools": list(profile.allowed_tools),
                    "auto_approve": profile.auto_approve,
                    "usage": profile.usage,
                    "color": profile.color,
                },
            )
        )
    return sorted(out, key=lambda i: i.identifier)


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
    items = _list_py_dir(working_dir, scope, subdir="extensions", category="tools")
    if items:
        from taui.tools.groups import _build_registry_with_attribution

        _, attribution = _build_registry_with_attribution(working_dir)
        enriched: list[Item] = []
        for it in items:
            tool_names = attribution.get(it.identifier)
            if tool_names:
                extra = dict(it.extra)
                extra["registered_tools"] = list(tool_names)
                it = replace(it, extra=extra)
            enriched.append(it)
        items = enriched
    if scope == "global":
        items = _list_builtin_tools() + items
    return items


def _list_builtin_tools() -> list[Item]:
    """Built-in tools are read-only; we surface them under the global scope."""
    try:
        from taui.tools.builtins import register_builtins
        from taui.tools.registry import ToolRegistry

        registry = ToolRegistry()
        register_builtins(registry)
    except Exception:
        return []
    out: list[Item] = []
    for name in sorted(registry.names):
        tool = registry.get(name)
        desc = getattr(tool, "description", "") or "(builtin)"
        schema = getattr(tool, "schema", None) or {}
        out.append(
            Item(
                category="tools",
                scope="global",
                identifier=name,
                label=name,
                summary=str(desc)[:120],
                path=Path(f"<builtin:{name}>"),
                body=_format_tool_definition(str(desc), schema),
                builtin=True,
                extra={"schema": schema},
            )
        )
    return out


def _format_tool_definition(description: str, schema: object) -> str:
    """Plain-text tool definition for the self-edit preview pane."""
    lines = [description.strip() or "(no description)"]
    params = schema_param_rows(schema)
    if not params:
        return "\n".join(lines)

    name_width = max(len(param.name) for param in params)
    lines.extend(["", "Parameters:"])
    for param in params:
        required = "*" if param.required else " "
        desc = f"  - {param.description}" if param.description else ""
        default = ""
        if param.default is not None and not param.required:
            default = f"  (default: {param.default!r})"
        lines.append(
            f"  {required} {param.name.ljust(name_width)}  {param.type_label}{default}{desc}"
        )
    return "\n".join(lines)


def all_tool_names(working_dir: Path) -> list[str]:
    """Every tool a user might want to grant an agent — builtins + extension tools.

    Extension tool *names* (e.g. ``notebook_read``) come from actually loading
    the user's ``~/.taui/extensions/*.py`` files into a fresh registry, not
    from file stems — one extension file may register many tools.
    """
    from taui.tools.groups import _build_known_registry

    reg = _build_known_registry(working_dir)
    return sorted(reg.names)


def builtin_tool_names() -> set[str]:
    """Set of identifiers for built-in tools (used for filtering UI)."""
    return {item.identifier for item in _list_builtin_tools()}


def _list_prompts(working_dir: Path, scope: str) -> list[Item]:
    """Standalone prompts: any .md under prompts/."""
    root = scope_root(working_dir, scope) / "prompts"
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


# ── General settings metadata ──────────────────────────────────────

# Ordered sections for the General settings panel.
# Each entry: (section_label, key, display_label, description, value_type)
GENERAL_SETTINGS_SECTIONS: tuple[
    tuple[str, list[tuple[str, str, str, type]]], ...
] = (
    (
        "PREFIXES",
        [
            (
                "file_attach",
                "File Attachment",
                "Character that triggers file completion "
                "(e.g. @filename).",
                str,
            ),
            (
                "command",
                "Command",
                "Character that triggers slash commands "
                "(e.g. /help).",
                str,
            ),
            (
                "skills",
                "Skills",
                "Character that triggers skill search "
                "(e.g. !skill-name).",
                str,
            ),
            (
                "prompts",
                "Prompts",
                "Character that triggers prompt templates "
                "(e.g. #prompt-name).",
                str,
            ),
        ],
    ),
    (
        "AGENT",
        [
            (
                "max_turns",
                "Max Turns",
                "Maximum tool-use cycles per request.",
                int,
            ),
            (
                "sub_agent_max_turns",
                "Sub-agent Max Turns",
                "Default turn budget for spawned sub-agents (capped at 25).",
                int,
            ),
            (
                "provider",
                "Default Provider",
                "LLM provider used when no override is given.",
                str,
            ),
            (
                "model",
                "Default Model",
                "Model name used when no override is given (empty = auto).",
                str,
            ),
        ],
    ),
    (
        "NOTIFICATIONS",
        [
            (
                "notifications",
                "Notifications",
                "Enable or disable all notifications.",
                bool,
            ),
            (
                "notify_on_turn_done",
                "Notify on Turn Done",
                "Notify when the agent finishes a request.",
                bool,
            ),
            (
                "notify_on_question",
                "Notify on Question",
                "Notify when the agent asks a question.",
                bool,
            ),
        ],
    ),
    (
        "DISPLAY",
        [
            (
                "verbose_tools",
                "Verbose Tools",
                "Show full tool output in the chat log.",
                bool,
            ),
            (
                "auto_approve",
                "Auto Approve",
                "Skip approval for every tool call.",
                bool,
            ),
        ],
    ),
)

# Flat map: key -> (toml_dot_path, type)
_GENERAL_SETTINGS_MAP: dict[str, tuple[str, type]] = {
    "file_attach": ("prefixes.file_attach", str),
    "command": ("prefixes.command", str),
    "skills": ("prefixes.skills", str),
    "prompts": ("prefixes.prompts", str),
    "max_turns": ("max_turns", int),
    "sub_agent_max_turns": ("sub_agent_max_turns", int),
    "provider": ("provider", str),
    "model": ("model", str),
    "notifications": ("notifications", bool),
    "notify_on_turn_done": ("notify_on_turn_done", bool),
    "notify_on_question": ("notify_on_question", bool),
    "verbose_tools": ("verbose_tools", bool),
    "auto_approve": ("auto_approve", bool),
}

# Total number of general settings (used for the tab badge).
_GENERAL_SETTINGS_COUNT: int = sum(
    len(rows) for _, rows in GENERAL_SETTINGS_SECTIONS
)

# Defaults that mirror taui/config.py.
_GENERAL_DEFAULTS: dict[str, object] = {
    "file_attach": "@",
    "command": "/",
    "skills": "!",
    "prompts": "#",
    "max_turns": 50,
    "sub_agent_max_turns": 25,
    "provider": "copilot",
    "model": "",
    "notifications": True,
    "notify_on_turn_done": True,
    "notify_on_question": True,
    "verbose_tools": True,
    "auto_approve": False,
}


def _load_general_values() -> dict[str, object]:
    """Read current general setting values from the config file."""
    from taui.llm_provider.config import load_config

    raw = load_config()
    taui_cfg = raw.get("taui", {})
    prefixes = taui_cfg.get("prefixes", {})

    values: dict[str, object] = dict(_GENERAL_DEFAULTS)
    for fld in ("max_turns", "sub_agent_max_turns", "provider", "model",
                "notifications", "notify_on_turn_done", "notify_on_question",
                "verbose_tools", "auto_approve"):
        if fld in taui_cfg:
            values[fld] = taui_cfg[fld]
    for fld in ("file_attach", "command"):
        if fld in prefixes:
            values[fld] = prefixes[fld]
    return values


def _list_general(working_dir: Path, scope: str) -> list[Item]:
    """Return one Item per general setting (always global scope)."""
    from taui.llm_provider.config import CONFIG_PATH

    values = _load_general_values()
    out: list[Item] = []
    for _section, rows in GENERAL_SETTINGS_SECTIONS:
        for key, label, description, _vtype in rows:
            raw_val = values.get(key, _GENERAL_DEFAULTS.get(key, ""))
            summary = _format_general_value(raw_val)
            out.append(
                Item(
                    category="general",
                    scope="global",
                    identifier=key,
                    label=label,
                    summary=summary,
                    path=CONFIG_PATH,
                    body=description,
                    builtin=False,
                )
            )
    return out


def _format_general_value(value: object) -> str:
    """Human-readable display string for a setting value."""
    if isinstance(value, bool):
        return "on" if value else "off"
    if value == "" or value is None:
        return "(auto)"
    return str(value)


def save_general_setting(key: str, value: object) -> None:
    """Persist a general setting to ~/.config/taui/config.toml under [taui]."""
    from taui.llm_provider.config import CONFIG_PATH, _dict_to_toml, load_config

    if key not in _GENERAL_SETTINGS_MAP:
        raise KeyError(f"Unknown general setting: {key!r}")

    path, vtype = _GENERAL_SETTINGS_MAP[key]
    # Coerce to the expected type.
    if vtype is bool:
        coerced: object = bool(value)
    elif vtype is int:
        coerced = int(value)
    else:
        coerced = str(value)

    existing = load_config()
    taui_cfg = existing.setdefault("taui", {})
    parts = path.split(".")
    target: dict = taui_cfg
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = coerced

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(_dict_to_toml(existing), encoding="utf-8")


def _save_prefix_setting(key: str, value: str) -> None:
    """Persist a prefix setting to the global config file.

    Kept for backward compatibility — delegates to save_general_setting.
    """
    save_general_setting(key, value)


_LISTERS: dict[str, Callable[[Path, str], list[Item]]] = {
    "agents": _list_agents,
    "skills": _list_skills,
    "commands": _list_commands,
    "tools": _list_tools,
    "prompts": _list_prompts,
    "mcp": _list_mcp,
    "general": _list_general,
}


# ── Create / save / delete ──────────────────────────────────────────


def new_item_path(
    working_dir: Path, category: str, scope: str, identifier: str
) -> Path:
    """Path to where a new item with this identifier would be saved."""
    root = scope_root(working_dir, scope)
    if category == "agents":
        return root / "agents" / f"{identifier.upper()}.md"
    if category == "skills":
        return root / "skills" / identifier / "SKILL.md"
    if category == "commands":
        return root / "commands" / f"{identifier}.py"
    if category == "tools":
        return root / "extensions" / f"{identifier}.py"
    if category == "prompts":
        return root / "prompts" / f"{identifier}.md"
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
    from taui.self_edit.store import AgentProfile

    store = SelfEditStore(working_dir)
    from taui.self_edit.store import AGENT_USAGE_VALUES

    usage = str(extra.get("usage", "both")).strip().lower()
    if usage not in AGENT_USAGE_VALUES:
        usage = "sub" if bool(extra.get("subagent_only", False)) else "both"
    profile = AgentProfile(
        id=identifier.upper(),
        name=str(extra.get("name", identifier)),
        prompt=body,
        provider=str(extra.get("provider", "")),
        model=str(extra.get("model", "")),
        allowed_tools=list(extra.get("allowed_tools", [])),
        tool_config={},
        auto_approve=bool(extra.get("auto_approve", extra.get("auto_approve_all", False))),
        usage=usage,
        color=str(extra.get("color", "")),
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

    new_block = _normalize_mcp_server_block(identifier, body)
    block_header = f"[servers.{identifier}]"

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
    lines = raw.splitlines()
    out: list[str] = []
    inside = False
    for line in lines:
        table = _toml_table_name(line)
        if table == f"servers.{name}":
            inside = True
            out.append(line)
            continue
        if inside and table is not None and not _is_mcp_server_table(table, name):
            break
        if inside:
            out.append(line)
    text = "\n".join(out).strip()
    return text or f"[servers.{name}]\n"


def _replace_toml_block(raw: str, name: str, replacement: str) -> str:
    lines = raw.splitlines(keepends=True)
    out: list[str] = []
    inside = False
    for line in lines:
        table = _toml_table_name(line)
        if table == f"servers.{name}":
            inside = True
            continue
        if inside and table is not None and not _is_mcp_server_table(table, name):
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


_MCP_SERVER_HEADER_RE = re.compile(
    r"^\s*\[\s*servers\.(?P<name>[A-Za-z0-9_-]+|\"[^\"]+\")(?P<suffix>(?:\.[^\]]+)?)\s*\]\s*$",
    re.MULTILINE,
)


def _normalize_mcp_server_block(identifier: str, body: str) -> str:
    """Return a single server block whose headers use `identifier`.

    The new-item template contains `[servers.NAME]`; LLM generation may also
    choose a different name. The modal's ID field is the source of truth, so
    rewrite the main and nested server table headers instead of prepending a
    second header.
    """
    cleaned = body.strip()
    if not cleaned:
        return f"[servers.{identifier}]\n"

    found = False

    def repl(match: re.Match[str]) -> str:
        nonlocal found
        found = True
        suffix = match.group("suffix") or ""
        return f"[servers.{identifier}{suffix}]"

    normalized = _MCP_SERVER_HEADER_RE.sub(repl, cleaned)
    if not found:
        normalized = f"[servers.{identifier}]\n{cleaned}"
    return normalized.strip() + "\n"


def _toml_table_name(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("[") or not stripped.endswith("]"):
        return None
    stripped = stripped.strip("[]").strip()
    # This self-edit file only needs server-table block boundaries; keep the
    # parser deliberately narrow and leave full TOML parsing to tomllib.
    return stripped.replace('"', "")


def _is_mcp_server_table(table: str, name: str) -> bool:
    return table == f"servers.{name}" or table.startswith(f"servers.{name}.")


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
        if cat.key == "general":
            result[cat.key] = {"global": _GENERAL_SETTINGS_COUNT, "project": 0}
        else:
            result[cat.key] = {
                "global": len(list_items(working_dir, cat.key, "global")),
                "project": len(list_items(working_dir, cat.key, "project")),
            }
    return result
