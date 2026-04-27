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

from taui.agent.loop import AgentLoop, RunResult
from taui.config import Config
from taui.llm_provider.auth import get_credentials
from taui.llm_provider.providers import CodexProvider, CopilotProvider
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
    ) -> None:
        self.config = config
        self._provider = provider
        self._registry = registry
        self._executor = executor
        self._store = store
        self._stream = stream
        self._loop = loop

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

        # Build system prompt with tool guidelines
        system_prompt = config.system_prompt
        guidelines = registry.guidelines()
        if guidelines:
            system_prompt = system_prompt.rstrip() + "\n\n" + guidelines

        # Store
        store = Store(config.working_dir)
        await store.connect()
        stream = StreamClient(store)

        # Agent
        loop = AgentLoop(
            llm=provider,
            executor=executor,
            stream=stream,
            system_prompt=system_prompt,
            model=config.model,
            max_turns=config.max_turns,
        )

        return cls(
            config=config,
            provider=provider,
            registry=registry,
            executor=executor,
            store=store,
            stream=stream,
            loop=loop,
        )

    async def send(self, message: str) -> RunResult:
        """Send a user message and get the agent's response."""
        return await self._loop.run(message)

    async def close(self) -> None:
        """Clean up resources."""
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
