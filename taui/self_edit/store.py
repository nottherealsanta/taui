"""Persistence and source discovery models for self-edit mode."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_AGENT_ID_RE = re.compile(r"^[A-Z]{3}$")


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


_DEFAULT_AGENTS = [
    AgentProfile(
        id="DEF",
        name="Default",
        prompt="You are a pragmatic software engineer. Make scoped changes and verify them.",
        provider="",
        model="",
        allowed_tools=[],
    ),
    AgentProfile(
        id="PLN",
        name="Planner",
        prompt=(
            "You are PLN, a planning agent. Investigate the task and produce a "
            "clear, actionable implementation plan. Do not write or edit code — "
            "only read, search, and reason.\n\n"
            "Return a plan with: (1) Goal — one sentence restating what is being "
            "built; (2) Key files — paths (with line numbers when useful); "
            "(3) Steps — an ordered list of concrete edits or actions; "
            "(4) Risks / open questions — anything ambiguous or worth confirming.\n\n"
            "Prefer file_path:line_number references over prose. Stop as soon as "
            "the plan is solid — do not pad."
        ),
        provider="",
        model="",
        allowed_tools=["read", "glob", "grep"],
    ),
]


class SelfEditStore:
    """Disk persistence for self-edit artifacts."""

    PROJECT_DIR = Path(".taui/self_edit")
    GLOBAL_DIR = Path.home() / ".taui" / "self_edit"

    def __init__(self, working_dir: Path) -> None:
        self._working_dir = working_dir

    def dir_for_scope(self, scope: str) -> Path:
        if scope == "project":
            return self._working_dir / self.PROJECT_DIR
        return self.GLOBAL_DIR

    def _state_file(self) -> Path:
        return self._working_dir / self.PROJECT_DIR / "state.json"

    def _agents_file(self, scope: str) -> Path:
        return self.dir_for_scope(scope) / "agents.json"

    def _agent_prompt_file(self, scope: str, agent_id: str) -> Path:
        return self.dir_for_scope(scope) / "agents" / f"{agent_id}.md"

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

    def ensure_default_prompts(self) -> None:
        for profile in _DEFAULT_AGENTS:
            path = self._agent_prompt_file("project", profile.id)
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(profile.prompt, encoding="utf-8")

    def load_agents(self) -> dict[str, AgentProfile]:
        self.ensure_default_prompts()
        merged = {a.id: self._default_with_path(a) for a in _DEFAULT_AGENTS}
        for scope in ("global", "project"):
            path = self._agents_file(scope)
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            changed = False
            rows = list(data.get("profiles", []))
            for row in rows:
                profile, migrated = self._agent_from_row(row, scope)
                changed = changed or migrated
                if profile is not None:
                    merged[profile.id] = profile
            if changed:
                data["profiles"] = rows
                try:
                    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                except OSError:
                    pass
        return merged

    def save_agent(self, profile: AgentProfile, scope: str) -> None:
        path = self._agents_file(scope)
        path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path = profile.prompt_path or self._agent_prompt_file(scope, profile.id)
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(profile.prompt, encoding="utf-8")

        data = {"profiles": []}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {"profiles": []}

        row = self._agent_to_row(profile, prompt_path)
        rows = list(data.get("profiles", []))
        for index, existing in enumerate(rows):
            if str(existing.get("id", "")).upper() == profile.id:
                rows[index] = row
                break
        else:
            rows.append(row)
        data["profiles"] = rows
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def delete_agent(self, agent_id: str, scope: str) -> None:
        """Delete a saved agent row and prompt file for the given scope."""
        normalized = agent_id.upper()
        path = self._agents_file(scope)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {"profiles": []}
            rows = [
                row
                for row in list(data.get("profiles", []))
                if str(row.get("id", "")).upper() != normalized
            ]
            data["profiles"] = rows
            try:
                path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except OSError:
                pass

        prompt_path = self._agent_prompt_file(scope, normalized)
        if prompt_path.exists():
            prompt_path.unlink()

    def _default_with_path(self, profile: AgentProfile) -> AgentProfile:
        prompt_path = self._agent_prompt_file("project", profile.id)
        prompt = profile.prompt
        try:
            prompt = prompt_path.read_text(encoding="utf-8")
        except OSError:
            pass
        return AgentProfile(
            id=profile.id,
            name=profile.name,
            prompt=prompt,
            provider=profile.provider,
            model=profile.model,
            allowed_tools=list(profile.allowed_tools),
            prompt_path=prompt_path,
            tool_config={},
        )

    def _agent_from_row(self, row: Any, scope: str) -> tuple[AgentProfile | None, bool]:
        if not isinstance(row, dict):
            return None, False
        try:
            agent_id = str(row["id"]).upper()
            if not _AGENT_ID_RE.match(agent_id):
                return None, False
            prompt_path_raw = str(row.get("prompt_path", "")).strip()
            inline_prompt = str(row.get("prompt", ""))
            migrated = False
            if not prompt_path_raw:
                prompt_path = self._agent_prompt_file(scope, agent_id)
                if inline_prompt:
                    try:
                        prompt_path.parent.mkdir(parents=True, exist_ok=True)
                        if not prompt_path.exists():
                            prompt_path.write_text(inline_prompt, encoding="utf-8")
                        row["prompt_path"] = str(prompt_path)
                        row.pop("prompt", None)
                        migrated = True
                    except OSError:
                        prompt_path = None
                else:
                    prompt_path = None
            else:
                prompt_path = Path(prompt_path_raw)
                if not prompt_path.is_absolute():
                    prompt_path = self.dir_for_scope(scope) / prompt_path
            prompt = inline_prompt
            if prompt_path is not None:
                try:
                    prompt = prompt_path.read_text(encoding="utf-8")
                except OSError:
                    pass
            raw_tc = row.get("tool_config", {})
            tool_config: dict[str, ToolConfig] = {}
            if isinstance(raw_tc, dict):
                for tname, tval in raw_tc.items():
                    if isinstance(tval, dict):
                        tool_config[tname] = ToolConfig(
                            policy=str(tval.get("policy", "auto")),
                            param_restrictions=dict(tval.get("param_restrictions", {})),
                        )
            return (
                AgentProfile(
                    id=agent_id,
                    name=str(row.get("name", "")) or agent_id,
                    prompt=prompt,
                    provider=str(row.get("provider", "")),
                    model=str(row.get("model", "")),
                    allowed_tools=[str(x) for x in row.get("allowed_tools", [])],
                    prompt_path=prompt_path,
                    tool_config=tool_config,
                ),
                migrated,
            )
        except (KeyError, TypeError, ValueError):
            return None, False

    @staticmethod
    def _agent_to_row(profile: AgentProfile, prompt_path: Path) -> dict[str, Any]:
        return {
            "id": profile.id,
            "name": profile.name,
            "provider": profile.provider,
            "model": profile.model,
            "allowed_tools": list(profile.allowed_tools),
            "prompt_path": str(prompt_path),
            "tool_config": {
                name: {"policy": tc.policy, "param_restrictions": tc.param_restrictions}
                for name, tc in profile.tool_config.items()
            },
        }
