# Session, Config & Cost

Session is the composition root — it wires together provider, tools, store, and agent loop into one usable unit.

---

## Session (`taui/session.py`)

### Composition Root Pattern

`Session` has two constructors:

```python
# Production: creates and wires everything
session = await Session.create(config)

# Testing: inject all dependencies directly
session = Session(
    config=config,
    provider=mock_llm,
    registry=registry,
    executor=executor,
    store=store,
    stream=stream,
    loop=loop,
)
```

This pattern means tests never need auth, never touch the network, and never create real databases.

### What `Session.create()` Does

```python
async def create(config: Config | None = None) -> Session:
    # 1. Load config (defaults + file + overrides)
    config = config or Config.load()

    # 2. Authenticate + create LLM provider
    provider = _create_provider(config)
    #   → get_credentials(config.provider) for auth
    #   → CopilotProvider or CodexProvider

    # 3. Build tool registry
    registry = ToolRegistry()
    register_builtins(registry)            # 9 tools
    for tool in registry:
        tool.working_dir = config.working_dir

    # 4. Create tool executor with default policy
    policy = ToolPolicy()
    executor = ToolExecutor(registry=registry, policy=policy)

    # 5. Build system prompt with template + context
    builder = SystemPromptBuilder()
    ctx = ProjectContext.discover_with_git(config.working_dir)
    builder.with_project_context(ctx)
    builder.with_tools(registry)           # Tool snippets + guidelines
    system_prompt = builder.render()

    # 6. Open event store
    store = Store(config.working_dir)
    await store.connect()
    stream = StreamClient(store)

    # 7. Create agent loop
    loop = AgentLoop(
        llm=provider,
        executor=executor,
        stream=stream,
        system_prompt=system_prompt,
        model=config.model,
        max_turns=config.max_turns,
    )

    return Session(config=..., provider=..., ...)
```

### Public API

```python
result = await session.send("Fix the bug in main.py")
# → RunResult(text, turns, state, turn_results)
# Also records cost from each turn's usage data

await session.close()
# → Commits and closes the SQLite store

session.cost_tracker          # CostTracker instance
session.provider_name         # "copilot" or "codex"
session.model_name            # "claude-sonnet-4.6"
session.working_dir           # Path
```

### Provider Creation

```python
def _create_provider(config: Config):
    creds = get_credentials(config.provider)  # Device flow / PKCE OAuth
    match config.provider:
        case "copilot": return CopilotProvider(credentials=creds)
        case "codex":   return CodexProvider(credentials=creds)
```

Providers are duck-typed — Session and AgentLoop accept `llm: Any`, calling `create_turn()` on it.

---

## Config (`taui/config.py`)

```python
@dataclass
class Config:
    provider: str = "copilot"
    model: str = "claude-sonnet-4.6"
    system_prompt: str = DEFAULT_SYSTEM_PROMPT    # Fallback only
    max_turns: int = 50
    working_dir: Path = Path.cwd()
    auto_approve_reads: bool = True
```

### Config Loading

```python
Config.load(**overrides)
```

Layered: defaults → `~/.config/taui/config.toml` → keyword overrides.

The config file is loaded via `taui.llm_provider.config.load_config()` which reads TOML from `~/.config/taui/config.toml`. Only the `[taui]` section is used for Config fields.

```toml
# ~/.config/taui/config.toml
[taui]
provider = "copilot"
model = "claude-sonnet-4.6"
max_turns = 50
```

**Note**: `system_prompt` in Config is a fallback. In production, `Session.create()` uses `SystemPromptBuilder` which constructs a richer prompt with template variables.

---

## Cost Tracking (`taui/cost.py`)

### Pricing Table

```python
_PRICING = {
    "claude-sonnet-4.6":           (3.00, 15.00),    # $/1M tokens (in, out)
    "claude-opus-4-20250514":      (15.00, 75.00),
    "gpt-4o":                      (2.50, 10.00),
    "gpt-4o-mini":                 (0.15, 0.60),
    ...
    "_default":                    (3.00, 15.00),     # Fallback
}
```

### CostTracker

```python
tracker = CostTracker()
tracker.record(model="claude-sonnet-4.6", input_tokens=1500, output_tokens=200)

tracker.total_input_tokens     # 1500
tracker.total_output_tokens    # 200
tracker.total_cost_usd         # 0.007500
tracker.turn_count             # 1
tracker.summary()              # "tokens: 1,500in / 200out | cost: $0.0075 | turns: 1"
tracker.to_dict()              # {"total_input_tokens": 1500, ...}
```

### Integration with Session

After each `session.send()`, token usage from every turn is recorded:

```python
for tr in result.turn_results:
    if tr.usage:
        self.cost_tracker.record(
            model=self.config.model,
            input_tokens=tr.usage.get("input_tokens", 0),
            output_tokens=tr.usage.get("output_tokens", 0),
        )
```

---

## Extension Points for Self-Edit

Extensions can hook into Session at these points:

1. **Registry access**: `session._registry` — register/unregister tools
2. **Policy access**: `session._executor._policy` — set tool policies
3. **Prompt modification**: Build a new `SystemPromptBuilder` and update `session._loop._system_prompt`
4. **Config overrides**: `Config.load(model="gpt-4o")` to change models

Extensions should NOT touch:
- `session._provider` (authentication is internal)
- `session._store` / `session._stream` (event log is infrastructure)
- `session._loop._messages` (conversation state is managed by the loop)

---

## Files

| File | Purpose |
|------|---------|
| `taui/session.py` | Session: composition root, create(), send(), close() |
| `taui/config.py` | Config: layered configuration dataclass |
| `taui/cost.py` | estimate_cost(), TurnRecord, CostTracker |
