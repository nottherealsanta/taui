"""Built-in slash commands."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from taui.commands.registry import CommandContext, CommandRegistry, CommandResult


@dataclass(slots=True)
class HelpCommand:
    name: str = "help"
    description: str = "Show available commands"
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

    async def execute(self, ctx: CommandContext) -> CommandResult:
        return CommandResult.ok(
            "Compaction requested.",
            action="compact_requested",
        )


@dataclass(slots=True)
class ClearCommand:
    name: str = "clear"
    description: str = "Clear conversation history"
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
    description: str = "Show or set the model"
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")
        session = self._get_session()
        if ctx.args:
            model = ctx.args[0]
            session.config.model = model
            session._loop._model = model
            return CommandResult.ok(f"Model set to {model}")
        return CommandResult.ok(f"Current model: {session.model_name}")


@dataclass(slots=True)
class SelfEditCommand:
    """Toggle self-edit mode. Creates a new session with the self-edit prompt."""

    name: str = "i"
    description: str = "Toggle self-edit mode (yellow UI)"
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")

        session = self._get_session()
        is_on = await session.toggle_self_edit()

        if is_on:
            # If user provided a description, send it as the first message
            msg = "Self-edit mode ON"
            if ctx.args:
                desc = " ".join(ctx.args)
                msg += f" — starting with: {desc}"
            return CommandResult.ok(msg, action="self_edit_on")
        else:
            return CommandResult.ok(
                "Self-edit mode OFF — back to normal.",
                action="self_edit_off",
            )


@dataclass(slots=True)
class SessionsCommand:
    """List recent sessions and allow resuming one."""

    name: str = "sessions"
    description: str = "List sessions (select to resume)"
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")

        session = self._get_session()

        # If an arg is given, try to resume that session
        if ctx.args:
            target = ctx.args[0]
            ok = await session.resume_session(target)
            if ok:
                mode = " [self-edit]" if session.self_edit else ""
                return CommandResult.ok(
                    f"Resumed session {target}{mode}",
                    action="session_resumed",
                    session_id=target,
                    self_edit=session.self_edit,
                )
            return CommandResult.fail(f"Session not found: {target}")

        # List sessions
        sessions = await session.list_sessions()
        if not sessions:
            return CommandResult.ok("No previous sessions.")

        lines = ["Sessions:"]
        for s in sessions:
            sid = s["session_id"]
            desc = s.get("description", "") or "(no description)"
            mode = s.get("mode", "normal")
            msgs = s.get("message_count", 0)
            ago = _time_ago(s.get("last_active", 0))
            mode_tag = " [self-edit]" if mode == "self-edit" else ""
            lines.append(
                f"  {sid}  {desc[:50]:50s}  {msgs:>3} msgs  {ago}{mode_tag}"
            )
        lines.append("")
        lines.append("Resume: /sessions <id>")
        return CommandResult.ok("\n".join(lines))


@dataclass(slots=True)
class NewSessionCommand:
    """Start a fresh session."""

    name: str = "new"
    description: str = "Start a new session"
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")

        session = self._get_session()
        await session.new_session()
        mode = "self-edit" if session.self_edit else "normal"
        return CommandResult.ok(
            f"New session started ({mode}).",
            action="new_session",
            session_id=session.session_id,
        )


@dataclass(slots=True)
class ExtensionsCommand:
    name: str = "extensions"
    description: str = "List loaded extensions"
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


def register_builtins(
    registry: CommandRegistry,
    *,
    get_session=None,
    get_tracker=None,
    get_extensions=None,
) -> None:
    """Register all built-in commands."""
    help_cmd = HelpCommand()
    help_cmd.set_registry(registry)

    clear_cmd = ClearCommand()
    model_cmd = ModelCommand()
    cost_cmd = CostCommand()
    ext_cmd = ExtensionsCommand()
    self_edit_cmd = SelfEditCommand()
    sessions_cmd = SessionsCommand()
    new_cmd = NewSessionCommand()

    if get_session:
        clear_cmd._get_loop = lambda: get_session()._loop
        model_cmd._get_session = get_session
        self_edit_cmd._get_session = get_session
        sessions_cmd._get_session = get_session
        new_cmd._get_session = get_session

    if get_tracker:
        cost_cmd._get_tracker = get_tracker

    if get_extensions:
        ext_cmd._get_extensions = get_extensions

    registry.register(help_cmd)
    registry.register(cost_cmd)
    registry.register(CompactCommand())
    registry.register(clear_cmd)
    registry.register(model_cmd)
    registry.register(ext_cmd)
    registry.register(self_edit_cmd)
    registry.register(sessions_cmd)
    registry.register(new_cmd)

    registry.alias("h", "help")
    registry.alias("?", "help")
