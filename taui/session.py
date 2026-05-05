"""
Session — wires together LLM provider, tools, and agent loop.

A Session is the unit of interactive use. It owns:
- The LLM provider (authenticated)
- The tool registry and executor
- The agent loop
- The event store (optional)
"""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from taui.agent.loop import AgentLoop, Message, RunResult
from taui.config import Config
from taui.cost import CostTracker
from taui.extensions import ExtensionRegistry
from taui.extensions.builtins import (
    close_builtin_extensions,
    configure_builtin_extensions,
    new_hook_registry,
)
from taui.hooks import HookRegistry
from taui.llm_provider.auth import get_credentials
from taui.llm_provider.providers import CodexProvider, CopilotProvider
from taui.prompt_builder import ProjectContext, SystemPromptBuilder
from taui.session_replay import ReplayItem
from taui.store.store import Store
from taui.store.stream import StreamClient
from taui.tools.builtins import register_builtins
from taui.tools.executor import ToolExecutor, ToolPolicy
from taui.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def _create_provider(config: Config):
    """Create and authenticate an LLM provider from config."""
    creds = get_credentials(config.provider)

    match config.provider:
        case "copilot":
            return CopilotProvider(credentials=creds)
        case "codex":
            return CodexProvider(credentials=creds)
        case _:
            raise ValueError(f"Unknown provider: {config.provider!r}")


class Session:
    """Interactive agent session.

    Usage::

        session = await Session.create(config)
        result = await session.send("What files are in src/?")
        print(result.text)
        await session.close()
    """

    def __init__(
        self,
        *,
        config: Config,
        provider,
        registry: ToolRegistry,
        executor: ToolExecutor,
        store: Store,
        stream: StreamClient,
        loop: AgentLoop,
        cost_tracker: CostTracker | None = None,
        ext_registry: ExtensionRegistry | None = None,
        hooks: HookRegistry | None = None,
        session_id: str | None = None,
    ) -> None:
        self.config = config
        self._provider = provider
        self._registry = registry
        self._executor = executor
        self._store = store
        self._stream = stream
        self._loop = loop
        self.cost_tracker = cost_tracker or CostTracker()
        self._ext_registry = ext_registry
        self.hooks = hooks or HookRegistry()
        self.session_id = session_id or uuid4().hex[:12]
        self.extensions_mode = False
        self._system_prompt: str = ""
        self._extensions_prompt: str = ""
        self._message_count = 0
        self._loaded_offset = 0
        self._last_replay_items: list[ReplayItem] = []
        self.last_resume_error: str = ""

    @classmethod
    async def create(cls, config: Config | None = None) -> Session:
        """Create a fully wired session."""
        if config is None:
            config = Config.load()

        # Provider
        provider = _create_provider(config)

        # Tools
        registry = ToolRegistry()
        register_builtins(registry)
        # Set working_dir on all builtin tools
        for name in registry.names:
            tool = registry.get(name)
            if hasattr(tool, "working_dir"):
                tool.working_dir = config.working_dir

        policy = ToolPolicy()
        executor = ToolExecutor(registry=registry, policy=policy)

        # Build system prompt
        builder = SystemPromptBuilder()
        try:
            ctx = ProjectContext.discover_with_git(config.working_dir)
        except Exception:
            ctx = ProjectContext.discover(config.working_dir)
        builder.with_project_context(ctx)

        # Inject tool metadata — builds snippets + adaptive guidelines
        builder.with_tools(registry)

        system_prompt = builder.render()

        # Store
        store = Store(config.working_dir)
        await store.connect()
        stream = StreamClient(store)

        # Built-in extensions are preloaded; user extensions are file-backed.
        builtin_tool_names = set(registry.names)
        ext_registry = ExtensionRegistry(config.working_dir, include_builtins=True)
        ext_registry.discover()
        hooks = new_hook_registry()
        ext_registry.load_all(tools=registry, commands=None, hooks=hooks)

        # Let extensions transform the system prompt
        if hooks.has("system_prompt"):
            system_prompt = await hooks.transform("system_prompt", system_prompt, None)

        session_id = uuid4().hex[:12]

        # Agent
        loop = AgentLoop(
            agent_id=session_id,
            llm=provider,
            executor=executor,
            stream=stream,
            system_prompt=system_prompt,
            model=config.model,
            max_turns=config.max_turns,
        )

        session = cls(
            config=config,
            provider=provider,
            registry=registry,
            executor=executor,
            store=store,
            stream=stream,
            loop=loop,
            ext_registry=ext_registry,
            hooks=hooks,
            session_id=session_id,
        )
        session._system_prompt = system_prompt
        session._extensions_prompt = _EXTENSIONS_SYSTEM_PROMPT
        session._builtin_tool_names = builtin_tool_names
        configure_builtin_extensions(session)
        session._refresh_loop_integrations()

        # Wire skill paths bundled by extensions into the skill registry.
        skill_reg = getattr(session, "_skill_registry", None)
        if skill_reg is not None:
            for name in ext_registry.names:
                ext = ext_registry.get(name)
                if ext and ext.skill_paths:
                    for p in ext.skill_paths:
                        skill_reg.add_from_path(p, scope=ext.scope)

        # Register session in store
        await store.create_session(session.session_id, stream_id=session._loop.stream_id)
        session._loaded_offset = await stream.get_length(session._loop.stream_id)

        return session

    async def send(self, message: str) -> RunResult:
        """Send a user message and get the agent's response."""
        await self._sync_replay_from_store()

        # Pipeline hook: let extensions preprocess the message
        message = await self.hooks.transform("before_send", message, self)

        result = await self._loop.run(message)
        self._message_count += 1
        self._loaded_offset = await self._stream.get_length(self._loop.stream_id)

        # Pipeline hook: let extensions postprocess the result
        result = await self.hooks.transform("after_result", result, self)
        # Record cost from usage
        for tr in result.turn_results:
            if tr.usage:
                self.cost_tracker.record(
                    model=self.config.model,
                    input_tokens=tr.usage.get("input_tokens", 0),
                    output_tokens=tr.usage.get("output_tokens", 0),
                )
        # Update session metadata
        try:
            await self._store.update_session(
                self.session_id,
                message_count=self._message_count,
            )
            # Auto-describe on first message if no description yet
            if self._message_count == 1 and result.text:
                desc = result.text[:120].split("\n")[0]
                await self._store.update_session(
                    self.session_id, description=desc,
                )
        except Exception:
            logger.debug("Failed to update session metadata", exc_info=True)
        return result

    async def new_session(self) -> None:
        """Start a fresh session — new loop, new agent, same store."""
        self.session_id = uuid4().hex[:12]
        self._message_count = 0
        self._last_replay_items = []

        prompt = self._extensions_prompt if self.extensions_mode else self._system_prompt

        loop = AgentLoop(
            agent_id=self.session_id,
            llm=self._provider,
            executor=self._executor,
            stream=self._stream,
            system_prompt=prompt,
            model=self.config.model,
            max_turns=self.config.max_turns,
        )
        self._replace_loop(loop)

        await self._store.create_session(
            self.session_id,
            mode="extensions" if self.extensions_mode else "normal",
            stream_id=self._loop.stream_id,
        )
        self._loaded_offset = await self._stream.get_length(self._loop.stream_id)

        # Observer hook
        await self.hooks.run("on_session_start", self)

    async def toggle_extensions_mode(self) -> bool:
        """Toggle extensions mode. Returns new state."""
        self.extensions_mode = not self.extensions_mode

        # Set/clear write guards on file-write tools
        self._apply_write_guard()

        prompt = self._extensions_prompt if self.extensions_mode else self._system_prompt

        # Create a new loop with the appropriate prompt
        self.session_id = uuid4().hex[:12]
        self._message_count = 0
        self._last_replay_items = []

        loop = AgentLoop(
            agent_id=self.session_id,
            llm=self._provider,
            executor=self._executor,
            stream=self._stream,
            system_prompt=prompt,
            model=self.config.model,
            max_turns=self.config.max_turns,
        )
        self._replace_loop(loop)

        # New session for the new mode
        await self._store.create_session(
            self.session_id,
            mode="extensions" if self.extensions_mode else "normal",
            stream_id=self._loop.stream_id,
        )
        self._loaded_offset = await self._stream.get_length(self._loop.stream_id)

        # Observer hook
        await self.hooks.run(
            "on_mode_change",
            "extensions" if self.extensions_mode else "normal",
            self,
        )

        return self.extensions_mode

    async def resume_session(self, session_id: str) -> bool:
        """Resume a previous session by replaying its messages."""
        self.last_resume_error = ""
        meta = await self._store.get_session(session_id)
        if meta is None:
            self.last_resume_error = f"Session not found: {session_id}"
            return False

        stream_id = str(meta.get("stream_id") or "")
        if not stream_id:
            self.last_resume_error = f"Session has no replayable stream: {session_id}"
            return False
        if not await self._stream.stream_exists(stream_id):
            self.last_resume_error = f"Session stream not found: {stream_id}"
            return False

        self.session_id = session_id
        self.extensions_mode = meta.get("mode") == "extensions"
        self._message_count = meta.get("message_count", 0)

        prompt = self._extensions_prompt if self.extensions_mode else self._system_prompt

        loop = AgentLoop(
            agent_id=_agent_id_from_stream(stream_id, session_id),
            llm=self._provider,
            executor=self._executor,
            stream=self._stream,
            system_prompt=prompt,
            model=self.config.model,
            max_turns=self.config.max_turns,
        )
        loop.stream_id = stream_id
        self._replace_loop(loop)

        await self._replay_stream()

        await self._store.update_session(session_id)
        return True

    async def list_sessions(self) -> list[dict]:
        """List recent sessions."""
        return await self._store.list_sessions()

    def reload_extensions(self) -> list[str]:
        """Hot-reload extensions: unload, re-discover, re-load.

        Returns names of loaded extensions.
        """
        # Remove extension-added tools
        builtin = getattr(self, "_builtin_tool_names", set())
        ext_tools = [n for n in self._registry.names if n not in builtin]
        for name in ext_tools:
            self._registry.unregister(name)

        # Clear all hooks (only extensions register hooks)
        self.hooks.clear()

        # Unload, re-discover, re-load
        if self._ext_registry:
            self._ext_registry.unload_all()
            self._ext_registry.discover()
            loaded_all = self._ext_registry.load_all(
                tools=self._registry, commands=None, hooks=self.hooks,
            )
            loaded = []
            for name in loaded_all:
                ext = self._ext_registry.get(name)
                if ext and ext.scope != "builtin":
                    loaded.append(name)
        else:
            loaded = []

        # Set working_dir on any new tools
        for name in self._registry.names:
            tool = self._registry.get(name)
            if hasattr(tool, "working_dir"):
                tool.working_dir = self.config.working_dir

        # Re-apply write guard if in extensions mode
        if self.extensions_mode:
            self._apply_write_guard()

        logger.info("Reloaded extensions: %s", loaded)
        return loaded

    async def close(self) -> None:
        """Clean up resources."""
        await close_builtin_extensions(self)
        try:
            await self._store.close()
        except Exception:
            logger.debug("Error closing store", exc_info=True)

    @property
    def provider_name(self) -> str:
        return self.config.provider

    @property
    def model_name(self) -> str:
        return self.config.model

    @property
    def working_dir(self) -> Path:
        return self.config.working_dir

    def _apply_write_guard(self) -> None:
        """Set or clear the write guard on file-write tools."""
        guard = self._extensions_guard if self.extensions_mode else None
        for name in ("write", "edit"):
            if name in self._registry:
                tool = self._registry.get(name)
                if hasattr(tool, "_path_guard"):
                    tool._path_guard = guard

    def _extensions_guard(self, path: Path) -> Any:
        """Reject writes outside .taui/ when in extensions mode."""
        from taui.tools.base import ToolResult
        taui_dir = self.config.working_dir / ".taui"
        try:
            path.resolve().relative_to(taui_dir.resolve())
        except ValueError:
            return ToolResult.fail(
                f"Extensions mode: writes are restricted to .taui/ — "
                f"cannot write to {path}. Create an extension in "
                f".taui/extensions/ instead."
            )
        return None

    @property
    def replay_items(self) -> list[ReplayItem]:
        """Transcript items from the most recent successful resume."""
        return list(self._last_replay_items)

    def _replace_loop(self, loop: AgentLoop) -> None:
        self._loop = loop
        self._refresh_loop_integrations()

    def _refresh_loop_integrations(self) -> None:
        try:
            skills_tool = self._registry.get("skills")
        except ValueError:
            return

        async def inject_skill_message(content: str) -> None:
            self._loop._messages.append(Message(role="system", content=content))

        skills_tool._inject_message = inject_skill_message

    async def _replay_stream(self) -> None:
        transcript = await self._stream.load_conversation(self._loop.stream_id)
        prompt = self._extensions_prompt if self.extensions_mode else self._system_prompt
        self._loop._messages = [Message(role="system", content=prompt)]
        self._loop._messages.extend(transcript.messages)
        self._last_replay_items = transcript.items
        self._message_count = sum(1 for msg in transcript.messages if msg.role == "user")
        self._loaded_offset = await self._stream.get_length(self._loop.stream_id)

    async def _sync_replay_from_store(self) -> None:
        if not self._loop.stream_id:
            return
        if not await self._stream.stream_exists(self._loop.stream_id):
            return
        current_offset = await self._stream.get_length(self._loop.stream_id)
        if current_offset > self._loaded_offset:
            await self._replay_stream()


def _agent_id_from_stream(stream_id: str, fallback: str) -> str:
    prefix = "agents/"
    if stream_id.startswith(prefix) and len(stream_id) > len(prefix):
        return stream_id[len(prefix):]
    return fallback


# ── Extensions system prompt ───────────────────────────────────────────────────

_EXTENSIONS_SYSTEM_PROMPT = """\
You are a taui extensions agent. You can create, modify, or delete taui \
extensions — Python files in .taui/extensions/.

IMPORTANT: You can ONLY write to .taui/ paths. You cannot modify taui source \
code. All customization must be done through extensions.

## Extension Convention

Every extension is a single .py file with a `register(ctx)` entry point.
`ctx` gives access to all registration targets: tools, commands, hooks, and skills.

### Tool Extension

```python
from dataclasses import dataclass, field
from typing import Any
from taui.tools.base import ToolCategory, ToolResult

@dataclass
class MyTool:
    name: str = "my_tool"
    description: str = "What this tool does"
    category: ToolCategory = ToolCategory.AGENT
    schema: dict[str, Any] = field(default=None)

    def __post_init__(self):
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "arg": {"type": "string", "description": "..."},
                },
                "required": ["arg"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.ok("result")

def register(ctx):
    ctx.tools.register(MyTool())
```

### Command Extension

```python
from dataclasses import dataclass
from taui.commands.registry import CommandContext, CommandResult

@dataclass(slots=True)
class MyCommand:
    name: str = "mycommand"
    description: str = "What this command does"

    async def execute(self, cmd_ctx: CommandContext) -> CommandResult:
        return CommandResult.ok("output")

def register(ctx):
    if ctx.commands:
        ctx.commands.register(MyCommand())
```

### Hook Extension

Hooks let you customize UI and behavior without modifying source code.

```python
def register(ctx):
    # UI hooks (sync, return str | None):
    ctx.hooks.prompt(lambda session: "\\033[35m❯ \\033[0m")
    ctx.hooks.banner(lambda session: "Custom banner line")
    ctx.hooks.status(lambda session: f"msgs: {session._message_count}")
    ctx.hooks.turn_summary(lambda result, session: f"turns: {result.turns}")

    # Pipeline hooks (sync or async, transform data):
    ctx.hooks.before_send(lambda msg, session: msg)
    ctx.hooks.after_result(lambda result, session: result)
    ctx.hooks.system_prompt(lambda prompt, session: prompt + "\\nExtra instructions.")

    # Observer hooks (sync or async, side-effects):
    ctx.hooks.on_tool_call(lambda name, args, session: None)
    ctx.hooks.on_tool_result(lambda name, content, is_error, session: None)
    ctx.hooks.on_session_start(lambda session: None)
    ctx.hooks.on_mode_change(lambda mode, session: None)

    # Override hooks (sync or async, first non-None wins):
    ctx.hooks.on_approval(lambda name, args, session: True)  # auto-approve
```

### Skill / Prompt Asset Extension

Bundle a Markdown prompt file alongside your extension:

```python
def register(ctx):
    ctx.skills.add_path("skills/code-review.md")   # relative to this .py file
```

Place the file at `.taui/extensions/skills/code-review.md`. Users load it
with the skills tool.

#### Hook Categories

| Hook | Type | Signature | Purpose |
|------|------|-----------|---------|
| `prompt` | UI | `(session) -> str` | Override input prompt text |
| `banner` | UI | `(session) -> str` | Add line to startup banner |
| `status` | UI | `(session) -> str` | Add status bar segment |
| `turn_summary` | UI | `(result, session) -> str` | Add to turn summary line |
| `before_send` | Pipeline | `(message, session) -> message` | Transform user input |
| `after_result` | Pipeline | `(result, session) -> result` | Transform agent output |
| `system_prompt` | Pipeline | `(prompt, session) -> prompt` | Modify system prompt |
| `on_tool_call` | Observer | `(name, args, session)` | Watch tool calls |
| `on_tool_result` | Observer | `(name, content, is_error, session)` | Watch tool results |
| `on_session_start` | Observer | `(session)` | New session started |
| `on_mode_change` | Observer | `(mode, session)` | Mode toggled |
| `on_approval` | Override | `(name, args, session) -> bool` | Auto-approve/deny tools |

## Rules
- Write files ONLY to .taui/extensions/<name>.py (and .taui/extensions/skills/)
- Read existing extension files before modifying them
- One extension per file
- Never modify core taui source files — you literally cannot
- After writing, tell the user to run /reload to activate the extension
"""
