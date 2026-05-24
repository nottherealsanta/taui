"""Built-in slash commands."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from taui.commands.git_workflows import (
    GitCommitCommand,
    GitDiffCommand,
    GitReviewCommand,
)
from taui.commands.registry import CommandContext, CommandRegistry, CommandResult


@dataclass(slots=True)
class HelpCommand:
    name: str = "help"
    description: str = "Show available commands"
    accepts_args: bool = False
    _registry: Any = None

    def set_registry(self, registry: CommandRegistry) -> None:
        self._registry = registry

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if self._registry is None:
            return CommandResult.ok("No command registry.")
        return CommandResult.ok(self._registry.help_text())


@dataclass(slots=True)
class CostCommand:
    name: str = "cost"
    description: str = "Show token usage and estimated cost"
    accepts_args: bool = False
    _get_tracker: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if self._get_tracker is None:
            return CommandResult.fail("Cost tracking not available.")
        tracker = self._get_tracker()
        return CommandResult.ok(tracker.summary())


@dataclass(slots=True)
class CompactCommand:
    name: str = "compact"
    description: str = "Compact conversation history"
    accepts_args: bool = False

    async def execute(self, ctx: CommandContext) -> CommandResult:
        return CommandResult.ok(
            "Compaction requested.",
            action="compact_requested",
        )


@dataclass(slots=True)
class ContextCommand:
    name: str = "context"
    description: str = "Show context tree"
    accepts_args: bool = False

    async def execute(self, ctx: CommandContext) -> CommandResult:
        return CommandResult.ok("", action="open_context_tree")


@dataclass(slots=True)
class ClearCommand:
    name: str = "clear"
    description: str = "Clear conversation history"
    accepts_args: bool = False
    _get_loop: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if self._get_loop:
            loop = self._get_loop()
            loop._messages.clear()
            return CommandResult.ok("Conversation cleared.")
        return CommandResult.fail("No active loop.")


@dataclass(slots=True)
class ModelCommand:
    name: str = "model"
    description: str = "Show, set, list, or select model interactively"
    accepts_args: bool = True
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")
        session = self._get_session()
        if not ctx.args:
            return CommandResult.ok(
                "", action="open_model_picker"
            )

        sub = ctx.args[0]
        if sub in ("list", "ls"):
            return self._list_models(session)
        if sub == "refresh":
            return self._list_models(session, force=True)
        if sub in ("select", "pick"):
            return self._interactive_select(session)

        # Set model
        provider = session.config.provider
        model = sub
        if "/" in sub:
            provider, model = sub.split("/", 1)
            if provider not in ("copilot", "codex") or not model:
                return CommandResult.fail(
                    "Usage: /model <id> or /model <provider>/<id>"
                )

        if provider != session.config.provider:
            return CommandResult.fail(
                f"Current provider is {session.config.provider}. "
                f"Use /provider {provider} before selecting {provider}/{model}."
            )

        session.config.model = model
        session._loop._model = model
        _reset_variant_if_unsupported(session)
        try:
            from taui.llm_provider.config import (
                save_last_agent_model,
                save_last_model,
            )
            save_last_model(session.config.provider, model)
            agent_id = str(getattr(session._loop, "agent_id", "") or "").upper()
            if agent_id:
                save_last_agent_model(agent_id, session.config.provider, model)
        except Exception:
            pass
        return CommandResult.ok(
            f"Model set to {model}",
            action="model_changed",
            model=model,
        )

    @staticmethod
    def _list_models(session, *, force: bool = False) -> CommandResult:
        from taui.llm_provider.models import list_models

        provider = session.config.provider
        models = list_models(provider, force_refresh=force)
        if not models:
            return CommandResult.ok(
                f"No models found for {provider}. "
                "Check connectivity or try /model refresh."
            )
        lines = [f"Models for {provider} (tool_call=true):"]
        for m in models[:20]:
            ctx_k = f"{m['context'] // 1000}k" if m["context"] else "?"
            current = " ◀" if m["id"] == session.config.model else ""
            tag = " reasoning" if m["reasoning"] else ""
            lines.append(f"  {m['id']:40s} {ctx_k:>6s}{tag}{current}")
        lines.append("")
        lines.append("Set: /model <id>  or  /model select")
        return CommandResult.ok("\n".join(lines))

    @staticmethod
    def _interactive_select(session) -> CommandResult:
        """Launch interactive model picker."""
        from taui.llm_provider.models import list_models, prompt_model_selection

        provider = session.config.provider
        models = list_models(provider)
        if not models:
            return CommandResult.fail(
                f"No models found for {provider}. Try /model refresh."
            )

        selected = prompt_model_selection(provider)
        session.config.model = selected
        session._loop._model = selected
        _reset_variant_if_unsupported(session)
        try:
            from taui.llm_provider.config import (
                save_last_agent_model,
                save_last_model,
            )
            save_last_model(provider, selected)
            agent_id = str(getattr(session._loop, "agent_id", "") or "").upper()
            if agent_id:
                save_last_agent_model(agent_id, provider, selected)
        except Exception:
            pass
        return CommandResult.ok(
            f"Model set to {selected}",
            action="model_changed",
            model=selected,
        )


def _reset_variant_if_unsupported(session: Any) -> None:
    """Clear ``model_variant`` if the new model does not accept it.

    Called after a model switch — keeps the persisted variant from leaking
    into a model that 400s on it.
    """
    current = str(getattr(session.config, "model_variant", "") or "")
    if not current:
        return
    try:
        from taui.llm_provider.models import get_model_variants

        allowed = get_model_variants(session.config.provider, session.config.model)
    except Exception:
        return
    if current not in allowed:
        session.config.model_variant = ""
        try:
            session._loop._model_variant = ""
        except Exception:
            pass


@dataclass(slots=True)
class AgentsCommand:
    """List or activate agent profiles."""

    name: str = "agents"
    description: str = "List or activate agents (/agents [ID])"
    accepts_args: bool = True
    _get_session: Any = None
    _get_store: Any = None
    _get_apply_profile: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if self._get_session is None:
            return CommandResult.fail("No session.")
        if self._get_store is None:
            return CommandResult.fail("Agent store not available.")

        session = self._get_session()
        store = self._get_store()
        all_agents = store.load_agents()
        # `/agents` only shows/activates main-mode agents — sub-agent-only
        # profiles are reachable through the `sub_agent` tool, not directly.
        agents = {aid: p for aid, p in all_agents.items() if not p.subagent_only}
        if not ctx.args:
            return CommandResult.ok(
                "", action="open_agent_picker"
            )
        if ctx.args[0].lower() in ("list", "ls"):
            return self._list_agents(session, agents)

        agent_id = ctx.args[0].upper()
        profile = agents.get(agent_id)
        if profile is None:
            available = ", ".join(sorted(agents)) or "(none)"
            return CommandResult.fail(
                f"Unknown agent: {agent_id}. Available: {available}"
            )
        if self._get_apply_profile is None:
            return CommandResult.fail("Agent activation not available.")

        self._get_apply_profile(profile)
        return CommandResult.ok(
            "",
            action="agent_activated",
            agent_id=profile.id,
        )

    @staticmethod
    def _list_agents(session: Any, agents: dict[str, Any]) -> CommandResult:
        if not agents:
            return CommandResult.ok("No agents found.")

        active_id = str(getattr(session._loop, "agent_id", "") or "").upper()
        lines = ["Agents:"]
        for profile in sorted(agents.values(), key=lambda item: item.id):
            marker = " ◀" if profile.id == active_id else ""
            provider_model = _profile_provider_model(profile)
            prompt_path = str(profile.prompt_path) if profile.prompt_path else "-"
            lines.append(
                f"  {profile.id:3s}  {profile.name:18s}  "
                f"{provider_model:28s}  {prompt_path}{marker}"
            )
        lines.append("")
        lines.append("Activate: /agents <ID>")
        return CommandResult.ok("\n".join(lines))


@dataclass(slots=True)
class SkillsCommand:
    """Open the inline skill picker, or list/toggle skills."""

    name: str = "skills"
    description: str = "List or toggle skills (/skills [name])"
    accepts_args: bool = True
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if self._get_session is None:
            return CommandResult.fail("No session.")
        session = self._get_session()
        reg = getattr(session, "_skill_registry", None)
        if reg is None:
            return CommandResult.fail("Skill registry not available.")
        skills = reg.list_all()

        if not ctx.args:
            return CommandResult.ok("", action="open_skill_picker_inline")
        if ctx.args[0].lower() in ("list", "ls"):
            return self._list_skills(skills)

        name = ctx.args[0]
        if reg.get(name) is None:
            available = ", ".join(s.name for s in skills) or "(none)"
            return CommandResult.fail(
                f"Unknown skill: {name}. Available: {available}"
            )
        return CommandResult.ok(
            "", action="skill_selected", skill_name=name,
        )

    @staticmethod
    def _list_skills(skills: list) -> CommandResult:
        if not skills:
            return CommandResult.ok("No skills found.")
        lines = ["Skills:"]
        for s in skills:
            marker = " ◀" if s.loaded else ""
            lines.append(f"  {s.name:<30s}  {s.scope}{marker}")
        lines.append("")
        lines.append("Toggle: /skills <name>")
        return CommandResult.ok("\n".join(lines))


@dataclass(slots=True)
class PromptsCommand:
    """Open the inline prompt picker, or list/run prompts."""

    name: str = "prompts"
    description: str = "List or run prompts (/prompts [identifier])"
    accepts_args: bool = True
    _get_session: Any = None
    _get_working_dir: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        from taui.self_edit.inventory import list_items

        wd = self._get_working_dir() if self._get_working_dir else None
        if wd is None and self._get_session is not None:
            wd = self._get_session().working_dir
        if wd is None:
            return CommandResult.fail("Working directory not available.")

        try:
            prompts = (
                list_items(wd, "prompts", "project")
                + list_items(wd, "prompts", "global")
            )
        except Exception as exc:
            return CommandResult.fail(f"Failed to load prompts: {exc}")

        if not ctx.args:
            return CommandResult.ok("", action="open_prompt_picker_inline")
        if ctx.args[0].lower() in ("list", "ls"):
            return self._list_prompts(prompts)

        identifier = ctx.args[0]
        if not any(getattr(p, "identifier", "") == identifier for p in prompts):
            available = ", ".join(
                getattr(p, "identifier", "") for p in prompts
            ) or "(none)"
            return CommandResult.fail(
                f"Unknown prompt: {identifier}. Available: {available}"
            )
        return CommandResult.ok(
            "", action="prompt_selected", prompt_id=identifier,
        )

    @staticmethod
    def _list_prompts(prompts: list) -> CommandResult:
        if not prompts:
            return CommandResult.ok("No prompts found.")
        lines = ["Prompts:"]
        for p in prompts:
            ident = getattr(p, "identifier", "") or ""
            summary = (getattr(p, "summary", "") or "")[:60]
            lines.append(f"  {ident:<30s}  {summary}")
        lines.append("")
        lines.append("Run: /prompts <identifier>")
        return CommandResult.ok("\n".join(lines))


def _profile_provider_model(profile: Any) -> str:
    provider = str(getattr(profile, "provider", "") or "")
    model = str(getattr(profile, "model", "") or "")
    if provider and model:
        return f"{provider}/{model}"
    if provider:
        return provider
    if model:
        return model
    return "-"


@dataclass(slots=True)
class SelfEditModeCommand:
    """Open the self-edit modal, or list the inventory as text."""

    name: str = "i"
    description: str = (
        "Open the self-edit modal · `/i list [category]` for text-mode listing"
    )
    accepts_args: bool = True

    async def execute(self, ctx: CommandContext) -> CommandResult:
        msg = " ".join(ctx.args).strip()
        return CommandResult.ok(msg, action="self_edit_open", message=msg)


@dataclass(slots=True)
class ExtensionsModeCommand:
    """Toggle extensions mode. Creates a new session with the extensions prompt."""

    name: str = "ext-mode"
    description: str = "Toggle extensions mode (yellow UI)"
    accepts_args: bool = False
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")

        session = self._get_session()
        is_on = await session.toggle_extensions_mode()
        if is_on:
            return CommandResult.ok("Extensions mode ON", action="extensions_on")
        return CommandResult.ok(
            "Extensions mode OFF — back to normal.",
            action="extensions_off",
        )


@dataclass(slots=True)
class SessionsCommand:
    """List recent sessions and request a frontend picker."""

    name: str = "sessions"
    description: str = "List sessions — interactive picker or /sessions <id>"
    accepts_args: bool = True
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")

        session = self._get_session()

        # If an arg is given, try to resume that session directly
        if ctx.args:
            target = ctx.args[0]
            ok = await session.resume_session(target)
            if ok:
                mode = " [extensions]" if session.extensions_mode else ""
                return CommandResult.ok(
                    f"Resumed session {target}{mode}",
                    action="session_resumed",
                    session_id=target,
                    extensions_mode=session.extensions_mode,
                )
            error = (
                getattr(session, "last_resume_error", "")
                or f"Session not found: {target}"
            )
            return CommandResult.fail(error)

        # List sessions — frontends can open a native picker from metadata.
        sessions = await session.list_sessions()
        if not sessions:
            return CommandResult.ok("No previous sessions.")

        result = self._format_session_list(sessions)
        result.metadata.update(
            action="session_picker",
            sessions=sessions[:20],
        )
        return result

    @staticmethod
    def _format_session_list(sessions: list[dict]) -> CommandResult:
        lines = ["Sessions:"]
        for s in sessions[:20]:
            sid = s["session_id"]
            desc = s.get("description", "") or _fallback_session_name(s)
            mode = s.get("mode", "normal")
            msgs = s.get("message_count", 0)
            ago = _time_ago(s.get("last_active", 0))
            mode_tag = " [extensions]" if mode == "extensions" else ""
            lines.append(
                f"  {sid}  {desc[:50]:50s}  {msgs:>3} msgs  {ago}{mode_tag}"
            )
        lines.append("")
        lines.append("Resume: /sessions <id>")
        return CommandResult.ok("\n".join(lines))


@dataclass(slots=True)
class NewSessionCommand:
    """Start a fresh session, optionally with an initial message."""

    name: str = "new"
    description: str = "Start a new session: /new [message]"
    accepts_args: bool = True
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")

        session = self._get_session()
        await session.new_session()
        mode = "extensions" if session.extensions_mode else "normal"
        initial_message = " ".join(ctx.args).strip()
        return CommandResult.ok(
            f"New session started ({mode}).",
            action="new_session",
            session_id=session.session_id,
            initial_message=initial_message,
        )


@dataclass(slots=True)
class ExtensionsCommand:
    name: str = "extensions"
    description: str = "List loaded extensions"
    accepts_args: bool = False
    _get_extensions: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_extensions:
            return CommandResult.fail("Extension system not available.")
        ext_registry = self._get_extensions()
        all_exts = ext_registry.list_all()
        if not all_exts:
            return CommandResult.ok(
                "No extensions found.\n"
                "Add .py files to .taui/extensions/ or ~/.taui/extensions/"
            )
        lines = [f"Extensions ({len(all_exts)}):"]
        for ext in all_exts:
            status = "loaded" if ext.loaded else ("error" if ext.error else "not loaded")
            lines.append(f"  {ext.name} [{ext.scope}] — {status}")
            if ext.error:
                lines.append(f"    error: {ext.error}")
        return CommandResult.ok("\n".join(lines))


@dataclass(slots=True)
class ReloadCommand:
    """Hot-reload extensions without restarting."""

    name: str = "reload"
    description: str = "Reload extensions"
    accepts_args: bool = False
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")

        session = self._get_session()
        try:
            loaded = session.reload_extensions()
        except Exception as exc:
            return CommandResult.fail(
                f"Reload failed: {exc}", action="reloaded",
            )

        # Collect errors from extensions that failed to load
        errors: list[str] = []
        ext_reg = getattr(session, "_ext_registry", None)
        if ext_reg:
            for ext in ext_reg._extensions.values():
                if ext.error and ext.scope != "builtin":
                    errors.append(f"  {ext.name}: {ext.error}")

        parts: list[str] = []
        if loaded:
            parts.append(f"Reloaded {len(loaded)} extension(s): {', '.join(loaded)}")
        else:
            parts.append("No extensions loaded.")
        if errors:
            parts.append(f"Errors ({len(errors)}):\n" + "\n".join(errors))

        return CommandResult.ok("\n".join(parts), action="reloaded")


def _time_ago(ts: float) -> str:
    """Format a timestamp as a relative time string."""
    if ts <= 0:
        return "unknown"
    delta = time.time() - ts
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    return f"{int(delta / 86400)}d ago"


def _fallback_session_name(session: dict) -> str:
    """Label for sessions without a description — first user message or created time."""
    first = (session.get("first_message") or "").strip()
    if first:
        return first
    from datetime import datetime
    ts = float(session.get("created_at", 0) or 0)
    if ts <= 0:
        return "(unnamed)"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


@dataclass(slots=True)
class ProviderCommand:
    """Show or switch provider."""

    name: str = "provider"
    description: str = "Show or switch provider (/provider [copilot|codex])"
    accepts_args: bool = True
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")

        session = self._get_session()

        if not ctx.args:
            return CommandResult.ok(f"Current provider: {session.provider_name}")

        target = ctx.args[0].lower()
        if target not in ("copilot", "codex"):
            return CommandResult.fail(
                f"Unknown provider: {target}. Options: copilot, codex"
            )

        if target == session.config.provider:
            return CommandResult.ok(f"Already using {target}.")

        # Switch provider — this requires re-authentication and a new session
        from taui.llm_provider.models import get_default_model

        session.config.provider = target
        session.config.model = get_default_model(target)
        # New session needed for the new provider
        await session.new_session()
        return CommandResult.ok(
            f"Switched to {target}/{session.config.model}",
            action="new_session",
            session_id=session.session_id,
        )


@dataclass(slots=True)
class LoginCommand:
    """Re-authenticate or add a provider."""

    name: str = "login"
    description: str = "Add or re-authenticate a provider"
    accepts_args: bool = False

    async def execute(self, ctx: CommandContext) -> CommandResult:
        from taui.llm_provider.auth import prompt_provider_selection

        try:
            provider = prompt_provider_selection()
        except (KeyboardInterrupt, EOFError):
            return CommandResult.ok("Login cancelled.")
        return CommandResult.ok(f"Authenticated with {provider}.")


@dataclass(slots=True)
class LogoutCommand:
    """Show logout instructions."""

    name: str = "logout"
    description: str = "Show how to remove saved credentials"
    accepts_args: bool = False

    async def execute(self, ctx: CommandContext) -> CommandResult:
        lines = [
            "To remove saved credentials:",
            "  Copilot: rm ~/.config/taui/copilot_token.json",
            "  Codex:   rm ~/.config/taui/codex_token.json",
            "",
            "Then /login to re-authenticate.",
        ]
        return CommandResult.ok("\n".join(lines))


@dataclass(slots=True)
class CopyCommand:
    """Copy the current agent context to clipboard as JSON."""

    name: str = "copy"
    description: str = "Copy current context to clipboard as JSON"
    accepts_args: bool = False
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")
        session = self._get_session()

        try:
            context_json = _context_json(session)
        except Exception as exc:
            return CommandResult.fail(f"Failed to serialize context: {exc}")

        data = context_json.encode()
        size_mb = len(data) / (1024 * 1024)
        if size_mb > 64:
            return CommandResult.fail(
                f"Context too large for clipboard ({size_mb:.1f} MB). "
                "Use /export instead."
            )

        message_count = len(session._loop._messages)
        return CommandResult.ok(
            f"Copied context JSON to clipboard ({message_count} messages, "
            f"{size_mb:.1f} MB).",
            action="copy_to_clipboard",
            clipboard_content=context_json,
        )


def _context_json(session: Any) -> str:
    loop = session._loop
    if hasattr(loop, "_build_llm_messages"):
        messages = loop._build_llm_messages()
    else:
        messages = [_message_to_dict(msg) for msg in loop._messages]

    # Strip large base64 image data to keep output manageable
    messages = _strip_images(messages)

    payload = {
        "session_id": getattr(session, "session_id", None),
        "provider": getattr(session, "provider_name", None),
        "model": getattr(session, "model_name", None),
        "messages": messages,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


def _strip_images(messages: list) -> list:
    """Replace inline base64 image URLs with a placeholder."""
    import copy

    result = []
    for msg in messages:
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, list):
            msg = copy.copy(msg)
            new_blocks = []
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "image_url"
                    and isinstance(block.get("image_url"), dict)
                    and str(block["image_url"].get("url", "")).startswith("data:")
                ):
                    new_blocks.append(
                        {"type": "image_url", "image_url": {"url": "[base64 image stripped]"}}
                    )
                else:
                    new_blocks.append(block)
            msg["content"] = new_blocks
        result.append(msg)
    return result


def _message_to_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return message
    if is_dataclass(message):
        return asdict(message)
    role = getattr(message, "role", "unknown")
    content = getattr(message, "content", None)
    return {"role": role, "content": content}


def _export_messages(messages: list, session_id: str, fmt: str) -> str:
    """Render messages in the given format."""
    if fmt == "jsonl":
        import json
        lines = []
        for msg in messages:
            role = msg.role if hasattr(msg, "role") else msg.get("role", "unknown")
            content = msg.content if hasattr(msg, "content") else msg.get("content", "")
            if isinstance(content, list):
                content = "\n".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
            lines.append(json.dumps({"role": role, "content": content or ""}))
        return "\n".join(lines) + "\n"

    if fmt == "html":
        lines = [
            "<!DOCTYPE html>",
            "<html><head>",
            f"<title>Session {session_id}</title>",
            "<style>",
            "body { font-family: system-ui; max-width: 800px; margin: 2em auto; }",
            ".user { background: #e3f2fd; padding: 1em; border-radius: 8px; margin: 0.5em 0; }",
            ".assistant { background: #f5f5f5; padding: 1em; "
            "border-radius: 8px; margin: 0.5em 0; }",
            ".system { color: #888; font-size: 0.9em; }",
            ".tool { background: #fff3e0; padding: 0.5em; border-radius: 4px; font-size: 0.9em; }",
            "</style>",
            "</head><body>",
            f"<h1>Session {session_id}</h1>",
        ]
        for msg in messages:
            role = msg.role if hasattr(msg, "role") else msg.get("role", "unknown")
            content = msg.content if hasattr(msg, "content") else msg.get("content", "")
            if isinstance(content, list):
                content = "\n".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
            if not content:
                continue
            escaped = (content or "").replace("&", "&amp;")
            escaped = escaped.replace("<", "&lt;").replace(">", "&gt;")
            escaped = escaped.replace("\n", "<br>\n")
            lines.append(f'<div class="{role}"><strong>{role.title()}</strong><br>{escaped}</div>')
        lines.append("</body></html>")
        return "\n".join(lines) + "\n"

    # Default: markdown
    lines = [f"# Session {session_id}\n"]
    for msg in messages:
        role = msg.role if hasattr(msg, "role") else msg.get("role", "unknown")
        content = msg.content if hasattr(msg, "content") else msg.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                p.get("text", "") for p in content if isinstance(p, dict)
            )
        if not content:
            continue
        if role == "user":
            lines.append(f"## User\n\n{content}\n")
        elif role == "assistant":
            lines.append(f"## Assistant\n\n{content}\n")
        elif role == "tool":
            lines.append(f"### Tool Result\n\n```\n{content}\n```\n")
        elif role == "system":
            lines.append(f"*System: {content[:200]}*\n")
    return "\n".join(lines) + "\n"


@dataclass(slots=True)
class ExportCommand:
    """Export session to file (markdown, JSONL, or HTML)."""

    name: str = "export"
    description: str = "Export session (/export [--jsonl|--html] [file])"
    accepts_args: bool = True
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")
        session = self._get_session()
        messages = session._loop._messages

        # Parse args
        fmt = "markdown"
        out_path = None
        for arg in (ctx.args or []):
            if arg == "--jsonl":
                fmt = "jsonl"
            elif arg == "--html":
                fmt = "html"
            elif arg == "--md" or arg == "--markdown":
                fmt = "markdown"
            else:
                out_path = arg

        content = _export_messages(messages, session.session_id, fmt)
        ext = {"markdown": ".md", "jsonl": ".jsonl", "html": ".html"}[fmt]

        from pathlib import Path
        if out_path:
            out = Path(out_path)
        else:
            exports_dir = session.working_dir / ".taui" / "exports"
            exports_dir.mkdir(parents=True, exist_ok=True)
            out = exports_dir / f"session-{session.session_id}{ext}"

        out.write_text(content)
        return CommandResult.ok(f"Exported ({fmt}) to {out}")


@dataclass(slots=True)
class HotkeysCommand:
    """Show keyboard shortcuts."""

    name: str = "hotkeys"
    description: str = "Show keyboard shortcuts"
    accepts_args: bool = False

    async def execute(self, ctx: CommandContext) -> CommandResult:
        lines = [
            "Keyboard shortcuts:",
            "  Enter            Submit message",
            "  Meta+Enter       Insert newline",
            "  Shift+Enter      Insert newline",
            "  Ctrl+C           Cancel agent / clear input / exit",
            "  Ctrl+D           Exit",
            "  Ctrl+P           Open command palette",
            "  Escape           Cancel running agent",
            "  Tab              Complete slash commands / @files",
            "",
            "Input prefixes:",
            "  /command         Slash commands (/help for list)",
            "  @file            Include file content",
            "  !cmd             Run shell, send output to agent",
            "  !!cmd            Run shell silently",
        ]
        return CommandResult.ok("\n".join(lines))


@dataclass(slots=True)
class VerboseCommand:
    """Toggle verbose tool output."""

    name: str = "verbose"
    description: str = "Toggle verbose/quiet tool output"
    accepts_args: bool = False
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if self._get_session is None:
            return CommandResult.fail("Session not available.")
        session = self._get_session()
        cfg = session.config
        cfg.verbose_tools = not cfg.verbose_tools
        state = "on (verbose)" if cfg.verbose_tools else "off (quiet)"
        return CommandResult.ok(f"Tool output: {state}")


@dataclass(slots=True)
class UpdateProvidersModelsCommand:
    """Force a refresh of the models.dev catalog and report what changed."""

    name: str = "update-providers-models"
    description: str = "Refresh model metadata from models.dev"
    accepts_args: bool = False

    async def execute(self, ctx: CommandContext) -> CommandResult:
        from taui.llm_provider.models import PROVIDER_MAP, fetch_models, list_models

        before: dict[str, set[str]] = {}
        for provider in PROVIDER_MAP:
            try:
                before[provider] = {m["id"] for m in list_models(provider)}
            except Exception:
                before[provider] = set()

        try:
            data = fetch_models(force=True)
        except Exception as exc:
            return CommandResult.fail(f"models.dev refresh failed: {exc}")
        if not data:
            return CommandResult.fail(
                "models.dev refresh returned no data (network?)."
            )

        lines = ["Refreshed models.dev catalog."]
        for provider in PROVIDER_MAP:
            try:
                after = {m["id"] for m in list_models(provider)}
            except Exception:
                after = set()
            added = sorted(after - before.get(provider, set()))
            removed = sorted(before.get(provider, set()) - after)
            lines.append(f"  {provider}: {len(after)} models")
            if added:
                lines.append(f"    + {', '.join(added[:5])}")
            if removed:
                lines.append(f"    - {', '.join(removed[:5])}")
        return CommandResult.ok("\n".join(lines))


@dataclass(slots=True)
class VariantCommand:
    """Show, set, or pick the model variant (reasoning effort)."""

    name: str = "variant"
    description: str = (
        "Show, set, or pick model variant — e.g. /variant high · /variant clear"
    )
    accepts_args: bool = True
    _get_session: Any = None

    # Words that clear the variant. Variant *values* themselves are looked up
    # per-model via taui.llm_provider.models.get_model_variants().
    _CLEAR = {"", "default", "clear", "off"}

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")
        session = self._get_session()

        if not ctx.args:
            return CommandResult.ok("", action="open_variant_picker")

        target = ctx.args[0].lower()
        from taui.llm_provider.models import get_model_variants

        allowed = get_model_variants(session.config.provider, session.config.model)
        if target in self._CLEAR:
            session.config.model_variant = ""
            session._loop._model_variant = ""
            await _persist_session_variant(session, "")
            return CommandResult.ok(
                "Model variant cleared.",
                action="variant_changed",
                variant="",
            )

        if not allowed:
            return CommandResult.fail(
                f"{session.config.model} does not expose reasoning variants."
            )
        if target not in allowed:
            options = ", ".join(allowed)
            return CommandResult.fail(
                f"Unsupported variant for {session.config.model}: {target}. "
                f"Options: {options} (or 'clear' to clear)."
            )

        session.config.model_variant = target
        session._loop._model_variant = target
        await _persist_session_variant(session, target)
        return CommandResult.ok(
            f"Model variant set to {target}",
            action="variant_changed",
            variant=target,
        )


async def _persist_session_variant(session: Any, variant: str) -> None:
    """Best-effort metadata update for already-persisted sessions."""
    if not getattr(session, "_session_persisted", False):
        return
    store = getattr(session, "_store", None)
    session_id = getattr(session, "session_id", "")
    if store is None or not session_id:
        return
    try:
        await store.update_session(session_id, model_variant=variant)
    except Exception:
        pass


@dataclass(slots=True)
class ThemeCommand:
    """Switch between taui themes.

    Switching to themes outside the taui set currently breaks styling,
    so this command intentionally only exposes the curated taui themes.
    """

    name: str = "theme"
    description: str = "Switch theme (/theme [dark|light])"
    accepts_args: bool = True

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not ctx.args:
            return CommandResult.ok("", action="open_theme_picker")

        choice = ctx.args[0].lower()
        # Accept short or full names.
        aliases = {
            "dark": "taui-dark",
            "light": "taui-light",
            "taui-dark": "taui-dark",
            "taui-light": "taui-light",
        }
        target = aliases.get(choice)
        if target is None:
            return CommandResult.fail(
                f"Unknown theme: {choice}. Options: dark, light"
            )
        return CommandResult.ok(
            f"Theme set to {target}",
            action="theme_changed",
            theme=target,
        )


@dataclass(slots=True)
class DebugCommand:
    """Run UI debug scenarios."""

    name: str = "debug"
    description: str = "Run UI debug scenarios"
    accepts_args: bool = True
    requires_args: bool = True

    async def execute(self, ctx: CommandContext) -> CommandResult:
        scenario = ctx.args[0].lower() if ctx.args else ""
        if scenario == "questions":
            return CommandResult.ok("Debug: questions", action="debug_questions")
        return CommandResult.fail("Usage: /debug questions")


@dataclass(slots=True)
class TasksCommand:
    """List background tasks. `/tasks stop <id>` cancels a running task."""

    name: str = "tasks"
    description: str = "List background sub-agent tasks; `/tasks stop <id>` cancels"
    accepts_args: bool = True
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")
        session = self._get_session()
        mgr = getattr(session, "task_manager", None)
        if mgr is None:
            return CommandResult.fail("Background tasks are not configured.")

        args = ctx.args or []
        if args and args[0].lower() == "stop":
            if len(args) < 2:
                return CommandResult.fail("Usage: /tasks stop <task_id>")
            ok = await mgr.stop(args[1])
            if not ok:
                return CommandResult.fail(
                    f"Task {args[1]} is not running or does not exist."
                )
            return CommandResult.ok(f"Cancellation requested for task {args[1]}.")

        records = mgr.list()
        if not records:
            return CommandResult.ok("No background tasks.")
        lines = []
        for r in records:
            label = f"[{r.id}] {r.state.value:>9} · {r.title}"
            if r.last_output and r.state.value == "running":
                snippet = r.last_output.strip().splitlines()[-1][:80]
                label += f"\n          → {snippet}"
            lines.append(label)
        return CommandResult.ok("\n".join(lines))


def register_builtins(
    registry: CommandRegistry,
    *,
    get_session=None,
    get_tracker=None,
    get_extensions=None,
    get_store=None,
    get_apply_profile=None,
) -> None:
    """Register all built-in commands."""
    help_cmd = HelpCommand()
    help_cmd.set_registry(registry)

    clear_cmd = ClearCommand()
    model_cmd = ModelCommand()
    agents_cmd = AgentsCommand()
    cost_cmd = CostCommand()
    provider_cmd = ProviderCommand()
    self_edit_cmd = SelfEditModeCommand()
    ext_mode_cmd = ExtensionsModeCommand()
    ext_list_cmd = ExtensionsCommand()
    sessions_cmd = SessionsCommand()
    new_cmd = NewSessionCommand()
    reload_cmd = ReloadCommand()
    copy_cmd = CopyCommand()
    export_cmd = ExportCommand()
    verbose_cmd = VerboseCommand()
    debug_cmd = DebugCommand()
    diff_cmd = GitDiffCommand()
    variant_cmd = VariantCommand()
    skills_cmd = SkillsCommand()
    prompts_cmd = PromptsCommand()
    tasks_cmd = TasksCommand()

    if get_session:
        clear_cmd._get_loop = lambda: get_session()._loop
        model_cmd._get_session = get_session
        agents_cmd._get_session = get_session
        provider_cmd._get_session = get_session
        ext_mode_cmd._get_session = get_session
        sessions_cmd._get_session = get_session
        new_cmd._get_session = get_session
        reload_cmd._get_session = get_session
        copy_cmd._get_session = get_session
        export_cmd._get_session = get_session
        verbose_cmd._get_session = get_session
        diff_cmd._get_session = get_session
        variant_cmd._get_session = get_session
        skills_cmd._get_session = get_session
        prompts_cmd._get_session = get_session
        tasks_cmd._get_session = get_session

    if get_store:
        agents_cmd._get_store = get_store
    if get_apply_profile:
        agents_cmd._get_apply_profile = get_apply_profile

    if get_extensions:
        ext_list_cmd._get_extensions = get_extensions

    if get_tracker:
        cost_cmd._get_tracker = get_tracker

    registry.register(help_cmd)
    registry.register(cost_cmd)
    registry.register(CompactCommand())
    registry.register(ContextCommand())
    registry.register(clear_cmd)
    registry.register(model_cmd)
    registry.register(variant_cmd)
    registry.register(agents_cmd)
    registry.register(provider_cmd)
    registry.register(ext_list_cmd)
    registry.register(self_edit_cmd)
    registry.register(ext_mode_cmd)
    registry.register(sessions_cmd)
    registry.register(new_cmd)
    registry.register(reload_cmd)
    registry.register(LoginCommand())
    registry.register(LogoutCommand())
    registry.register(copy_cmd)
    registry.register(export_cmd)
    registry.register(diff_cmd)
    registry.register(GitReviewCommand())
    registry.register(GitCommitCommand())
    registry.register(HotkeysCommand())
    registry.register(verbose_cmd)
    registry.register(debug_cmd)
    registry.register(ThemeCommand())
    registry.register(tasks_cmd)
    registry.register(UpdateProvidersModelsCommand())
    registry.register(skills_cmd)
    registry.register(prompts_cmd)

    registry.alias("h", "help")
    registry.alias("?", "help")
    registry.alias("keys", "hotkeys")
    registry.alias("quiet", "verbose")
    registry.alias("self-edit", "i")
