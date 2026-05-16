# Session and Configuration

## Session as Composition Root

`Session` (`taui/session.py`) is the central wiring point for a single interactive agent
session. It owns and connects:

- An authenticated LLM provider
- The tool registry and executor
- An `AgentLoop` (the think → tool → observe state machine)
- The SQLite event store and stream client
- Extension registry and hook registry
- A cost tracker
- Self-edit and variant sub-systems

`Session.__init__` takes all components as keyword arguments. `Session.create()` is the
only supported way to build a fully wired session from a `Config`.

---

## `Session.create()` Wiring Sequence

```python
session = await Session.create(config)
```

1. **Provider** — `_create_provider(config)` runs `create_provider(config.provider)` in
   a thread and returns an authenticated LLM provider.

2. **Tool registry** — `ToolRegistry` is created and builtin tools are registered via
   `register_builtins(registry)`. `working_dir` is set on every tool that declares it.

3. **File tracker** — A `FileTracker` is wired into `read`, `write`, and `edit` tools.

4. **LSP manager** — `LspManager(config.working_dir)` is created and injected into the
   `lsp` tool if present.

5. **Tool policy** — A `ToolPolicy` is built with `PolicyDecision` overrides:
   - `auto_approve_reads=True` auto-approves `read`, `glob`, and `grep`.
   - `config.tool_policy` provides explicit per-tool string overrides (validated against
     `PolicyDecision` enum).
   - `config.permission` populates a `PermissionRuleset` at the `"project"` layer.

6. **ToolExecutor** — `ToolExecutor(registry, policy)` is created. A shared
   `TruncationStore` is wired into the executor and the `peek` tool.

7. **System prompt** — `SystemPromptBuilder` discovers `ProjectContext` (with git
   metadata when available), injects tool metadata and adaptive guidelines, then renders
   the final prompt string.

8. **Store and stream** — `Store(config.working_dir)` is connected (WAL mode, creates
   `.taui/store.db`). A `StreamClient` is created over the store.

9. **Extension registry** — `ExtensionRegistry` is created with `include_builtins=True`
   and any `config.extension_dirs`. `discover()` finds all extension files.

10. **Variant and context strategy registries** — `AgentVariantRegistry` discovers from
    `.taui/agents/`. `ContextStrategyRegistry` and `ProviderRegistrationProxy` are
    created for extension use.

11. **Extension loading** — `ext_registry.load_all(tools, commands=None, hooks, policy,
    agents, context, providers)` loads all discovered extensions, which may register
    tools, hooks, policy overrides, variants, and context strategies.

12. **System prompt hook** — If any extension registered a `system_prompt` hook, the
    prompt is run through `hooks.transform("system_prompt", prompt, None)`.

13. **AgentLoop** — Created with `agent_id=session_id`, provider, executor, stream,
    system prompt, model, and `max_turns`.

14. **Session instantiation** — The `Session` object is constructed with all wired
    components.

15. **Post-wiring** — Self-edit prompt and executor are built, variant registry is
    attached, `configure_builtin_extensions(session)` is called, `session_name` tool is
    wired with a callback, and `_refresh_loop_integrations()` injects the skills and
    result-processor pipeline into the loop.

16. **Skill paths from extensions** — Any extension-bundled skill paths are registered
    into the skill registry.

17. **Store registration** — Session is written to the store and its stream is
    materialized. The initial stream offset is saved so future resumes work even if no
    messages were sent.

---

## Session Public API

### `send(message, *, images=None) -> RunResult`

Sends a user message and drives the agent loop for one conversation turn.

1. `_sync_replay_from_store()` — checks if the stream has grown externally and replays
   if needed.
2. `hooks.transform("before_send", message, self)` — extension preprocessing.
3. `loop.run(message, images=images)` — the agent loop runs to completion.
4. `hooks.transform("after_result", result, self)` — extension postprocessing.
5. Token usage from `result.turn_results` is recorded into `cost_tracker`.
6. Session metadata is updated in the store.

### `new_session()`

Discards the current loop and creates a fresh one with the same provider, executor, and
store. Chooses the appropriate system prompt based on current mode (self-edit /
extensions / normal). Registers the new session in the store and runs the
`on_session_start` hook.

### `toggle_extensions_mode() -> bool`

Toggles `extensions_mode`. Applies or removes the write guard on `write` and `edit`
tools (restricts writes to `.taui/` when active). Creates a new loop with the extensions
system prompt or the normal system prompt. Runs the `on_mode_change` hook.

### `toggle_self_edit_mode() -> bool`

**Entering**: snapshots the current session state as `_SessionSnapshot` (session ID,
loop, message count, loaded offset). Creates a new loop with the self-edit prompt and
executor using `agent_id="SEF"`. Registers the self-edit session in the store.

**Exiting**: restores the snapshot — the original loop and message count are put back,
and `_replay_stream()` re-loads the transcript so the TUI can re-render it. If no
snapshot exists (self-edit was the initial mode), a fresh normal session is created.

### `resume_session(session_id) -> bool`

Loads session metadata from the store. Validates that a replayable stream exists.
Creates a new loop with the correct prompt and executor for the session's mode. Sets
`loop.stream_id` to the stored stream ID, calls `_replay_stream()`, and updates last
active timestamp. Returns `False` and sets `last_resume_error` on any failure.

### `list_sessions() -> list[dict]`

Delegates to `store.list_sessions_with_parents()`. Returns metadata dicts including
`session_id`, `description`, `mode`, `message_count`, `created_at`, `last_active`, and
`parent_session_id`.

### `reload_extensions() -> list[str]`

Hot-reloads all extensions without restarting the session:
1. Removes extension-added tools from the registry; restores builtins.
2. Resets policy overrides to the base config values.
3. Clears all hooks.
4. Unloads, re-discovers, and re-loads all extension files.
5. Re-applies `working_dir` to new tools.
6. Re-applies the write guard if in extensions mode.

Returns the names of the newly loaded (non-builtin) extensions.

### `fork(*, at_offset=None) -> Session`

Creates a branched session. A new stream with `parent_id` set to the current stream is
materialized. Events up to `at_offset` are copied. A new `AgentLoop` replays the copied
messages. The forked `Session` shares the same provider, registry, executor, store, and
cost tracker as the parent.

### `create_sub_session(*, name, tools, system_prompt, model, max_turns) -> Session`

Creates a child session (used by the sub-agent tool). The sub-stream has `parent_id`
set to the current session's stream. If `tools` is provided, a registry subset is
used. All overrides default to the parent's values.

### `add_result_processor(fn)`

Registers a post-processor `fn(tool_name, call_id, result) -> ToolResult` that runs
after each tool execution. Processors are chained in registration order. Used for secret
redaction, content tagging, and similar cross-cutting concerns.

### `switch_self_edit_scope() -> str`

Toggles `_self_edit_scope` between `"global"` and `"project"` while in self-edit mode.
Saves the new default to `SelfEditStore`. Rebuilds the self-edit prompt and executor,
and updates the current loop's executor and system prompt in place.

### `switch_variant(name) -> bool`

Applies a named agent variant from `_variant_registry`. Builds an effective tool
registry (subset or read-only filter), creates a new `ToolExecutor`, optionally applies
variant permission rules, and updates the loop's executor and system prompt in place.
Returns `False` if the variant is not found.

---

## `_SessionSnapshot`

```python
@dataclass
class _SessionSnapshot:
    session_id: str
    loop: AgentLoop
    message_count: int
    loaded_offset: int
    last_replay_items: list[ReplayItem]
```

A frozen view of the main session state saved when entering self-edit mode. Stored in
`Session._pre_self_edit_state`. Restored verbatim by `toggle_self_edit_mode()` on exit.
The `last_replay_items` field holds the replay items at snapshot time (typically empty
because items are only populated on resume, not on plain `send`).

---

## Config

`Config` (`taui/config.py`) is a plain dataclass holding all runtime settings.

### Fields

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `provider` | `str` | `"copilot"` | LLM provider name |
| `model` | `str` | `""` | Model ID; resolved to provider default if empty |
| `system_prompt` | `str` | `DEFAULT_SYSTEM_PROMPT` | Fallback system prompt (tests; `Session.create` uses `SystemPromptBuilder`) |
| `max_turns` | `int` | `50` | Maximum agent loop iterations per `send()` |
| `session_id` | `str \| None` | `None` | When set, `TauiApp` resumes this session on startup |
| `working_dir` | `Path` | `Path.cwd()` | Project directory; root for relative tool paths and `.taui/` storage |
| `auto_approve_reads` | `bool` | `True` | Auto-approves `read`, `glob`, `grep` |
| `tool_policy` | `dict[str, str]` | `{}` | Per-tool `PolicyDecision` strings (e.g. `{"bash": "ask"}`) |
| `permission` | `dict[str, dict[str, str]]` | `{}` | Pattern-based permission ruleset |
| `verbose_tools` | `bool` | `True` | Show full tool output (toggled by `/verbose`) |
| `theme` | `dict` | `{}` | Style override map |
| `keybindings` | `dict` | `{}` | Custom keybinding map |
| `extension_dirs` | `list[str]` | `[]` | Additional extension search directories |

### Config Layering

`Config.load(**overrides)` applies settings in priority order (later sources win):

1. **Defaults** — dataclass field defaults above.
2. **TOML config file** — loaded by `taui.llm_provider.config.load_config()`, which
   reads `~/.taui/config.toml` and/or a project `.taui/config.toml`. Fields under the
   `[taui]` section are mapped directly to config fields.
3. **CLI / environment overrides** — passed as keyword arguments to `load()`. Only
   non-`None` values override. These come from `taui/main.py` argparse parsing.
4. **Model default** — if `model` is still empty after all layers, `get_default_model(provider)`
   selects the best available model for the provider.

---

## CostTracker

`CostTracker` (`taui/cost.py`) accumulates token usage and estimated USD cost for all
LLM turns within a session.

### `_PRICING` Table

A module-level `dict[str, tuple[float, float]]` mapping model ID to
`(input_$/1M, output_$/1M)`:

| Model | Input $/1M | Output $/1M |
|-------|-----------|-------------|
| `claude-sonnet-4.6` | 3.00 | 15.00 |
| `claude-sonnet-4-20250514` | 3.00 | 15.00 |
| `claude-opus-4-20250514` | 15.00 | 75.00 |
| `claude-3-5-sonnet-20241022` | 3.00 | 15.00 |
| `claude-3-5-haiku-20241022` | 0.80 | 4.00 |
| `gpt-4o` | 2.50 | 10.00 |
| `gpt-4o-mini` | 0.15 | 0.60 |
| `o1` | 15.00 | 60.00 |
| `o3-mini` | 1.10 | 4.40 |
| `_default` | 3.00 | 15.00 |

### `estimate_cost(model, input_tokens, output_tokens) -> float`

Looks up the model in `_PRICING`. Falls back to a prefix match (e.g. `"claude-sonnet"`
matches `"claude-sonnet-4.6"`). Uses `_default` if no match. Returns
`(input_tokens * input_rate + output_tokens * output_rate) / 1_000_000`.

### `TurnRecord`

```python
@dataclass(slots=True)
class TurnRecord:
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    timestamp: float   # time.monotonic()
```

One entry per LLM turn.

### `CostTracker`

```python
@dataclass(slots=True)
class CostTracker:
    turns: list[TurnRecord]
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
```

**`record(*, model, input_tokens, output_tokens, cost_usd=None) -> TurnRecord`**

Estimates cost if not provided. Appends a `TurnRecord` and updates the running totals.
Called by `Session.send()` for each `TurnResult` that carries usage data.

**`summary() -> str`**

Returns a human-readable string:
```
tokens: 12,345in / 678out | cost: $0.0023 | turns: 3
```

**`to_dict() -> dict`**

Returns `{"total_input_tokens", "total_output_tokens", "total_cost_usd", "turn_count"}`
with cost rounded to 6 decimal places.

**`turn_count`** — property returning `len(self.turns)`.

`Session.cost_tracker` is accessible to the TUI (for the InfoBar cost display and
`/cost` command) and to `turn_summary` hooks.
