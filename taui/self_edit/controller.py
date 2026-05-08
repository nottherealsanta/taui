"""Verb parser and dispatcher for self-edit mode (v2)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from taui.config import Config
from taui.extensions import ExtensionRegistry
import taui.self_edit.listings as listings
from taui.self_edit.scaffolding import find_tool_source
from taui.self_edit.store import AgentProfile, ExtensionSource, SelfEditStore, ToolSource
from taui.skills import SkillRegistry

if TYPE_CHECKING:
    from taui.agent.loop import AgentLoop
    from taui.self_edit.panel import SelfEditPanel
    from taui.session import Session
    from taui.tui.app import TauiApp

logger = logging.getLogger(__name__)

PLAYBOOK_DIR = Path(__file__).parent / "playbooks"


@dataclass(slots=True)
class Selection:
    kind: str
    name: str


@dataclass(slots=True)
class PendingConfirm:
    """A pending one-shot confirmation (e.g. rm)."""

    verb: str
    kind: str
    name: str
    path: Path | None = None


@dataclass(slots=True)
class SelfEditSession:
    scope: str = "project"
    selection: Selection | None = None
    pending_confirm: PendingConfirm | None = None
    active_playbook: str | None = None
    previous_session_id: str | None = None
    activated_profile: AgentProfile | None = None
    specialist_loop: "AgentLoop | None" = None
    dirty_files: set[Path] = field(default_factory=set)


# Verbs allowed by kind for the user (selection-driven or typed-form).
_KIND_VERBS: dict[str, set[str]] = {
    "agent": {"show", "edit", "add", "rm", "delete", "activate"},
    "tool": {"show", "edit", "add", "rm", "delete"},
    "extension": {"show", "edit", "add", "rm", "delete"},
    "skill": {"show", "add"},
}

_ALWAYS_VERBS = {"scope", "reload", "help", "?", "cancel"}


class SelfEditController:
    """Parse self-edit verbs and perform their side effects."""

    def __init__(
        self,
        *,
        app: "TauiApp",
        session: "Session",
        config: Config,
        state: SelfEditSession,
        store: SelfEditStore | None = None,
    ) -> None:
        self._app = app
        self._session = session
        self._config = config
        self._state = state
        self._store = store or SelfEditStore(config.working_dir)
        self._panel: "SelfEditPanel | None" = None
        self._playbook_cache: dict[str, str] = {}

    # ── Public hooks ──────────────────────────────────────────────────

    def attach_panel(self, panel: "SelfEditPanel") -> None:
        self._panel = panel
        panel.set_scope(self._state.scope)
        panel.set_playbook(self._state.active_playbook)

    def on_panel_select(self, kind: str, name: str) -> None:
        self._state.selection = Selection(kind=kind, name=name)
        if self._panel is not None:
            self._panel.set_selection(kind, name)

    def set_scope(self, scope: str) -> str:
        """Update creation scope from a UI control."""
        return self._scope([scope])

    async def handle(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""

        # Pending rm confirmation consumes the next input.
        if self._state.pending_confirm is not None:
            return self._consume_confirm(text)

        # /q exits.
        if text == "/q":
            await self._app.action_exit_self_edit()
            return ""

        parts = text.split()
        verb = parts[0].lower()
        rest = parts[1:]

        if verb in ("help", "?"):
            return self._help_text()
        if verb == "cancel":
            return self._cancel()
        if verb == "scope":
            return self._scope(rest)
        if verb == "reload":
            return self.reload()

        kind_verbs = {"show", "edit", "add", "rm", "delete", "activate"}
        if verb in kind_verbs:
            target = self._resolve_target(verb, rest)
            if isinstance(target, str):
                return target

            if verb == "show":
                return self._show(target.kind, target.name)
            if verb in ("rm", "delete"):
                return self._rm(target.kind, target.name)
            if verb == "activate":
                if target.kind != "agent":
                    return "activate only applies to agents"
                return await self._activate(target.name)
            if verb == "add":
                return await self._begin_playbook("add", target.kind, target.name)
            if verb == "edit":
                return await self._begin_playbook("edit", target.kind, target.name)

        return f"unknown verb: {verb}\n\n{self._help_text()}"

    def build_completer(self):
        """Return a bare-word completer for ChatInput self-edit mode."""

        _VERB_HINTS: list[tuple[str, str]] = [
            ("show",     "print selection to chat"),
            ("edit",     "agent-assisted edit"),
            ("add",      "agent-assisted add"),
            ("rm",       "delete with confirm"),
            ("activate", "switch active agent"),
            ("scope",    "set creation scope"),
            ("reload",   "hot-reload extensions"),
            ("help",     "verb reference"),
            ("cancel",   "clear playbook / cancel"),
        ]
        _KINDS: list[tuple[str, str]] = [
            ("agent",     "agent profiles"),
            ("tool",      "registered tools"),
            ("extension", "extension files"),
            ("skill",     "skill bundles"),
        ]
        _VERB_KINDS: dict[str, set[str]] = {
            "show":     {"agent", "tool", "extension", "skill"},
            "edit":     {"agent", "tool", "extension"},
            "add":      {"agent", "tool", "extension", "skill"},
            "rm":       {"agent", "tool", "extension", "skill"},
            "activate": {"agent"},
        }

        def _names_for_kind(kind: str) -> list[tuple[str, str]]:
            if kind == "agent":
                return [
                    (a.id, a.name)
                    for a in self._store.load_agents().values()
                ]
            if kind == "tool":
                return [(n, "") for n in sorted(self._session._registry.names)]
            if kind == "extension":
                exts = self._discover_extensions()
                return [(n, ext.scope) for n, ext in sorted(exts.items())]
            if kind == "skill":
                reg = SkillRegistry(self._config.working_dir)
                reg.discover()
                return [(s.name, s.scope) for s in reg.list_all()]
            return []

        def completer(text: str) -> list[tuple[str, str, bool]]:
            parts = text.split()
            ends_space = text.endswith(" ")

            # Nothing typed yet → all verbs.
            if not parts:
                return [(v, d, True) for v, d in _VERB_HINTS]

            verb = parts[0].lower()

            # Still typing the verb (no space yet).
            if len(parts) == 1 and not ends_space:
                return [
                    (v, d, True) for v, d in _VERB_HINTS if v.startswith(verb)
                ]

            # Verb complete, no kind yet.
            allowed_kinds = _VERB_KINDS.get(verb)
            if allowed_kinds is None:
                return []  # verb like scope/reload doesn't take kind

            if len(parts) == 1 and ends_space:
                return [
                    (k, d, True) for k, d in _KINDS if k in allowed_kinds
                ]

            kind_raw = parts[1].lower()

            # Still typing the kind.
            if len(parts) == 2 and not ends_space:
                return [
                    (k, d, True) for k, d in _KINDS
                    if k in allowed_kinds and k.startswith(kind_raw)
                ]

            # Normalise kind (strip trailing 's').
            kind = kind_raw.rstrip("s")
            if kind not in allowed_kinds:
                return []

            names = _names_for_kind(kind)

            # Kind complete, no name yet.
            if len(parts) == 2 and ends_space:
                return [(n, d, True) for n, d in names]

            # Typing the name.
            partial = parts[2].lower() if len(parts) >= 3 else ""
            if not ends_space:
                return [
                    (n, d, True) for n, d in names if n.lower().startswith(partial)
                ]
            return []

        return completer

    def reload(self) -> str:
        try:
            loaded = self._session.reload_extensions()
        except Exception as exc:
            logger.exception("reload_extensions failed")
            return f"reload failed: {exc}"
        self._app._wire_callbacks()
        self._app._update_status()
        if self._panel is not None:
            self._panel.refresh_inventory()
        errors = self._extension_errors()
        if errors:
            joined = "; ".join(f"{name}: {msg}" for name, msg in errors)
            return f"reloaded with errors — {joined}"
        if loaded:
            return f"reloaded {len(loaded)} extension(s): {', '.join(loaded)}"
        return "reloaded extensions"

    def _extension_errors(self) -> list[tuple[str, str]]:
        """Collect any per-extension errors from the session registry."""
        registry = getattr(self._session, "_ext_registry", None)
        if registry is None:
            return []
        errors: list[tuple[str, str]] = []
        for ext in registry.list_all():
            if ext.error:
                errors.append((ext.name, ext.error))
        return errors

    def reset_specialist_history(self) -> None:
        """Clear specialist message history (for `/new` while in mode)."""
        loop = self._state.specialist_loop
        if loop is None:
            return
        loop._messages = []
        # Keep playbook + selection.

    def specialist_system_prompt(self) -> str:
        return self._compose_system_prompt()

    # ── Verb resolution ──────────────────────────────────────────────

    def _resolve_target(self, verb: str, rest: list[str]) -> Selection | str:
        """Return a Selection for verbs that need one, or an error string."""
        if verb in _ALWAYS_VERBS:
            # These verbs don't need a selection; caller handles them above.
            return Selection(kind="", name="")

        # Typed form: `verb kind [name]`.
        if rest:
            kind = self._normalize_kind(rest[0])
            if kind is None:
                return f"unknown kind: {rest[0]}"
            if kind not in _KIND_VERBS or verb not in _KIND_VERBS[kind]:
                return f"verb `{verb}` does not apply to {kind}"
            if len(rest) >= 2:
                name = " ".join(rest[1:])
                return Selection(kind=kind, name=name)
            # `add tool` — kind only is allowed for `add`.
            if verb == "add":
                return Selection(kind=kind, name="")
            return f"select a row first or type `{verb} {kind} <name>`"

        # Fall back to selection.
        sel = self._state.selection
        if sel is None:
            return f"select a row first or type `{verb} <kind> [name]`"
        if verb not in _KIND_VERBS.get(sel.kind, set()):
            return f"verb `{verb}` does not apply to {sel.kind}"
        return sel

    def _normalize_kind(self, raw: str) -> str | None:
        raw = raw.lower()
        for kind in ("agent", "tool", "extension", "skill"):
            if raw == kind or raw == f"{kind}s":
                return kind
        return None

    # ── Direct verbs ─────────────────────────────────────────────────

    def _scope(self, rest: list[str]) -> str:
        if len(rest) != 1:
            return "usage: scope project | scope global"
        scope = rest[0].lower()
        if scope not in ("project", "global"):
            return "scope must be `project` or `global`"
        self._state.scope = scope
        self._store.save_default_scope(scope)
        if self._panel is not None:
            self._panel.set_scope(scope)
        return f"creation scope set to {scope}"

    def _cancel(self) -> str:
        if self._state.pending_confirm is not None:
            self._state.pending_confirm = None
            return "cancelled"
        if self._state.active_playbook is not None:
            self._state.active_playbook = None
            self._sync_specialist_prompt()
            if self._panel is not None:
                self._panel.set_playbook(None)
            return "cleared active playbook"
        return "nothing to cancel"

    def _help_text(self) -> str:
        sel = self._state.selection
        if sel is not None:
            applicable = sorted(_KIND_VERBS.get(sel.kind, set()))
            sel_line = f"selected: {sel.kind} {sel.name}"
        else:
            applicable = sorted({v for verbs in _KIND_VERBS.values() for v in verbs})
            sel_line = "selected: -"
        always = sorted(_ALWAYS_VERBS) + ["/new", "/q"]
        return "\n".join(
            [
                "self-edit verbs",
                sel_line,
                "  applicable: " + ", ".join(applicable),
                "  always:     " + ", ".join(always),
                "",
                "Verbs apply to the panel's selected row, or use",
                "`<verb> <kind> [name]` to target explicitly.",
            ]
        )

    # ── show ─────────────────────────────────────────────────────────

    def _show(self, kind: str, name: str) -> str:
        if kind == "agent":
            return self._show_agent(name)
        if kind == "tool":
            return self._show_tool(name)
        if kind == "extension":
            return self._show_extension(name)
        if kind == "skill":
            return self._show_skill(name)
        return f"can't show {kind}"

    def _show_agent(self, agent_id: str) -> str:
        agent = self._store.load_agents().get(agent_id.upper())
        if agent is None:
            return f"unknown agent: {agent_id}"
        return listings.agent_detail(agent)

    def _show_tool(self, name: str) -> str:
        if name not in self._session._registry.names:
            return f"unknown tool: {name}"
        source = self._discover_tool_sources().get(name)
        if source and source.path:
            try:
                content = source.path.read_text(encoding="utf-8")
            except OSError as exc:
                return f"error reading {source.path}: {exc}"
            return f"# {source.path}\n```python\n{content}\n```"
        return listings.tool_detail(name, source, self._session._registry)

    def _show_extension(self, name: str) -> str:
        ext = self._discover_extensions().get(name)
        if ext is None:
            return f"unknown extension: {name}"
        if ext.path:
            try:
                content = ext.path.read_text(encoding="utf-8")
            except OSError as exc:
                return f"error reading {ext.path}: {exc}"
            return f"# {ext.path}\n```python\n{content}\n```"
        return listings.extension_detail(ext)

    def _show_skill(self, name: str) -> str:
        registry = SkillRegistry(self._config.working_dir)
        registry.discover()
        skill = registry.get(name)
        if skill is None:
            return f"unknown skill: {name}"
        try:
            content = skill.skill_file.read_text(encoding="utf-8")
        except OSError as exc:
            return f"error reading {skill.skill_file}: {exc}"
        return f"# {skill.skill_file}\n```markdown\n{content}\n```"

    # ── rm ───────────────────────────────────────────────────────────

    def _rm(self, kind: str, name: str) -> str:
        path = self._target_path(kind, name)
        if path is None:
            return f"can't delete {kind} {name}: built-in or unknown"
        if not path.exists():
            return f"path does not exist: {path}"
        self._state.pending_confirm = PendingConfirm(
            verb="rm", kind=kind, name=name, path=path
        )
        return f"delete {path}? type 'yes' to confirm."

    def _consume_confirm(self, text: str) -> str:
        confirm = self._state.pending_confirm
        assert confirm is not None
        self._state.pending_confirm = None
        if text.strip().lower() != "yes":
            return "cancelled"
        if confirm.verb == "rm":
            return self._do_delete(confirm.kind, confirm.name, confirm.path)
        return "cancelled"

    def _do_delete(self, kind: str, name: str, path: Path | None) -> str:
        if path is None:
            return f"missing path for {kind} {name}"
        try:
            if kind == "agent":
                self._delete_agent_row(name)
            path.unlink(missing_ok=True)
        except OSError as exc:
            return f"failed to delete {path}: {exc}"
        # Drop selection if it pointed at this row.
        sel = self._state.selection
        if sel is not None and sel.kind == kind and sel.name == name:
            self._state.selection = None
            if self._panel is not None:
                self._panel.set_selection(None, None)
        if self._panel is not None:
            self._panel.refresh_inventory()
        return f"deleted {path}"

    def _delete_agent_row(self, agent_id: str) -> None:
        import json
        for scope in ("project", "global"):
            agents_file = self._store._agents_file(scope)
            if not agents_file.exists():
                continue
            try:
                data = json.loads(agents_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            rows = list(data.get("profiles", []))
            new_rows = [
                r for r in rows
                if str(r.get("id", "")).upper() != agent_id.upper()
            ]
            if len(new_rows) != len(rows):
                data["profiles"] = new_rows
                try:
                    agents_file.write_text(
                        json.dumps(data, indent=2), encoding="utf-8"
                    )
                except OSError:
                    pass

    def _target_path(self, kind: str, name: str) -> Path | None:
        if kind == "agent":
            agent = self._store.load_agents().get(name.upper())
            if agent is None or agent.prompt_path is None:
                return None
            return agent.prompt_path
        if kind == "tool":
            if name in getattr(self._session, "_builtin_tool_names", set()):
                return None
            source = self._discover_tool_sources().get(name)
            return source.path if source and source.path else None
        if kind == "extension":
            ext = self._discover_extensions().get(name)
            return ext.path if ext and ext.path else None
        if kind == "skill":
            registry = SkillRegistry(self._config.working_dir)
            registry.discover()
            skill = registry.get(name)
            return skill.skill_file if skill else None
        return None

    # ── activate ─────────────────────────────────────────────────────

    async def _activate(self, agent_id: str) -> str:
        profile = self._store.load_agents().get(agent_id.upper())
        if profile is None:
            return f"unknown agent: {agent_id}"
        registry = self._session._registry
        if profile.allowed_tools:
            missing = sorted(set(profile.allowed_tools) - set(registry.names))
            if missing:
                return f"unknown tools for {profile.id}: {', '.join(missing)}"
        if profile.provider:
            self._config.provider = profile.provider
        if profile.model:
            self._config.model = profile.model
        self._config.system_prompt = profile.prompt
        self._session.config = self._config
        self._state.activated_profile = profile
        return f"activated agent {profile.id} (resumes on /q)"

    # ── add / edit playbook swap ─────────────────────────────────────

    async def _begin_playbook(self, verb: str, kind: str, name: str) -> str:
        playbook_name = f"{verb}_{kind}"
        playbook_text = self._load_playbook(playbook_name)
        if playbook_text is None:
            return f"no playbook for {verb} {kind} yet"

        if verb == "edit" and kind == "tool":
            if name and name in getattr(self._session, "_builtin_tool_names", set()):
                # Built-in: nudge user toward add_tool instead.
                return (
                    f"{name} is a built-in tool and is read-only. "
                    "Mirror it as a project extension with `add tool` instead."
                )

        self._state.active_playbook = playbook_name
        self._sync_specialist_prompt()
        if self._panel is not None:
            self._panel.set_playbook(playbook_name)
        target = f"{kind} {name}".strip()
        return (
            f"playbook `{playbook_name}` active"
            + (f" for {target}" if target else "")
            + " — describe what you want; I'll do the work."
        )

    def _sync_specialist_prompt(self) -> None:
        loop = self._state.specialist_loop
        if loop is None:
            return
        prompt = self._compose_system_prompt()
        loop._system_prompt = prompt
        # Replace any leading system message in the running history.
        if loop._messages and loop._messages[0].role == "system":
            loop._messages[0] = type(loop._messages[0])(
                role="system", content=prompt
            )

    def _compose_system_prompt(self) -> str:
        base = self._load_playbook("base") or ""
        if self._state.active_playbook:
            extra = self._load_playbook(self._state.active_playbook) or ""
            if extra:
                return f"{base}\n\n---\n\n{extra}"
        return base

    def _load_playbook(self, name: str) -> str | None:
        if name in self._playbook_cache:
            return self._playbook_cache[name]
        path = PLAYBOOK_DIR / f"{name}.md"
        if not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        self._playbook_cache[name] = text
        return text

    # ── Discovery helpers ────────────────────────────────────────────

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
