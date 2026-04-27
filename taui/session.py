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
from taui.llm_provider.auth import get_credentials
from taui.llm_provider.providers import CodexProvider, CopilotProvider
from taui.mcp import McpManager
from taui.prompt_builder import ProjectContext, SystemPromptBuilder
from taui.skills import SkillRegistry
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
        self.session_id = session_id or uuid4().hex[:12]
        self.self_edit = False
        self._system_prompt: str = ""
        self._self_edit_prompt: str = ""
        self._message_count = 0

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

        # Wire sub-agent tool with shared dependencies
        sub_agent = registry.get("sub_agent")
        sub_agent._llm = provider
        sub_agent._stream = stream
        sub_agent._parent_executor = executor
        sub_agent._model = config.model
        sub_agent._system_prompt = ""  # uses default from SubAgentTool

        # Wire skills tool
        skill_registry = SkillRegistry(config.working_dir)
        skill_registry.discover()
        skills_tool = registry.get("skills")
        skills_tool._skill_registry = skill_registry

        # Wire MCP tool
        mcp_manager = McpManager(config.working_dir)
        mcp_manager.load_configs()
        mcp_tool = registry.get("mcp")
        mcp_tool._manager = mcp_manager

        # Load extensions
        ext_registry = ExtensionRegistry(config.working_dir)
        ext_registry.discover()
        ext_registry.load_all(tools=registry, commands=None)

        # Agent
        loop = AgentLoop(
            llm=provider,
            executor=executor,
            stream=stream,
            system_prompt=system_prompt,
            model=config.model,
            max_turns=config.max_turns,
        )

        # Wire skills injection into the agent loop's message list
        from taui.agent.loop import Message

        async def inject_skill_message(content: str) -> None:
            loop._messages.append(Message(role="system", content=content))

        skills_tool._inject_message = inject_skill_message

        session = cls(
            config=config,
            provider=provider,
            registry=registry,
            executor=executor,
            store=store,
            stream=stream,
            loop=loop,
            ext_registry=ext_registry,
        )
        session._system_prompt = system_prompt
        session._self_edit_prompt = _SELF_EDIT_SYSTEM_PROMPT

        # Register session in store
        await store.create_session(session.session_id)

        return session

    async def send(self, message: str) -> RunResult:
        """Send a user message and get the agent's response."""
        result = await self._loop.run(message)
        self._message_count += 1
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
        old_id = self.session_id
        self.session_id = uuid4().hex[:12]
        self._message_count = 0

        prompt = self._self_edit_prompt if self.self_edit else self._system_prompt

        self._loop = AgentLoop(
            llm=self._provider,
            executor=self._executor,
            stream=self._stream,
            system_prompt=prompt,
            model=self.config.model,
            max_turns=self.config.max_turns,
        )

        await self._store.create_session(
            self.session_id,
            mode="self-edit" if self.self_edit else "normal",
        )

    async def toggle_self_edit(self) -> bool:
        """Toggle self-edit mode. Returns new state."""
        self.self_edit = not self.self_edit

        prompt = self._self_edit_prompt if self.self_edit else self._system_prompt

        # Create a new loop with the appropriate prompt
        self._loop = AgentLoop(
            llm=self._provider,
            executor=self._executor,
            stream=self._stream,
            system_prompt=prompt,
            model=self.config.model,
            max_turns=self.config.max_turns,
        )

        # New session for the new mode
        self.session_id = uuid4().hex[:12]
        self._message_count = 0
        await self._store.create_session(
            self.session_id,
            mode="self-edit" if self.self_edit else "normal",
        )

        return self.self_edit

    async def resume_session(self, session_id: str) -> bool:
        """Resume a previous session by replaying its messages."""
        from taui.store.events import EventType

        meta = await self._store.get_session(session_id)
        if meta is None:
            return False

        # Find the stream for this session
        stream_id = f"agents/{session_id}"
        if not await self._store.stream_exists(stream_id):
            # Try to find events under any stream — session may have used
            # the loop's auto-generated agent_id. For now, just reset.
            pass

        self.session_id = session_id
        self.self_edit = meta.get("mode") == "self-edit"
        self._message_count = meta.get("message_count", 0)

        prompt = self._self_edit_prompt if self.self_edit else self._system_prompt

        self._loop = AgentLoop(
            llm=self._provider,
            executor=self._executor,
            stream=self._stream,
            system_prompt=prompt,
            model=self.config.model,
            max_turns=self.config.max_turns,
        )

        # Try to replay messages from the store
        try:
            events = await self._store.read(stream_id, limit=5000)
            for event in events:
                if event.type == EventType.USER_MESSAGE:
                    self._loop._messages.append(
                        Message(role="user", content=event.data.get("text", ""))
                    )
                elif event.type == EventType.ASSISTANT_MESSAGE:
                    self._loop._messages.append(
                        Message(role="assistant", content=event.data.get("text", ""))
                    )
        except Exception:
            logger.debug("Could not replay session %s", session_id, exc_info=True)

        await self._store.update_session(session_id)
        return True

    async def list_sessions(self) -> list[dict]:
        """List recent sessions."""
        return await self._store.list_sessions()

    async def close(self) -> None:
        """Clean up resources."""
        # Disconnect MCP servers
        try:
            mcp_tool = self._registry.get("mcp")
            if hasattr(mcp_tool, "_manager") and mcp_tool._manager:
                await mcp_tool._manager.disconnect_all()
        except Exception:
            logger.debug("Error disconnecting MCP servers", exc_info=True)
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


# ── Self-edit system prompt ────────────────────────────────────────────────────

_SELF_EDIT_SYSTEM_PROMPT = """\
You are a taui self-edit agent. You can create, modify, or delete taui \
extensions — Python files in .taui/extensions/.

## Extension Convention

Every extension is a single .py file with a `register(tools, commands)` function.

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

def register(tools, commands):
    tools.register(MyTool())
```

### Command Extension

```python
from dataclasses import dataclass
from taui.commands.registry import CommandContext, CommandResult

@dataclass(slots=True)
class MyCommand:
    name: str = "mycommand"
    description: str = "What this command does"

    async def execute(self, ctx: CommandContext) -> CommandResult:
        return CommandResult.ok("output")

def register(tools, commands):
    if commands:
        commands.register(MyCommand())
```

## Rules
- Write files to .taui/extensions/<name>.py (create directory if needed)
- Read existing extension files before modifying them
- One extension per file
- Never modify core taui source files
- After writing, tell the user the extension will load on next restart

You also have full access to read and edit files in the workspace. You can \
help the user build, debug, and improve their taui setup.
"""
