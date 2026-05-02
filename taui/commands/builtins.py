"""Built-in slash commands."""

from __future__ import annotations

import subprocess
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
    description: str = "Show, set, list, or select model interactively"
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")
        session = self._get_session()
        if not ctx.args:
            return CommandResult.ok(f"Current model: {session.model_name}")

        sub = ctx.args[0]
        if sub in ("list", "ls"):
            return self._list_models(session)
        if sub == "refresh":
            return self._list_models(session, force=True)
        if sub in ("select", "pick"):
            return self._interactive_select(session)

        # Set model
        model = sub
        session.config.model = model
        session._loop._model = model
        return CommandResult.ok(f"Model set to {model}")

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
            tag = " 🧠" if m["reasoning"] else ""
            current = " ◀" if m["id"] == session.config.model else ""
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
        return CommandResult.ok(f"Model set to {selected}")


@dataclass(slots=True)
class ExtensionsModeCommand:
    """Toggle extensions mode. Creates a new session with the extensions prompt."""

    name: str = "i"
    description: str = "Toggle extensions mode (yellow UI)"
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")

        session = self._get_session()
        is_on = await session.toggle_extensions_mode()

        if is_on:
            # If user provided a description, send it as the first message
            msg = "Extensions mode ON"
            if ctx.args:
                desc = " ".join(ctx.args)
                msg += f" — starting with: {desc}"
            return CommandResult.ok(msg, action="extensions_on")
        else:
            return CommandResult.ok(
                "Extensions mode OFF — back to normal.",
                action="extensions_off",
            )


@dataclass(slots=True)
class SessionsCommand:
    """List recent sessions and allow resuming one interactively."""

    name: str = "sessions"
    description: str = "List sessions — interactive picker or /sessions <id>"
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
            return CommandResult.fail(f"Session not found: {target}")

        # List sessions — if any, show interactive picker
        sessions = await session.list_sessions()
        if not sessions:
            return CommandResult.ok("No previous sessions.")

        selected = _interactive_session_select(sessions)
        if selected is None:
            # User cancelled or non-interactive — show text listing
            return self._format_session_list(sessions)

        ok = await session.resume_session(selected)
        if ok:
            mode = " [extensions]" if session.extensions_mode else ""
            return CommandResult.ok(
                f"Resumed session {selected}{mode}",
                action="session_resumed",
                session_id=selected,
                extensions_mode=session.extensions_mode,
            )
        return CommandResult.fail(f"Failed to resume session: {selected}")

    @staticmethod
    def _format_session_list(sessions: list[dict]) -> CommandResult:
        lines = ["Sessions:"]
        for s in sessions[:20]:
            sid = s["session_id"]
            desc = s.get("description", "") or "(no description)"
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
    """Start a fresh session."""

    name: str = "new"
    description: str = "Start a new session"
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")

        session = self._get_session()
        await session.new_session()
        mode = "extensions" if session.extensions_mode else "normal"
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


@dataclass(slots=True)
class ReloadCommand:
    """Hot-reload extensions without restarting."""

    name: str = "reload"
    description: str = "Reload extensions"
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")

        session = self._get_session()
        loaded = session.reload_extensions()
        if loaded:
            return CommandResult.ok(
                f"Reloaded {len(loaded)} extension(s): {', '.join(loaded)}",
                action="reloaded",
            )
        return CommandResult.ok("No extensions loaded.", action="reloaded")


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


def _interactive_session_select(sessions: list[dict]) -> str | None:
    """Interactive session picker using prompt_toolkit.

    Returns the selected session_id, or None if the user cancels.
    Falls back to text listing if running inside an event loop.
    """
    if not sessions:
        return None

    # Check if we're inside an async event loop — prompt_toolkit's app.run()
    # uses asyncio.run() which can't nest. Fall back to simple text picker.
    import asyncio
    try:
        asyncio.get_running_loop()
        return _simple_session_select(sessions)
    except RuntimeError:
        pass

    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    selected = [0]
    display = sessions[:20]

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(event):
        selected[0] = (selected[0] - 1) % len(display)

    @kb.add("down")
    @kb.add("j")
    def _down(event):
        selected[0] = (selected[0] + 1) % len(display)

    @kb.add("enter")
    def _enter(event):
        event.app.exit(result=display[selected[0]]["session_id"])

    @kb.add("c-c")
    @kb.add("c-d")
    @kb.add("escape")
    def _quit(event):
        event.app.exit(result=None)

    def _get_text():
        lines = [("bold", "Select a session to resume:\n\n")]
        for i, s in enumerate(display):
            sid = s["session_id"]
            desc = s.get("description", "") or "(no description)"
            mode = s.get("mode", "normal")
            msgs = s.get("message_count", 0)
            ago = _time_ago(s.get("last_active", 0))
            mode_tag = " [ext]" if mode == "extensions" else ""
            label = f"{sid}  {desc[:40]:<40s}  {msgs:>3} msgs  {ago}{mode_tag}"
            if i == selected[0]:
                lines.append(("bold fg:cyan", f"  ❯ {label}\n"))
            else:
                lines.append(("class:dim", f"    {label}\n"))
        lines.append(("", "\n"))
        lines.append(("class:dim", "↑/↓ to move, Enter to resume, Esc to cancel"))
        return lines

    app: Application[str | None] = Application(
        layout=Layout(HSplit([Window(FormattedTextControl(_get_text))])),
        key_bindings=kb,
        full_screen=False,
    )

    return app.run()


def _simple_session_select(sessions: list[dict]) -> str | None:
    """Fallback text-based session selection."""
    display = sessions[:20]
    print("\nSessions:")
    for i, s in enumerate(display, 1):
        sid = s["session_id"]
        desc = s.get("description", "") or "(no description)"
        mode = s.get("mode", "normal")
        msgs = s.get("message_count", 0)
        ago = _time_ago(s.get("last_active", 0))
        mode_tag = " [ext]" if mode == "extensions" else ""
        print(f"  {i:2}. {sid}  {desc[:40]:<40s}  {msgs:>3} msgs  {ago}{mode_tag}")
    print()
    try:
        choice = input(f"Resume [1-{len(display)}] or Enter to cancel: ").strip()
        if not choice:
            return None
        idx = int(choice) - 1
        if 0 <= idx < len(display):
            return display[idx]["session_id"]
    except (ValueError, EOFError, KeyboardInterrupt, OSError):
        pass
    return None


@dataclass(slots=True)
class ProviderCommand:
    """Show or switch provider."""

    name: str = "provider"
    description: str = "Show or switch provider (/provider [copilot|codex])"
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
class SessionInfoCommand:
    """Show current session info."""

    name: str = "session"
    description: str = "Show current session info"
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")
        session = self._get_session()
        tracker = session.cost_tracker
        lines = [
            f"Session:    {session.session_id}",
            f"Provider:   {session.provider_name}",
            f"Model:      {session.model_name}",
            f"Messages:   {session._message_count}",
            f"Tokens in:  {tracker.total_input_tokens:,}",
            f"Tokens out: {tracker.total_output_tokens:,}",
            f"Cost:       ${tracker.total_cost_usd:.4f}",
            f"Mode:       {'extensions' if session.extensions_mode else 'normal'}",
        ]
        return CommandResult.ok("\n".join(lines))


@dataclass(slots=True)
class CopyCommand:
    """Copy last assistant message to clipboard."""

    name: str = "copy"
    description: str = "Copy last assistant message to clipboard"
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")
        session = self._get_session()
        # Find last assistant message
        messages = session._loop._messages
        last_text = None
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    last_text = content
                    break
        if not last_text:
            return CommandResult.ok("No assistant message to copy.")
        try:
            subprocess.run(
                ["pbcopy"], input=last_text.encode(),
                check=True, timeout=5,
            )
        except FileNotFoundError:
            # Fallback for non-macOS
            try:
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=last_text.encode(), check=True, timeout=5,
                )
            except (FileNotFoundError, subprocess.SubprocessError):
                return CommandResult.fail(
                    "Clipboard not available (install pbcopy or xclip)."
                )
        except subprocess.SubprocessError as exc:
            return CommandResult.fail(f"Clipboard error: {exc}")
        preview = last_text[:80] + ("..." if len(last_text) > 80 else "")
        return CommandResult.ok(f"Copied to clipboard: {preview}")


@dataclass(slots=True)
class ExportCommand:
    """Export session to a markdown file."""

    name: str = "export"
    description: str = "Export session to markdown (/export [file])"
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if not self._get_session:
            return CommandResult.fail("No session.")
        session = self._get_session()
        messages = session._loop._messages

        # Build markdown
        lines = [f"# Session {session.session_id}\n"]
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = "\n".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict)
                )
            if not content:
                continue
            if role == "user":
                lines.append(f"## User\n\n{content}\n")
            elif role == "assistant":
                lines.append(f"## Assistant\n\n{content}\n")

        md = "\n".join(lines)

        # Determine output path
        from pathlib import Path
        if ctx.args:
            out = Path(ctx.args[0])
        else:
            exports_dir = session.working_dir / ".taui" / "exports"
            exports_dir.mkdir(parents=True, exist_ok=True)
            out = exports_dir / f"session-{session.session_id}.md"

        out.write_text(md)
        return CommandResult.ok(f"Exported to {out}")


@dataclass(slots=True)
class HotkeysCommand:
    """Show keyboard shortcuts."""

    name: str = "hotkeys"
    description: str = "Show keyboard shortcuts"

    async def execute(self, ctx: CommandContext) -> CommandResult:
        lines = [
            "Keyboard shortcuts:",
            "  Enter            Submit message",
            "  Meta+Enter       Insert newline",
            "  Shift+Enter      Insert newline",
            "  Ctrl+C           Cancel agent / clear input / exit",
            "  Ctrl+D           Exit",
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
    _get_session: Any = None

    async def execute(self, ctx: CommandContext) -> CommandResult:
        if self._get_session is None:
            return CommandResult.fail("Session not available.")
        session = self._get_session()
        cfg = session.config
        cfg.verbose_tools = not cfg.verbose_tools
        state = "on (verbose)" if cfg.verbose_tools else "off (quiet)"
        return CommandResult.ok(f"Tool output: {state}")


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
    provider_cmd = ProviderCommand()
    ext_mode_cmd = ExtensionsModeCommand()
    ext_list_cmd = ExtensionsCommand()
    sessions_cmd = SessionsCommand()
    new_cmd = NewSessionCommand()
    reload_cmd = ReloadCommand()
    session_info_cmd = SessionInfoCommand()
    copy_cmd = CopyCommand()
    export_cmd = ExportCommand()
    verbose_cmd = VerboseCommand()

    if get_session:
        clear_cmd._get_loop = lambda: get_session()._loop
        model_cmd._get_session = get_session
        provider_cmd._get_session = get_session
        ext_mode_cmd._get_session = get_session
        sessions_cmd._get_session = get_session
        new_cmd._get_session = get_session
        reload_cmd._get_session = get_session
        session_info_cmd._get_session = get_session
        copy_cmd._get_session = get_session
        export_cmd._get_session = get_session
        verbose_cmd._get_session = get_session

    if get_tracker:
        cost_cmd._get_tracker = get_tracker

    if get_extensions:
        ext_list_cmd._get_extensions = get_extensions

    registry.register(help_cmd)
    registry.register(cost_cmd)
    registry.register(CompactCommand())
    registry.register(clear_cmd)
    registry.register(model_cmd)
    registry.register(provider_cmd)
    registry.register(ext_list_cmd)
    registry.register(ext_mode_cmd)
    registry.register(sessions_cmd)
    registry.register(new_cmd)
    registry.register(reload_cmd)
    registry.register(LoginCommand())
    registry.register(LogoutCommand())
    registry.register(session_info_cmd)
    registry.register(copy_cmd)
    registry.register(export_cmd)
    registry.register(HotkeysCommand())
    registry.register(verbose_cmd)

    registry.alias("h", "help")
    registry.alias("?", "help")
    registry.alias("keys", "hotkeys")
    registry.alias("quiet", "verbose")
