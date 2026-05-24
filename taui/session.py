"""
Session — wires together LLM provider, tools, and agent loop.

A Session is the unit of interactive use. It owns:
- The LLM provider (authenticated)
- The tool registry and executor
- The agent loop
- The event store (optional)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from taui.agent.loop import AgentLoop, Message, RunResult
from taui.agent.variants import AgentVariantRegistry
from taui.config import Config
from taui.cost import CostTracker
from taui.extensions import ExtensionRegistry
from taui.extensions.builtins import (
    close_builtin_extensions,
    configure_builtin_extensions,
    new_hook_registry,
)
from taui.hooks import HookRegistry
from taui.prompt_builder import ProjectContext, SystemPromptBuilder
from taui.session_replay import ReplayItem
from taui.store.store import Store
from taui.store.stream import StreamClient
from taui.tasks import TaskManager, TaskRecord, TaskState
from taui.tools.background import BackgroundProcessRegistry
from taui.tools.base import ToolResult
from taui.tools.builtins import register_builtins
from taui.tools.executor import PolicyDecision, ToolExecutor, ToolPolicy
from taui.tools.registry import ToolRegistry
from taui.tools.truncation import TruncationStore
from taui.worktree import WorktreeHandle

logger = logging.getLogger(__name__)


async def _create_provider(config: Config):
    """Create and authenticate an LLM provider from config."""
    from taui.llm_provider.registry import create_provider

    return await asyncio.to_thread(create_provider, config.provider)


@dataclass
class _SessionSnapshot:
    """Frozen view of a main-session's in-memory state, used to restore on /exit."""
    session_id: str
    loop: AgentLoop
    message_count: int
    loaded_offset: int
    last_replay_items: list[ReplayItem] = field(default_factory=list)


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
        # Human-readable session label. Populated by the `session_name`
        # tool when it runs, and refreshed on resume from the store.
        self.description: str = ""
        self.extensions_mode = False
        self.self_edit_mode = False
        self._system_prompt: str = ""
        self._base_system_prompt: str = ""  # original prompt before variant overrides
        self._extensions_prompt: str = ""
        self._self_edit_prompt: str = ""
        self._self_edit_executor: ToolExecutor | None = None
        self._self_edit_scope: str = ""
        self._message_count = 0
        self._session_persisted = False
        self._loaded_offset = 0
        self._last_replay_items: list[ReplayItem] = []
        self.last_resume_error: str = ""
        self._base_policy_overrides: dict[str, PolicyDecision] = {}
        self._result_processors: list[Callable[[str, str, ToolResult], ToolResult]] = []
        self._builtin_tools: dict[str, Any] = {}
        self._pre_self_edit_state: _SessionSnapshot | None = None
        self._variant_registry: AgentVariantRegistry = AgentVariantRegistry()
        self._config_change_listeners: list[Callable[[], None]] = []
        self.worktree: WorktreeHandle | None = None
        self._task_manager: TaskManager = TaskManager()
        self._task_listeners: list[Callable[[TaskRecord], Any]] = []

    def add_config_change_listener(self, callback: Callable[[], None]) -> None:
        """Register a callback fired when the agent's prompt/tools/policy change.

        Used by the TUI to keep the rendered context banner (system prompt +
        tool list) in sync with hot-reloaded extensions, variant switches, and
        self-edit exits.
        """
        self._config_change_listeners.append(callback)

    def _notify_config_changed(self) -> None:
        for cb in list(getattr(self, "_config_change_listeners", ())):
            try:
                cb()
            except Exception:
                logger.exception("config-change listener raised")

    @classmethod
    async def create(cls, config: Config | None = None) -> Session:
        """Create a fully wired session."""
        if config is None:
            config = Config.load()

        # Provider
        provider = await _create_provider(config)

        # Tools
        registry = ToolRegistry()
        register_builtins(registry)
        # Set working_dir on all builtin tools
        for name in registry.names:
            tool = registry.get(name)
            if hasattr(tool, "working_dir"):
                tool.working_dir = config.working_dir

        # Wire file tracker on read/write/edit tools
        from taui.tools.file_tracker import FileTracker
        file_tracker = FileTracker()
        for name in ("read", "write", "edit"):
            if name in registry:
                tool = registry.get(name)
                if hasattr(tool, "_file_tracker"):
                    tool._file_tracker = file_tracker

        # Wire LSP manager into the lsp tool
        from taui.lsp import LspManager
        lsp_manager = LspManager(config.working_dir)
        if "lsp" in registry:
            tool = registry.get("lsp")
            if hasattr(tool, "_lsp_manager"):
                tool._lsp_manager = lsp_manager

        # Tool policy — safe defaults with config overrides
        policy_overrides: dict[str, PolicyDecision] = {}
        if config.auto_approve_reads:
            # Read-only tools auto-approved when configured
            for name in ("read", "glob", "grep"):
                policy_overrides[name] = PolicyDecision.AUTO
        # Apply explicit per-tool overrides from config file
        for tool_name, decision_str in config.tool_policy.items():
            try:
                policy_overrides[tool_name] = PolicyDecision(decision_str)
            except ValueError:
                logger.warning(
                    "Ignoring invalid tool_policy decision %r for %s",
                    decision_str,
                    tool_name,
                )
        policy = ToolPolicy(overrides=policy_overrides)

        # Pattern-based permission ruleset (project layer from config)
        if config.permission:
            from taui.permissions import PermissionRuleset

            ruleset = PermissionRuleset()
            ruleset.add_rules(config.permission, layer="project")
            policy.set_ruleset(ruleset)

        executor = ToolExecutor(registry=registry, policy=policy)

        # Truncation store — shared between the executor and the peek tool
        truncation_store = TruncationStore()
        executor._truncation_store = truncation_store
        # Wire the store into the peek tool so it can retrieve stored outputs
        try:
            peek_tool = registry.get("peek")
            peek_tool._truncation_store = truncation_store
        except ValueError:
            pass
        # Also wire the truncation store into tools that produce their own
        # peek-friendly envelopes (bash, grep, glob).
        for tool_name in ("bash", "grep", "glob"):
            try:
                t = registry.get(tool_name)
            except ValueError:
                continue
            if hasattr(t, "_truncation_store"):
                t._truncation_store = truncation_store

        # Background process registry — shared between bash / bash_status /
        # bash_kill so a job started by one tool is visible to the others.
        bg_registry = BackgroundProcessRegistry()
        executor._bg_registry = bg_registry  # used by Session.close
        for tool_name in ("bash", "bash_status", "bash_kill"):
            try:
                t = registry.get(tool_name)
            except ValueError:
                continue
            if hasattr(t, "_bg_registry"):
                t._bg_registry = bg_registry

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
        builtin_tools = {name: registry.get(name) for name in registry.names}
        extra_dirs = [Path(d) for d in config.extension_dirs]
        ext_registry = ExtensionRegistry(
            config.working_dir,
            include_builtins=True,
            extra_dirs=extra_dirs,
        )
        ext_registry.discover()
        hooks = new_hook_registry()

        # Create variant and context strategy registries before loading extensions
        # so extensions can register their own variants, strategies, and providers.
        from taui.agent.context_strategy import ContextStrategyRegistry
        from taui.llm_provider.ext_registry import ProviderRegistrationProxy

        variant_registry = AgentVariantRegistry()
        variant_registry.discover_from_dir(config.working_dir / ".taui" / "agents")
        context_strategy_registry = ContextStrategyRegistry()
        provider_proxy = ProviderRegistrationProxy()

        ext_registry.load_all(
            tools=registry,
            commands=None,
            hooks=hooks,
            policy=executor.policy,
            agents=variant_registry,
            context=context_strategy_registry,
            providers=provider_proxy,
        )

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
            model_variant=config.model_variant,
            max_turns=config.max_turns,
            provider_name=config.provider,
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
        from taui.self_edit.factory import build_self_edit_executor, build_self_edit_system_prompt

        session._system_prompt = system_prompt
        session._base_system_prompt = system_prompt
        session._extensions_prompt = _EXTENSIONS_SYSTEM_PROMPT
        session._lsp_manager = lsp_manager
        session._self_edit_prompt = build_self_edit_system_prompt(config.working_dir)
        session._self_edit_executor = build_self_edit_executor(
            registry,
            executor,
            config.working_dir,
        )
        session._builtin_tool_names = builtin_tool_names
        session._builtin_tools = builtin_tools
        session._base_policy_overrides = policy_overrides
        # Wire pre-built registries (variants discovered and extensions already loaded)
        session._variant_registry = variant_registry
        session._context_strategy_registry = context_strategy_registry
        configure_builtin_extensions(session)
        session._wire_session_name_tool()
        session._wire_worktree_tool()
        session._wire_task_manager()
        session._refresh_loop_integrations()

        # Wire skill paths bundled by extensions into the skill registry.
        skill_reg = getattr(session, "_skill_registry", None)
        if skill_reg is not None:
            for name in ext_registry.names:
                ext = ext_registry.get(name)
                if ext and ext.skill_paths:
                    for p in ext.skill_paths:
                        skill_reg.add_from_path(p, scope=ext.scope)

        # Materialize the stream so the agent loop can emit events, but defer
        # creating the session record until the first message is actually sent
        # (avoids cluttering the session list with empty sessions).
        await stream.ensure_stream(session._loop.stream_id)
        session._loaded_offset = await stream.get_length(session._loop.stream_id)
        session._session_persisted = False

        return session

    async def send(
        self,
        message: str,
        *,
        images: list[str] | None = None,
    ) -> RunResult:
        """Send a user message and get the agent's response.

        *images* is an optional list of data-URL encoded images to attach.
        """
        await self._sync_replay_from_store()

        # Lazily persist the session record on first message
        if not self._session_persisted:
            await self._store.create_session(
                self.session_id,
                stream_id=self._loop.stream_id,
                model=self.config.model,
                model_variant=self.config.model_variant,
            )
            self._session_persisted = True

        # Pipeline hook: let extensions preprocess the message
        message = await self.hooks.transform("before_send", message, self)

        result = await self._loop.run(message, images=images)
        self._message_count += 1
        if self._message_count == 1:
            self.first_message = message.strip().split("\n", 1)[0][:60]
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
        # Update session metadata. Descriptions come from the session_name tool;
        # if the agent didn't call it, /sessions falls back to first_message.
        try:
            kwargs: dict[str, Any] = {"message_count": self._message_count}
            # Persist the first user message for display in session lists
            if self._message_count == 1:
                # Clip to first 60 chars of the first line
                snippet = message.strip().split("\n", 1)[0][:60]
                kwargs["first_message"] = snippet
            await self._store.update_session(self.session_id, **kwargs)
        except Exception:
            logger.debug("Failed to update session metadata", exc_info=True)
        return result

    async def new_session(self) -> None:
        """Start a fresh session — new loop, new agent, same store."""
        self.session_id = uuid4().hex[:12]
        self.description = ""
        self._message_count = 0
        self.first_message = ""
        self._last_replay_items = []

        if self.self_edit_mode:
            prompt = self._self_edit_prompt
            executor = self._self_edit_executor or self._executor
        else:
            prompt = self._extensions_prompt if self.extensions_mode else self._system_prompt
            executor = self._executor

        agent_id = "SEF" if self.self_edit_mode else self.session_id
        loop = AgentLoop(
            agent_id=agent_id,
            llm=self._provider,
            executor=executor,
            stream=self._stream,
            system_prompt=prompt,
            model=self.config.model,
            model_variant=self.config.model_variant,
            max_turns=self.config.max_turns,
            provider_name=self.config.provider,
        )
        self._replace_loop(loop)

        mode = "self_edit" if self.self_edit_mode else (
            "extensions" if self.extensions_mode else "normal"
        )
        await self._store.create_session(
            self.session_id,
            mode=mode,
            stream_id=self._loop.stream_id,
            model=self.config.model,
            model_variant=self.config.model_variant,
        )
        self._session_persisted = True
        await self._stream.ensure_stream(self._loop.stream_id)
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
        self.first_message = ""
        self._last_replay_items = []

        loop = AgentLoop(
            agent_id=self.session_id,
            llm=self._provider,
            executor=self._executor,
            stream=self._stream,
            system_prompt=prompt,
            model=self.config.model,
            model_variant=self.config.model_variant,
            max_turns=self.config.max_turns,
            provider_name=self.config.provider,
        )
        self._replace_loop(loop)

        # New session for the new mode
        await self._store.create_session(
            self.session_id,
            mode="extensions" if self.extensions_mode else "normal",
            stream_id=self._loop.stream_id,
            model=self.config.model,
            model_variant=self.config.model_variant,
        )
        self._session_persisted = True
        await self._stream.ensure_stream(self._loop.stream_id)
        self._loaded_offset = await self._stream.get_length(self._loop.stream_id)

        # Observer hook
        await self.hooks.run(
            "on_mode_change",
            "extensions" if self.extensions_mode else "normal",
            self,
        )

        return self.extensions_mode

    async def toggle_self_edit_mode(self) -> bool:
        """Toggle self-edit mode. Returns new state.

        Entering self-edit snapshots the current main-session state (id, loop,
        offsets) so that exiting restores it instead of creating a fresh, empty
        main session.
        """
        entering = not self.self_edit_mode
        self.self_edit_mode = entering

        if entering:
            self._pre_self_edit_state = _SessionSnapshot(
                session_id=self.session_id,
                loop=self._loop,
                message_count=self._message_count,
                loaded_offset=self._loaded_offset,
                last_replay_items=list(self._last_replay_items),
            )

            from taui.self_edit.factory import (
                build_self_edit_executor,
                build_self_edit_system_prompt,
            )
            from taui.self_edit.store import SelfEditStore
            self._self_edit_prompt = build_self_edit_system_prompt(
                self.config.working_dir
            )
            self._self_edit_executor = build_self_edit_executor(
                self._registry,
                self._executor,
                self.config.working_dir,
            )
            self._self_edit_scope = SelfEditStore(
                self.config.working_dir
            ).load_default_scope()
            prompt = self._self_edit_prompt
            executor = self._self_edit_executor or self._executor

            self.session_id = uuid4().hex[:12]
            self._message_count = 0
            self.first_message = ""
            self._last_replay_items = []

            loop = AgentLoop(
                agent_id="SEF",
                llm=self._provider,
                executor=executor,
                stream=self._stream,
                system_prompt=prompt,
                model=self.config.model,
                model_variant=self.config.model_variant,
                max_turns=self.config.max_turns,
                provider_name=self.config.provider,
            )
            self._replace_loop(loop)

            await self._store.create_session(
                self.session_id,
                mode="self_edit",
                stream_id=self._loop.stream_id,
                model=self.config.model,
                model_variant=self.config.model_variant,
            )
            self._session_persisted = True
            await self._stream.ensure_stream(self._loop.stream_id)
            self._loaded_offset = await self._stream.get_length(self._loop.stream_id)
            self._notify_config_changed()
            return self.self_edit_mode

        # Exiting self-edit — hot-reload extensions, rebuild the system prompt,
        # restore the prior main session, and apply the rebuilt prompt to its
        # loop so user edits take effect without a new session.
        self._self_edit_scope = ""
        snap = self._pre_self_edit_state
        self._pre_self_edit_state = None

        try:
            self.reload_extensions()
        except Exception:
            logger.exception("reload_extensions failed during self-edit exit")
        try:
            self._variant_registry.discover_from_dir(
                self.config.working_dir / ".taui" / "agents"
            )
        except Exception:
            logger.exception("variant re-discovery failed during self-edit exit")
        await self._rebuild_system_prompt()

        prompt = self._extensions_prompt if self.extensions_mode else self._system_prompt

        if snap is not None:
            self.session_id = snap.session_id
            self._replace_loop(snap.loop)
            self._message_count = snap.message_count
            self._loop.update_system_prompt(prompt)
            # Rebuild replay items from the stream so the TUI can re-render the
            # transcript. The snapshot's items are typically empty because they
            # are only populated on resume, not on plain send().
            await self._replay_stream()
            self._notify_config_changed()
            return self.self_edit_mode

        # Fallback (no snapshot, e.g. self-edit was the initial mode): make a
        # fresh main session.
        executor = self._executor

        self.session_id = uuid4().hex[:12]
        self._message_count = 0
        self.first_message = ""
        self._last_replay_items = []

        loop = AgentLoop(
            agent_id=self.session_id,
            llm=self._provider,
            executor=executor,
            stream=self._stream,
            system_prompt=prompt,
            model=self.config.model,
            model_variant=self.config.model_variant,
            max_turns=self.config.max_turns,
            provider_name=self.config.provider,
        )
        self._replace_loop(loop)

        mode = "extensions" if self.extensions_mode else "normal"
        await self._store.create_session(
            self.session_id,
            mode=mode,
            stream_id=self._loop.stream_id,
            model=self.config.model,
            model_variant=self.config.model_variant,
        )
        self._session_persisted = True
        await self._stream.ensure_stream(self._loop.stream_id)
        self._loaded_offset = await self._stream.get_length(self._loop.stream_id)
        self._notify_config_changed()
        return self.self_edit_mode

    async def _rebuild_system_prompt(self) -> None:
        """Rebuild the main system prompt from current project + tool state.

        Picks up CLAUDE.md edits, tool-registry changes, and `system_prompt`
        hook contributions from freshly-reloaded extensions.
        """
        builder = SystemPromptBuilder()
        try:
            ctx = ProjectContext.discover_with_git(self.config.working_dir)
        except Exception:
            ctx = ProjectContext.discover(self.config.working_dir)
        builder.with_project_context(ctx)
        builder.with_tools(self._registry)
        prompt = builder.render()
        if self.hooks.has("system_prompt"):
            prompt = await self.hooks.transform("system_prompt", prompt, None)
        self._system_prompt = prompt
        self._base_system_prompt = prompt

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
        self.description = str(meta.get("description") or "")
        self.extensions_mode = meta.get("mode") == "extensions"
        self.self_edit_mode = meta.get("mode") == "self_edit"
        self._message_count = meta.get("message_count", 0)
        self.first_message = str(meta.get("first_message") or "")
        self._session_persisted = True

        # Restore model from session metadata
        saved_model = str(meta.get("model") or "")
        if saved_model:
            self.config.model = saved_model
        self.config.model_variant = str(meta.get("model_variant") or "")

        if self.self_edit_mode:
            from taui.self_edit.factory import build_self_edit_executor

            self._self_edit_executor = build_self_edit_executor(
                self._registry,
                self._executor,
                self.config.working_dir,
            )
            prompt = self._self_edit_prompt
            executor = self._self_edit_executor or self._executor
        else:
            prompt = self._extensions_prompt if self.extensions_mode else self._system_prompt
            executor = self._executor

        agent_id = "SEF" if self.self_edit_mode else _agent_id_from_stream(stream_id, session_id)
        loop = AgentLoop(
            agent_id=agent_id,
            llm=self._provider,
            executor=executor,
            stream=self._stream,
            system_prompt=prompt,
            model=self.config.model,
            model_variant=self.config.model_variant,
            max_turns=self.config.max_turns,
            provider_name=self.config.provider,
        )
        loop.stream_id = stream_id
        self._replace_loop(loop)

        await self._replay_stream()

        await self._store.update_session(session_id)
        return True

    async def list_sessions(self) -> list[dict]:
        """List recent sessions with parent relationships."""
        return await self._store.list_sessions_with_parents()

    def reload_extensions(self) -> list[str]:
        """Hot-reload extensions: unload, re-discover, re-load.

        Returns names of loaded extensions.
        """
        # Remove extension-added tools
        builtin = getattr(self, "_builtin_tool_names", set())
        ext_tools = [n for n in self._registry.names if n not in builtin]
        for name in ext_tools:
            self._registry.unregister(name)
        for name, tool in getattr(self, "_builtin_tools", {}).items():
            self._registry.register_or_replace(tool)

        self._executor.policy.set_overrides(
            getattr(self, "_base_policy_overrides", {})
        )

        # Clear all hooks (only extensions register hooks)
        self.hooks.clear()

        # Unload, re-discover, re-load
        if self._ext_registry:
            self._ext_registry.unload_all()
            self._ext_registry.discover()
            try:
                from taui.llm_provider.ext_registry import ProviderRegistrationProxy

                loaded_all = self._ext_registry.load_all(
                    tools=self._registry,
                    commands=None,
                    hooks=self.hooks,
                    policy=self._executor.policy,
                    agents=getattr(self, "_variant_registry", None),
                    context=getattr(self, "_context_strategy_registry", None),
                    providers=ProviderRegistrationProxy(),
                )
            except Exception:
                logger.exception("Failed during extension reload")
                loaded_all = []
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

    async def fork(self, *, at_offset: int | None = None) -> Session:
        """Fork this session at an offset, creating a branched session.

        The fork gets its own stream with parent_id linked to the original.
        Messages up to at_offset are copied. The original session is unchanged.
        """
        fork_id = uuid4().hex[:12]
        parent_stream = self._loop.stream_id
        fork_stream = f"agents/{fork_id}"

        # Create the forked stream with parent link
        await self._stream.ensure_stream(fork_stream, parent_id=parent_stream)

        # Copy events up to offset
        if at_offset is not None:
            events = await self._store.read(parent_stream, from_offset=0, limit=at_offset)
            for event in events:
                await self._store.append(fork_stream, event.type, event.data, offset=event.offset)

        prompt = self._extensions_prompt if self.extensions_mode else self._system_prompt
        loop = AgentLoop(
            agent_id=fork_id,
            llm=self._provider,
            executor=self._executor,
            stream=self._stream,
            system_prompt=prompt,
            model=self.config.model,
            model_variant=self.config.model_variant,
            max_turns=self.config.max_turns,
            provider_name=self.config.provider,
        )
        loop.stream_id = fork_stream

        # Replay messages into the new loop
        transcript = await self._stream.load_conversation(fork_stream)
        loop._messages = [Message(role="system", content=prompt)]
        loop._messages.extend(transcript.messages)

        forked = Session(
            config=self.config,
            provider=self._provider,
            registry=self._registry,
            executor=self._executor,
            store=self._store,
            stream=self._stream,
            loop=loop,
            cost_tracker=self.cost_tracker,
            hooks=self.hooks,
            session_id=fork_id,
        )
        forked._system_prompt = self._system_prompt
        forked._base_system_prompt = self._base_system_prompt
        forked._extensions_prompt = self._extensions_prompt

        await self._store.create_session(
            fork_id,
            stream_id=fork_stream,
            model=self.config.model,
            model_variant=self.config.model_variant,
        )
        forked._loaded_offset = await self._stream.get_length(fork_stream)

        return forked

    async def create_sub_session(
        self,
        *,
        name: str | None = None,
        tools: list[str] | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
        max_turns: int | None = None,
    ) -> Session:
        """Create a sub-session with optional overrides.

        Reuses the parent's store and provider. The sub-session's stream
        has parent_id set to the current session's stream.
        """
        sub_id = name or uuid4().hex[:12]
        sub_stream = f"agents/{sub_id}"

        # Tool registry — subset or full
        if tools:
            registry = self._registry.subset(tools)
        else:
            registry = self._registry

        executor = ToolExecutor(
            registry=registry,
            policy=self._executor.policy,
            timeout=self._executor._timeout,
        )

        prompt = system_prompt or self._system_prompt
        mdl = model or self.config.model
        turns = max_turns or self.config.max_turns

        await self._stream.ensure_stream(sub_stream, parent_id=self._loop.stream_id)

        loop = AgentLoop(
            agent_id=sub_id,
            llm=self._provider,
            executor=executor,
            stream=self._stream,
            system_prompt=prompt,
            model=mdl,
            max_turns=turns,
            provider_name=self.config.provider,
        )
        loop.stream_id = sub_stream

        sub = Session(
            config=self.config,
            provider=self._provider,
            registry=registry,
            executor=executor,
            store=self._store,
            stream=self._stream,
            loop=loop,
            cost_tracker=self.cost_tracker,
            hooks=self.hooks,
            session_id=sub_id,
        )
        sub._system_prompt = prompt

        await self._store.create_session(
            sub_id,
            stream_id=sub_stream,
            model=self.config.model,
            model_variant=self.config.model_variant,
        )
        sub._loaded_offset = 0

        return sub

    def add_result_processor(
        self,
        fn: Callable[[str, str, ToolResult], ToolResult],
    ) -> None:
        """Register a post-processor for tool results.

        fn(tool_name, call_id, result) -> ToolResult

        Processors run in order after each tool execution, before the result
        is written to the stream. Use for secret redaction, content tagging, etc.
        """
        self._result_processors.append(fn)

    async def close(self) -> None:
        """Clean up resources."""
        try:
            await self._task_manager.shutdown()
        except Exception:
            logger.debug("Error shutting down task manager", exc_info=True)
        await close_builtin_extensions(self)
        if hasattr(self, "_lsp_manager"):
            try:
                await self._lsp_manager.stop_all()
            except Exception:
                logger.debug("Error stopping LSP manager", exc_info=True)
        bg_registry = getattr(self._executor, "_bg_registry", None)
        if bg_registry is not None:
            try:
                await bg_registry.shutdown()
            except Exception:
                logger.debug("Error shutting down bg processes", exc_info=True)
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
    def model_variant(self) -> str:
        return self.config.model_variant

    @property
    def working_dir(self) -> Path:
        return self.config.working_dir

    @property
    def self_edit_scope(self) -> str:
        """Active self-edit scope: 'global', 'project', or '' if not in self-edit."""
        return self._self_edit_scope

    async def switch_self_edit_scope(self) -> str:
        """Toggle self-edit scope between 'global' and 'project' in place."""
        if not self.self_edit_mode:
            return self._self_edit_scope

        from taui.self_edit.factory import (
            build_self_edit_executor,
            build_self_edit_system_prompt,
        )
        from taui.self_edit.store import SelfEditStore

        new_scope = "project" if self._self_edit_scope == "global" else "global"
        SelfEditStore(self.config.working_dir).save_default_scope(new_scope)
        self._self_edit_scope = new_scope
        self._self_edit_prompt = build_self_edit_system_prompt(self.config.working_dir)

        self._self_edit_executor = build_self_edit_executor(
            self._registry,
            self._executor,
            self.config.working_dir,
        )
        self._loop._executor = self._self_edit_executor
        self._loop.update_system_prompt(self._self_edit_prompt)
        self._notify_config_changed()
        return new_scope

    def switch_variant(self, name: str) -> bool:
        """Apply a named agent variant to the current loop.

        Adjusts tool availability, system prompt, and executor based on the variant
        configuration. Returns True on success, False if the variant is not found.
        """
        from taui.tools.base import ToolCategory

        variant = self._variant_registry.get(name)
        if variant is None:
            logger.warning("Unknown agent variant: %r", name)
            return False

        # Build the effective tool registry for this variant
        if variant.tool_names is not None:
            # Explicit tool subset
            available = [n for n in variant.tool_names if n in self._registry]
            effective_registry = self._registry.subset(available)
        elif variant.read_only:
            # Exclude write/shell/git categories
            excluded = {ToolCategory.FILE_WRITE, ToolCategory.SHELL, ToolCategory.GIT}
            allowed = [
                t.name
                for t in self._registry._tools.values()
                if t.category not in excluded
            ]
            effective_registry = self._registry.subset(allowed)
        else:
            effective_registry = self._registry

        # Build executor with the effective registry
        from taui.tools.executor import ToolExecutor

        effective_executor = ToolExecutor(
            registry=effective_registry,
            policy=self._executor.policy,
        )
        effective_executor._truncation_store = getattr(
            self._executor, "_truncation_store", None
        )

        # Apply permission overrides from variant if present
        if variant.permission:
            from taui.permissions import PermissionRuleset

            ruleset = PermissionRuleset()
            ruleset.add_rules(variant.permission, layer="variant")
            effective_executor.policy.set_ruleset(ruleset)

        # Determine system prompt
        if variant.system_prompt is not None:
            prompt = variant.system_prompt
        else:
            prompt = self._base_system_prompt

        self._system_prompt = prompt
        self._loop._executor = effective_executor
        self._loop.update_system_prompt(prompt)
        self._notify_config_changed()
        return True

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

    @property
    def task_manager(self) -> TaskManager:
        """Per-session background TaskManager."""
        return self._task_manager

    def add_task_listener(self, cb: Callable[[TaskRecord], Any]) -> None:
        """Register a callback invoked on every background task state change.

        Used by the TUI sidebar / desktop notification extensions to surface
        progress and completion without polling.
        """
        self._task_listeners.append(cb)

    async def _on_task_state_change(self, record: TaskRecord) -> None:
        # Fan-out to in-process listeners (TUI sidebar, etc.)
        for cb in list(self._task_listeners):
            try:
                result = cb(record)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.debug("Task listener raised", exc_info=True)
        # Fire the extension hook on terminal transitions so desktop-notify
        # extensions can surface "task done" to the operator.
        if record.state in (TaskState.DONE, TaskState.FAILED, TaskState.CANCELLED):
            try:
                await self.hooks.run("on_task_done", record, self)
            except Exception:
                logger.debug("on_task_done hook raised", exc_info=True)

    def _wire_task_manager(self) -> None:
        """Inject the TaskManager into task_* tools and configure its runner."""
        # The manager is created in __init__ as a stable reference; here we
        # wire it up to the stream + runner once we have all the dependencies.
        mgr = self._task_manager
        mgr.set_stream(self._stream, self._loop.stream_id)
        mgr.set_state_listener(self._on_task_state_change)

        async def runner(record: TaskRecord, cancel_event: asyncio.Event) -> None:
            """Spawn a sub-session for this task and shuttle its result back."""
            sub = await self.create_sub_session(
                name=f"task-{record.id}",
                tools=record.tools,
                model=record.model,
                max_turns=record.max_turns,
            )
            record.stream_id = sub._loop.stream_id
            # Race the sub-agent's run against the cancel signal.
            run_task = asyncio.create_task(sub.send(record.prompt))
            cancel_task = asyncio.create_task(cancel_event.wait())
            try:
                done, _ = await asyncio.wait(
                    {run_task, cancel_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancel_task in done and not run_task.done():
                    run_task.cancel()
                    try:
                        await run_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    record.last_output = "(cancelled by operator)"
                    return
                result = await run_task
                record.result = result.text or ""
                record.turns = result.turns
            finally:
                if not cancel_task.done():
                    cancel_task.cancel()
                try:
                    await sub.close()
                except Exception:
                    logger.debug("Error closing sub-session", exc_info=True)

        mgr.set_runner(runner)

        # Inject the manager into every task_* tool that has set_manager.
        for name in (
            "task_create",
            "task_get",
            "task_list",
            "task_output",
            "task_stop",
            "task_update",
        ):
            try:
                tool = self._registry.get(name)
            except ValueError:
                continue
            if hasattr(tool, "set_manager"):
                tool.set_manager(mgr)

    def _wire_session_name_tool(self) -> None:
        """Give the session_name tool a callback that writes the description."""
        try:
            tool = self._registry.get("session_name")
        except ValueError:
            return

        async def set_name(name: str) -> None:
            self.description = name
            try:
                await self._store.update_session(
                    self.session_id, description=name,
                )
            except Exception:
                logger.debug(
                    "Failed to save session name", exc_info=True,
                )

        tool._set_name = set_name

    def _wire_worktree_tool(self) -> None:
        """Give the worktree tool callbacks to mutate session cwd + persist events."""
        try:
            tool = self._registry.get("worktree")
        except ValueError:
            return

        async def on_enter(handle: WorktreeHandle) -> None:
            await self._apply_worktree(handle)

        async def on_exit(keep: bool) -> None:
            await self._clear_worktree(keep=keep)

        def get_handle() -> WorktreeHandle | None:
            return self.worktree

        tool._on_enter = on_enter
        tool._on_exit = on_exit
        tool._get_handle = get_handle
        tool._session_id = self.session_id

    def _set_tools_cwd(self, cwd: Path) -> None:
        """Update working_dir on every tool that exposes one."""
        for name in self._registry.names:
            t = self._registry.get(name)
            if hasattr(t, "working_dir"):
                t.working_dir = cwd

    async def _apply_worktree(self, handle: WorktreeHandle) -> None:
        """Adopt a new worktree: rebind tool cwd and persist a WORKTREE event."""
        from taui.store.events import EventType

        self.worktree = handle
        self._set_tools_cwd(handle.path)
        try:
            await self._store.append(
                self._loop.stream_id,
                EventType.WORKTREE,
                {
                    "action": "enter",
                    "path": str(handle.path),
                    "branch": handle.branch,
                    "base": handle.base,
                    "origin": str(handle.origin),
                },
            )
        except Exception:
            logger.debug("Failed to persist worktree-enter event", exc_info=True)
        self._notify_config_changed()

    async def _clear_worktree(self, *, keep: bool) -> None:
        """Drop the active worktree handle and restore the original cwd."""
        from taui.store.events import EventType

        prior = self.worktree
        self.worktree = None
        self._set_tools_cwd(self.config.working_dir)
        if prior is None:
            return
        try:
            await self._store.append(
                self._loop.stream_id,
                EventType.WORKTREE,
                {
                    "action": "exit",
                    "kept": keep,
                    "path": str(prior.path),
                    "branch": prior.branch,
                },
            )
        except Exception:
            logger.debug("Failed to persist worktree-exit event", exc_info=True)
        self._notify_config_changed()

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

        def process_result(name: str, call_id: str, content: str) -> str:
            result = ToolResult.ok(content)
            for fn in self._result_processors:
                result = fn(name, call_id, result)
            return result.content

        self._loop._on_result_process = process_result

    async def _replay_stream(self) -> None:
        transcript = await self._stream.load_conversation(self._loop.stream_id)
        if self.self_edit_mode:
            prompt = self._self_edit_prompt
        else:
            prompt = self._extensions_prompt if self.extensions_mode else self._system_prompt
        self._loop._messages = [Message(role="system", content=prompt)]
        self._loop._messages.extend(transcript.messages)
        self._last_replay_items = transcript.items
        self._message_count = sum(1 for msg in transcript.messages if msg.role == "user")
        self._loaded_offset = await self._stream.get_length(self._loop.stream_id)
        await self._restore_worktree_from_events()

    async def _restore_worktree_from_events(self) -> None:
        """Re-bind the session to the worktree active at the end of the stream.

        Reads WORKTREE events in order; the last unmatched ``enter`` wins. If
        the recorded path no longer exists on disk, the handle is dropped.
        """
        from taui.store.events import EventType

        try:
            events = await self._stream.read_all(self._loop.stream_id)
        except Exception:
            logger.debug("worktree restore: read_all failed", exc_info=True)
            return

        active: WorktreeHandle | None = None
        for event in events:
            if event.type != EventType.WORKTREE:
                continue
            action = event.data.get("action")
            if action == "enter":
                path = event.data.get("path")
                branch = event.data.get("branch")
                base = event.data.get("base", "")
                origin = event.data.get("origin", str(self.config.working_dir))
                if isinstance(path, str) and isinstance(branch, str):
                    active = WorktreeHandle(
                        path=Path(path),
                        branch=branch,
                        base=base if isinstance(base, str) else "",
                        origin=Path(origin),
                    )
            elif action == "exit":
                active = None

        if active is not None and not active.path.exists():
            logger.info(
                "worktree restore: path missing, dropping handle (%s)",
                active.path,
            )
            active = None

        if active is None:
            self.worktree = None
            self._set_tools_cwd(self.config.working_dir)
            return

        self.worktree = active
        self._set_tools_cwd(active.path)

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

Legacy extensions can also use `register(tools, commands, hooks)`.

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
