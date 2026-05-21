"""Persistence and source discovery models for self-edit mode."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_AGENT_ID_RE = re.compile(r"^[A-Z]{3}$")

# Valid `usage` values for AgentProfile. Controls where the profile shows up:
#   "main" — main agent only (Tab cycle, /agents, picker); not spawnable via sub_agent
#   "sub"  — sub-agent only (hidden from main UI); spawnable via sub_agent(agent_id=…)
#   "both" — available in both contexts (default)
AGENT_USAGE_VALUES = ("main", "sub", "both")


@dataclass(slots=True)
class ToolConfig:
    """Per-tool configuration within an agent profile."""

    policy: str = "auto"  # "auto", "confirm", or "deny"
    param_restrictions: dict[str, Any] = field(default_factory=dict)
    # param_restrictions example: {"working_dir": "/allowed/path"}


@dataclass(slots=True)
class AgentProfile:
    id: str
    name: str
    prompt: str
    provider: str
    model: str
    allowed_tools: list[str]
    prompt_path: Path | None = None
    tool_config: dict[str, ToolConfig] = field(default_factory=dict)
    auto_approve_all: bool = False
    # Where the profile is reachable. One of "main", "sub", "both".
    usage: str = "both"
    # Optional accent color (hex like "#7aa2f7", named like "cyan", or "").
    # Used to tint the agent badge in the picker / info bar. Sub-only agents
    # don't use a color.
    color: str = ""

    @property
    def subagent_only(self) -> bool:
        """Back-compat alias: True iff this profile is hidden from main UI."""
        return self.usage == "sub"

    @property
    def main_visible(self) -> bool:
        """Show in the main agent picker / Tab cycle / /agents listing."""
        return self.usage in ("main", "both")

    @property
    def spawnable_as_sub(self) -> bool:
        """Reachable via `sub_agent` tool with `agent_id=<ID>`."""
        return self.usage in ("sub", "both")


@dataclass(slots=True)
class ToolSource:
    name: str
    path: Path | None


@dataclass(slots=True)
class ExtensionSource:
    name: str
    path: Path | None
    scope: str
    description: str = ""
    loaded: bool = False
    error: str | None = None


# Default agent files: filename -> full frontmatter+prompt markdown content.
_DEFAULT_AGENT_FILES: dict[str, str] = {
    "DEF.md": (
        '---\n'
        'name: Default\n'
        'usage: both\n'
        'color: "#7aa2f7"\n'
        'allowed_tools: []\n'
        'auto_approve_all: true\n'
        '---\n'
        'You are a pragmatic software engineer. Make scoped changes and verify them.'
    ),
    "PLN.md": (
        '---\n'
        'name: Planner\n'
        'usage: both\n'
        'color: "#bb9af7"\n'
        'allowed_tools: ["read", "glob", "grep"]\n'
        '---\n'
        'You are PLN, a planning agent. Investigate the task and produce a clear, '
        'actionable implementation plan. Do not write or edit code — '
        'only read, search, and reason.\n'
        '\n'
        'Return a plan with: (1) Goal — one sentence restating what is being built; '
        '(2) Key files — paths (with line numbers when useful); '
        '(3) Steps — an ordered list of concrete edits or actions; '
        '(4) Risks / open questions — anything ambiguous or worth confirming.\n'
        '\n'
        'Prefer file_path:line_number references over prose. Stop as soon as '
        'the plan is solid — do not pad.'
    ),
    "EXP.md": (
        '---\n'
        'name: Explorer\n'
        'usage: sub\n'
        'allowed_tools: ["read", "glob", "grep", "bash"]\n'
        '---\n'
        'You are EXP, a code-exploration sub-agent. You are spawned by a parent agent '
        'to answer a focused question about the codebase.\n'
        '\n'
        'You have read-only tools: `read`, `glob`, `grep`, and `bash` '
        '(for safe inspection like `ls`, `wc`, `head`, `cat`). Do not modify files.\n'
        '\n'
        'Workflow: cast a wide net first (glob/grep), narrow to the files that matter, '
        'then read them. Return a tight, structured answer with file_path:line_number '
        'references — no padding, no speculation. If the question is ambiguous, answer '
        'the most useful interpretation and note the alternative in one line.'
    ),
}


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-like frontmatter from markdown text.

    Returns (metadata_dict, body_text).
    """
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return {}, text
    # Find the closing ---
    end = stripped.find("---", 3)
    if end < 0:
        return {}, text
    fm_text = stripped[3:end].strip()
    body = stripped[end + 3:].lstrip("\n")

    meta: dict[str, Any] = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        colon = line.find(":")
        if colon < 0:
            continue
        key = line[:colon].strip()
        val_str = line[colon + 1:].strip()
        # Parse value
        if val_str.lower() in ("true", "yes"):
            meta[key] = True
        elif val_str.lower() in ("false", "no"):
            meta[key] = False
        elif val_str.startswith("[") or val_str.startswith("{"):
            try:
                meta[key] = json.loads(val_str)
            except json.JSONDecodeError:
                meta[key] = val_str
        elif val_str.startswith('"') and val_str.endswith('"'):
            meta[key] = val_str[1:-1]
        elif val_str.startswith("'") and val_str.endswith("'"):
            meta[key] = val_str[1:-1]
        else:
            meta[key] = val_str
    return meta, body


def _serialize_frontmatter(meta: dict[str, Any], body: str) -> str:
    """Serialize metadata and body into a frontmatter markdown file."""
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, bool):
            lines.append(f"{key}: {str(value).lower()}")
        elif isinstance(value, (list, dict)):
            lines.append(f"{key}: {json.dumps(value)}")
        elif isinstance(value, str) and (
            value.startswith("#") or ":" in value or value != value.strip()
        ):
            lines.append(f'{key}: "{value}"')
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n" + body


def _parse_agent_frontmatter(
    text: str, agent_id: str, path: Path
) -> AgentProfile | None:
    """Parse a frontmatter markdown file into an AgentProfile.

    Returns None if the file is malformed or the ID is invalid.
    """
    if not _AGENT_ID_RE.match(agent_id):
        return None
    try:
        meta, body = _parse_frontmatter(text)
        raw_usage = str(meta.get("usage", "")).strip().lower()
        if raw_usage in AGENT_USAGE_VALUES:
            usage = raw_usage
        elif bool(meta.get("subagent_only", False)):
            usage = "sub"
        else:
            usage = "both"
        # Parse tool_config from frontmatter if present
        raw_tc = meta.get("tool_config", {})
        tool_config: dict[str, ToolConfig] = {}
        if isinstance(raw_tc, dict):
            for tname, tval in raw_tc.items():
                if isinstance(tval, dict):
                    tool_config[tname] = ToolConfig(
                        policy=str(tval.get("policy", "auto")),
                        param_restrictions=dict(
                            tval.get("param_restrictions", {})
                        ),
                    )
        return AgentProfile(
            id=agent_id,
            name=str(meta.get("name", "") or agent_id),
            prompt=body,
            provider=str(meta.get("provider", "")),
            model=str(meta.get("model", "")),
            allowed_tools=[str(x) for x in meta.get("allowed_tools", [])],
            prompt_path=path,
            tool_config=tool_config,
            auto_approve_all=bool(meta.get("auto_approve_all", False)),
            usage=usage,
            color=str(meta.get("color", "")),
        )
    except Exception:
        return None


def _serialize_agent_frontmatter(profile: AgentProfile) -> str:
    """Convert an AgentProfile to a frontmatter markdown string."""
    meta: dict[str, Any] = {
        "name": profile.name,
        "usage": profile.usage,
    }
    if profile.color:
        meta["color"] = profile.color
    meta["allowed_tools"] = list(profile.allowed_tools)
    if profile.auto_approve_all:
        meta["auto_approve_all"] = profile.auto_approve_all
    if profile.provider:
        meta["provider"] = profile.provider
    if profile.model:
        meta["model"] = profile.model
    if profile.tool_config:
        meta["tool_config"] = {
            name: {
                "policy": tc.policy,
                "param_restrictions": tc.param_restrictions,
            }
            for name, tc in profile.tool_config.items()
        }
    return _serialize_frontmatter(meta, profile.prompt)


class SelfEditStore:
    """Disk persistence for self-edit artifacts."""

    PROJECT_DIR = Path(".taui")
    GLOBAL_DIR = Path.home() / ".taui"

    def __init__(self, working_dir: Path) -> None:
        self._working_dir = working_dir

    def dir_for_scope(self, scope: str) -> Path:
        if scope == "project":
            return self._working_dir / self.PROJECT_DIR
        return self.GLOBAL_DIR

    def _state_file(self) -> Path:
        return self._working_dir / self.PROJECT_DIR / "state.json"

    def _agent_prompt_file(self, scope: str, agent_id: str) -> Path:
        return self.dir_for_scope(scope) / "agents" / f"{agent_id}.md"

    def _agents_dir(self, scope: str) -> Path:
        return self.dir_for_scope(scope) / "agents"

    def load_default_scope(self) -> str:
        path = self._state_file()
        if not path.exists():
            return "global"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            scope = data.get("scope", "global")
            return "global" if scope == "global" else "project"
        except (OSError, json.JSONDecodeError):
            return "global"

    def save_default_scope(self, scope: str) -> None:
        out = self._state_file()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"scope": scope}, indent=2), encoding="utf-8")

    def ensure_default_agents(self) -> None:
        """Write default agent .md files to the global directory if missing."""
        agents_dir = self._agents_dir("global")
        agents_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in _DEFAULT_AGENT_FILES.items():
            path = agents_dir / filename
            if not path.exists():
                try:
                    path.write_text(content, encoding="utf-8")
                except OSError:
                    pass


    def load_agents(self) -> dict[str, AgentProfile]:
        """Load all agents from global and project scopes. Project overrides global."""
        self.ensure_default_agents()

        merged: dict[str, AgentProfile] = {}
        for scope in ("global", "project"):
            agents_dir = self._agents_dir(scope)
            if not agents_dir.is_dir():
                continue
            for md_path in sorted(agents_dir.glob("*.md")):
                agent_id = md_path.stem.upper()
                if not _AGENT_ID_RE.match(agent_id):
                    continue
                try:
                    text = md_path.read_text(encoding="utf-8")
                except OSError:
                    continue
                profile = _parse_agent_frontmatter(text, agent_id, md_path)
                if profile is not None:
                    merged[agent_id] = profile
        return merged

    def load_agents_for_scope(self, scope: str) -> dict[str, AgentProfile]:
        """Load agents from a single scope directory (no merging)."""
        agents_dir = self._agents_dir(scope)
        result: dict[str, AgentProfile] = {}
        if not agents_dir.is_dir():
            return result
        for md_path in sorted(agents_dir.glob("*.md")):
            agent_id = md_path.stem.upper()
            if not _AGENT_ID_RE.match(agent_id):
                continue
            try:
                text = md_path.read_text(encoding="utf-8")
            except OSError:
                continue
            profile = _parse_agent_frontmatter(text, agent_id, md_path)
            if profile is not None:
                result[agent_id] = profile
        return result

    def save_agent(self, profile: AgentProfile, scope: str) -> None:
        """Write an agent as a single frontmatter .md file."""
        agents_dir = self._agents_dir(scope)
        agents_dir.mkdir(parents=True, exist_ok=True)
        md_path = agents_dir / f"{profile.id}.md"
        content = _serialize_agent_frontmatter(profile)
        md_path.write_text(content, encoding="utf-8")

    def delete_agent(self, agent_id: str, scope: str) -> None:
        """Delete the agent .md file for the given scope."""
        normalized = agent_id.upper()
        md_path = self._agent_prompt_file(scope, normalized)
        if md_path.exists():
            try:
                md_path.unlink()
            except OSError:
                pass
