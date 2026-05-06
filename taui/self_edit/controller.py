"""Verb parser and dispatcher for chat-layer self-edit mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from taui.agent.loop import AgentLoop
from taui.config import Config
from taui.extensions import ExtensionRegistry
import taui.self_edit.listings as listings
from taui.self_edit.modal import ConfigEditModal, FileEditModal
from taui.self_edit.scaffolding import (
    NewExtensionRequest,
    NewToolRequest,
    agent_id_from_prompt,
    agent_prompt_from_request,
    extension_template,
    find_tool_source,
    infer_tool_category,
    scope_extension_base,
    slug,
    slug_from_prompt,
    summary_from_prompt,
    title_from_prompt,
    tool_extension_template,
    unique_path,
)
from taui.self_edit.store import AgentProfile, ExtensionSource, SelfEditStore, ToolSource
from taui.skills import SkillRegistry
from taui.tools.executor import ToolExecutor

if TYPE_CHECKING:
    from taui.session import Session
    from taui.tui.app import TauiApp


@dataclass(slots=True)
class PendingCreation:
    kind: str


@dataclass(slots=True)
class SelfEditSession:
    scope: str = "project"
    pending_creation: PendingCreation | None = None
    dirty_files: set[Path] = field(default_factory=set)


class SelfEditController:
    """Parse self-edit verbs and perform their side effects."""

    def __init__(
        self,
        *,
        app: TauiApp,
        session: Session,
        config: Config,
        state: SelfEditSession,
        store: SelfEditStore | None = None,
    ) -> None:
        self._app = app
        self._session = session
        self._config = config
        self._state = state
        self._store = store or SelfEditStore(config.working_dir)

    async def handle(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        if self._state.pending_creation is not None and text != "cancel":
            return self._complete_creation(text)

        parts = text.split()
        verb = parts[0].lower()
        rest = parts[1:]

        if text == "/q":
            await self._app.action_exit_self_edit()
            return ""
        if verb in ("help", "?"):
            return listings.help_text()
        if verb == "cancel":
            return self._cancel()
        if verb == "agents" and not rest:
            return listings.agents_listing(self._store.load_agents(), scope=self._state.scope)
        if verb == "agent" and len(rest) == 1:
            return self._agent_detail(rest[0])
        if verb == "tools" and not rest:
            return listings.tools_listing(self._discover_tool_sources(), self._session._registry)
        if verb == "tool" and len(rest) == 1:
            return self._tool_detail(rest[0])
        if verb == "extensions" and not rest:
            return listings.extensions_listing(self._discover_extensions())
        if verb == "extension" and len(rest) == 1:
            return self._extension_detail(rest[0])
        if verb == "skills" and not rest:
            return self._skills()
        if verb == "config" and not rest:
            return listings.config_listing(self._config)
        if verb == "scope" and len(rest) == 1:
            return self._set_scope(rest[0])
        if verb == "reload" and not rest:
            return self.reload()
        if verb == "new" and len(rest) == 1:
            return self._begin_creation(rest[0])
        if verb == "edit":
            return self._edit(rest)
        if verb == "activate" and len(rest) == 1:
            return await self._activate(rest[0])

        return f"unknown self-edit verb: {text}\n\n{listings.help_text()}"

    def reload(self) -> str:
        loaded = self._session.reload_extensions()
        self._app._wire_callbacks()
        self._app._update_status()
        if loaded:
            return f"reloaded {len(loaded)} extension(s): {', '.join(loaded)}"
        return "reloaded extensions"

    def summary(self) -> str:
        """Return a local inventory summary without invoking the LLM."""
        agents = self._store.load_agents()
        tools = self._discover_tool_sources()
        extensions = self._discover_extensions()
        skill_registry = SkillRegistry(self._config.working_dir)
        skill_registry.discover()

        lines = [
            f"## Self-Edit Mode",
            "",
            f"Scope: `{self._state.scope}`",
            "",
            f"### Agents ({len(agents)})",
            "",
            "| ID | Name | Model | Prompt |",
            "| --- | --- | --- | --- |",
        ]
        for agent_id, profile in sorted(agents.items()):
            model = " / ".join(x for x in (profile.provider, profile.model) if x)
            prompt_path = str(profile.prompt_path) if profile.prompt_path else "inline"
            lines.append(
                "| "
                f"`{_md_cell(agent_id)}` | "
                f"{_md_cell(profile.name)} | "
                f"{_md_cell(model or 'inherit')} | "
                f"`{_md_cell(prompt_path)}` |"
            )

        lines.extend(
            [
                "",
                f"### Tools ({len(self._session._registry.names)})",
                "",
                "| Name | Category | Source |",
                "| --- | --- | --- |",
            ]
        )
        for name in self._session._registry.names:
            source = tools.get(name)
            tool = self._session._registry.get(name)
            source_text = str(source.path) if source and source.path else "built-in"
            lines.append(
                "| "
                f"`{_md_cell(name)}` | "
                f"{_md_cell(tool.category.value)} | "
                f"{_md_cell(source_text)} |"
            )

        skills = skill_registry.list_all()
        lines.extend(
            [
                "",
                f"### Skills ({len(skills)})",
                "",
                "| Name | Scope | Path |",
                "| --- | --- | --- |",
            ]
        )
        if not skills:
            lines.append("| none | - | - |")
        for skill in skills:
            lines.append(
                "| "
                f"`{_md_cell(skill.name)}` | "
                f"{_md_cell(skill.scope)} | "
                f"{_md_cell(str(skill.path))} |"
            )

        lines.extend(
            [
                "",
                f"### Extensions ({len(extensions)})",
                "",
                "| Name | Scope | Status | Path |",
                "| --- | --- | --- | --- |",
            ]
        )
        for name, ext in sorted(extensions.items()):
            status = "error" if ext.error else ("loaded" if ext.loaded else "not loaded")
            path = str(ext.path) if ext.path else "built-in"
            lines.append(
                "| "
                f"`{_md_cell(name)}` | "
                f"{_md_cell(ext.scope)} | "
                f"{_md_cell(status)} | "
                f"{_md_cell(path)} |"
            )

        lines.extend(["", "Type `help` for verbs. `/q` exits and reloads."])
        return "\n".join(lines)

    def _cancel(self) -> str:
        if self._state.pending_creation is None:
            return "nothing to cancel"
        self._state.pending_creation = None
        return "cancelled"

    def _set_scope(self, scope: str) -> str:
        if scope not in ("project", "global"):
            return "scope must be `project` or `global`"
        self._state.scope = scope
        self._store.save_default_scope(scope)
        return f"creation scope set to {scope}"

    def _agent_detail(self, agent_id: str) -> str:
        agent = self._store.load_agents().get(agent_id.upper())
        if agent is None:
            return f"unknown agent: {agent_id}"
        return listings.agent_detail(agent)

    def _tool_detail(self, name: str) -> str:
        if name not in self._session._registry.names:
            return f"unknown tool: {name}"
        return listings.tool_detail(
            name,
            self._discover_tool_sources().get(name),
            self._session._registry,
        )

    def _extension_detail(self, name: str) -> str:
        ext = self._discover_extensions().get(name)
        if ext is None:
            return f"unknown extension: {name}"
        return listings.extension_detail(ext)

    def _skills(self) -> str:
        registry = SkillRegistry(self._config.working_dir)
        registry.discover()
        return listings.skills_listing(registry.list_all())

    def _begin_creation(self, kind: str) -> str:
        if kind not in ("agent", "tool", "extension"):
            return "can only create `agent`, `tool`, or `extension`"
        self._state.pending_creation = PendingCreation(kind=kind)
        return f"enter prompt for new {kind} (or `cancel`):"

    def _complete_creation(self, prompt: str) -> str:
        pending = self._state.pending_creation
        if pending is None:
            return "nothing pending"
        self._state.pending_creation = None
        if pending.kind == "agent":
            return self._create_agent(prompt)
        if pending.kind == "tool":
            return self._create_tool(prompt)
        if pending.kind == "extension":
            return self._create_extension(prompt)
        return "unknown pending creation"

    def _create_agent(self, prompt: str) -> str:
        agents = self._store.load_agents()
        agent_id = agent_id_from_prompt(prompt, set(agents))
        profile = AgentProfile(
            id=agent_id,
            name=title_from_prompt(prompt, agent_id),
            prompt=agent_prompt_from_request(prompt),
            provider="",
            model="",
            allowed_tools=[],
        )
        self._store.save_agent(profile, self._state.scope)
        saved = self._store.load_agents()[agent_id]
        return f"created agent {agent_id} at {saved.prompt_path}"

    def _create_tool(self, prompt: str) -> str:
        name = slug(slug_from_prompt(prompt, "custom_tool"), "custom_tool")
        category = infer_tool_category(prompt)
        request = NewToolRequest(
            name=name,
            description=summary_from_prompt(prompt, f"{name} tool"),
            category=category,
            prompt=prompt,
        )
        base = scope_extension_base(self._config.working_dir, self._state.scope)
        path = unique_path(base, f"tool_{name}", ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tool_extension_template(request), encoding="utf-8")
        return f"created tool scaffold {name} at {path}"

    def _create_extension(self, prompt: str) -> str:
        name = slug(slug_from_prompt(prompt, "custom_extension"), "custom_extension")
        request = NewExtensionRequest(name=name, prompt=prompt)
        base = scope_extension_base(self._config.working_dir, self._state.scope)
        path = unique_path(base, name, ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(extension_template(request), encoding="utf-8")
        return f"created extension scaffold {name} at {path}"

    def _edit(self, rest: list[str]) -> str:
        if len(rest) != 2 and rest != ["config"]:
            return "usage: edit agent <ID> | edit tool <name> | edit extension <name> | edit config"
        if rest == ["config"]:
            self._app.push_screen(ConfigEditModal(self._config), callback=self._config_saved)
            return "opened config editor"
        kind, name = rest
        if kind == "agent":
            return self._edit_agent(name)
        if kind == "tool":
            return self._edit_tool(name)
        if kind == "extension":
            return self._edit_extension(name)
        return f"unknown edit target: {kind}"

    def _edit_agent(self, agent_id: str) -> str:
        agent = self._store.load_agents().get(agent_id.upper())
        if agent is None:
            return f"unknown agent: {agent_id}"
        if agent.prompt_path is None:
            return f"agent {agent.id} has no prompt file"
        self._open_file(agent.prompt_path, language="markdown")
        return f"opened {agent.prompt_path}"

    def _edit_tool(self, name: str) -> str:
        if name not in self._session._registry.names:
            return f"unknown tool: {name}"
        source = self._discover_tool_sources().get(name)
        if source and source.path:
            self._open_file(source.path, language="python")
            return f"opened {source.path}"
        self._open_read_only_source(f"{name}.txt", "Built-in tools are read-only in self-edit.\n")
        return f"{name} is built-in and read-only"

    def _edit_extension(self, name: str) -> str:
        ext = self._discover_extensions().get(name)
        if ext is None:
            return f"unknown extension: {name}"
        if ext.path:
            self._open_file(ext.path, language="python")
            return f"opened {ext.path}"
        self._open_read_only_source(f"{name}.txt", listings.extension_detail(ext))
        return f"{name} is built-in and read-only"

    async def _activate(self, agent_id: str) -> str:
        profile = self._store.load_agents().get(agent_id.upper())
        if profile is None:
            return f"unknown agent: {agent_id}"
        registry = self._session._registry
        if profile.allowed_tools:
            missing = sorted(set(profile.allowed_tools) - set(registry.names))
            if missing:
                return f"unknown tools for {profile.id}: {', '.join(missing)}"
            registry = registry.subset(profile.allowed_tools)
        executor = ToolExecutor(registry=registry, policy=self._session._executor._policy)
        if profile.provider:
            self._config.provider = profile.provider
        if profile.model:
            self._config.model = profile.model
        self._config.system_prompt = profile.prompt
        self._session.config = self._config
        loop = AgentLoop(
            agent_id=profile.id,
            llm=self._session._provider,
            executor=executor,
            stream=self._session._stream,
            system_prompt=profile.prompt,
            model=self._config.model,
            max_turns=self._config.max_turns,
        )
        self._session._replace_loop(loop)
        self._app._wire_callbacks()
        self._app._update_status()
        return f"activated agent {profile.id}"

    def _open_file(self, path: Path, *, language: str | None) -> None:
        self._app.push_screen(
            FileEditModal(path, language=language),
            callback=lambda saved: self._file_saved(path, bool(saved)),
        )

    def _open_read_only_source(self, name: str, content: str) -> None:
        path = self._config.working_dir / ".taui" / "self_edit" / "readonly" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self._app.push_screen(FileEditModal(path, read_only=True))

    def _file_saved(self, path: Path, saved: bool) -> None:
        if saved:
            self._state.dirty_files.add(path)

    def _config_saved(self, config: Config | None) -> None:
        if config is None:
            return
        self._config = config
        self._session.config = config
        self._session._loop._model = config.model
        self._session._loop._max_turns = config.max_turns
        self._session._system_prompt = config.system_prompt

    def _discover_tool_sources(self) -> dict[str, ToolSource]:
        builtin = getattr(self._session, "_builtin_tool_names", set())
        extension_paths = self._extension_paths()
        sources: dict[str, ToolSource] = {}
        for name in self._session._registry.names:
            sources[name] = ToolSource(
                name=name,
                path=None if name in builtin else find_tool_source(name, extension_paths),
            )
        return sources

    def _extension_paths(self) -> list[Path]:
        paths: list[Path] = []
        for base in (
            Path.home() / ".taui" / "extensions",
            self._config.working_dir / ".taui" / "extensions",
        ):
            if base.is_dir():
                paths.extend(sorted(base.glob("*.py")))
        return paths

    def _discover_extensions(self) -> dict[str, ExtensionSource]:
        registry = ExtensionRegistry(self._config.working_dir, include_builtins=True)
        registry.discover()
        session_registry = getattr(self._session, "_ext_registry", None)
        if session_registry is not None:
            for session_ext in session_registry.list_all():
                ext = registry.get(session_ext.name)
                if ext is None:
                    continue
                ext.loaded = session_ext.loaded
                ext.error = session_ext.error
        return {
            ext.name: ExtensionSource(
                name=ext.name,
                path=ext.path,
                scope=ext.scope,
                description=ext.description,
                loaded=ext.loaded,
                error=ext.error,
            )
            for ext in registry.list_all()
        }


def _md_cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")
