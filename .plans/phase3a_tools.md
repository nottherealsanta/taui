# Phase 3a — Tool System Implementation Plan

**Goal:** Implement the complete tool system (base types, registry, executor, policy, and 6 built-in tools) so that the agent loop (Phase 3c) can be wired up with full tool-calling capabilities.

**Preconditions:** Phase 2 (auth + REPL) is complete. The live `taui/` package has auth and a simple streaming REPL. No tool system, no agent loop, no structured messages exist in the live code yet.

**Reference:** `.refs/tools/`, `.refs/config/`, `.refs/llm/types.py` contain complete, tested reference implementations.

## Completion Status (2026-03-06)

Phase 3a is implemented in the live tree.

- Implemented: `taui/config/`, `taui/llm/`, `taui/agent/session.py`, `taui/tools/` and all 6 built-in tools.
- Implemented: registry `unregister()` + `names_by_origin()` and tool `origin` support.
- Implemented: executor outcomes (`completed`, `approval_required`, `denied`) with schema validation and timeout handling.
- Implemented: auth config migration to `taui/config/auth_config.py` with compatibility imports via `taui.config`.
- Implemented tests: `tests/test_tools_guards.py`, `tests/test_executor_outcomes.py`, `tests/test_builtins_search_and_bash.py`, `tests/test_registry_origin.py`.
- Verification: `uv run pytest -q` passes (`16 passed`).

---

## Dependency Order

The tool system depends on two upstream modules that don't exist in the live code yet:

```
config/settings.py + config/policies.py  ← tools/executor.py needs Policy
llm/types.py                             ← agent/events.py needs ToolCall, but tools/ itself doesn't
agent/session.py                         ← tools/builtins need session.mark_read(), session.has_read()
```

So the build order within this phase is:

```
Step 1: config/settings.py, config/policies.py
Step 2: tools/base.py
Step 3: tools/registry.py
Step 4: tools/builtins/_common.py
Step 5: tools/builtins/ (read, edit, write, bash, glob, grep) — needs Session stub
Step 6: tools/executor.py
Step 7: tools/__init__.py + tools/builtins/__init__.py
Step 8: Tests
```

Note: The built-in tools need `session.mark_read()` and `session.has_read()`. We have two options:
- **(A)** Build Session first (pull forward from Phase 3c) — it's self-contained aside from SQLite storage
- **(B)** Use a minimal `Session` protocol/interface that the tools depend on, implement the real Session later

**Decision: Option A.** The Session class from `.refs/agent/session.py` is well-defined and self-contained. The tools need `mark_read()`, `has_read()`, and `read_status()`. We build a **minimal Session** now (just the parts tools need: message list, read tracking, usage recording). The full persistence (SQLite, locking) comes in a later step.

---

## Step 1: `taui/config/` — Settings & Policy

### 1.1 `taui/config/__init__.py`

Re-exports: `Settings`, `load_settings`, `Policy`, `ToolDecision`.

### 1.2 `taui/config/settings.py`

Port from `.refs/config/settings.py`. Contains:

| Type | Purpose |
|---|---|
| `ProviderSettings` | `api_key_env`, `api_key` |
| `ModelSettings` | `default: str = "copilot:gpt-5"` |
| `PolicySettings` | `auto_approve`, `confirm`, `deny` tuples |
| `BashPolicySettings` | `restrict_workdir_to_workspace`, `allow_network`, `env_allowlist`, `max_output_bytes`, `default_timeout_sec` |
| `McpServerSettings` | `command`, `args`, `env`, `enabled` — one entry per MCP server |
| `Settings` | Aggregates all above |
| `load_settings()` | Reads TOML from `~/.config/taui/config.toml`, applies env vars and overrides |

**Change from reference:** Add `McpServerSettings` and a `mcp_servers: dict[str, McpServerSettings]` field to `Settings`. The `load_settings()` parser reads `[mcp_servers.<name>]` tables from config.

```python
@dataclass(slots=True)
class McpServerSettings:
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True

@dataclass(slots=True)
class Settings:
    model: ModelSettings = field(default_factory=ModelSettings)
    providers: dict[str, ProviderSettings] = field(default_factory=dict)
    policy: PolicySettings = field(default_factory=PolicySettings)
    policy_bash: BashPolicySettings = field(default_factory=BashPolicySettings)
    mcp_servers: dict[str, McpServerSettings] = field(default_factory=dict)  # NEW
```

Example user config:
```toml
[mcp_servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]

[mcp_servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
env = { GITHUB_TOKEN = "env:GITHUB_TOKEN" }
enabled = true
```

The `env` dict supports `"env:VAR_NAME"` values, which are resolved from the environment at connection time (not at config load time). This is handled by the MCP client (Phase 4+), not by `load_settings()`.

**Key detail:** The existing `taui/config.py` handles TOML read/write for provider tokens. The new `taui/config/settings.py` replaces it. The old `config.py` auth-related functions (`load_provider_config`, `save_provider_config`) should be preserved — either in `settings.py` or as a compat shim — since `auth/*.py` modules import from `taui.config`.

**Migration approach:** See [Appendix A: `config.py` → `config/` Migration](#appendix-a-configpy--config-migration) for full details.

### 1.3 `taui/config/policies.py`

Port from `.refs/config/policies.py`. Contains:

| Type | Purpose |
|---|---|
| `PolicyDecision` | `Literal["allow", "confirm", "deny"]` |
| `ToolDecision` | `decision: PolicyDecision`, `reason: str` |
| `Policy` | `auto_approve`, `confirm`, `deny` sets + `bash: BashPolicySettings`; `evaluate(tool_name) → ToolDecision`; `from_settings()` classmethod |

**Evaluation logic:** deny > confirm > auto_approve > default (confirm).

---

## Step 2: `taui/tools/base.py` — Core Contracts

Port from `.refs/tools/base.py`. Three types:

| Type | Fields | Purpose |
|---|---|---|
| `ToolResult` | `content: str`, `error: bool`, `metadata: dict | None` | Return value from every tool. `.ok()` / `.fail()` classmethods. |
| `ToolContext` | `working_dir: Path`, `session: Any`, `policy: Policy` | Passed to every tool's `execute()`. The session is typed as `Any` to avoid circular imports. |
| `Tool` | `name`, `description`, `schema`, `origin`, `execute()` | The protocol that all tools implement. |

**Change from reference:** Add `origin: str` to the `Tool` protocol. This is the single field that enables MCP integration (and any future tool source) without breaking changes later.

```python
class Tool(Protocol):
    name: str
    description: str
    schema: dict[str, Any]
    origin: str  # "builtin" | "mcp:<server_name>" | future: "user:<path>"

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult: ...
```

All 6 built-in tools set `self.origin = "builtin"` in `__post_init__`. MCP tools (Phase 4+) will set `origin = "mcp:<server_name>"`.

---

## Step 3: `taui/tools/registry.py` — Tool Registry

Port from `.refs/tools/registry.py`. Extended with two new methods:

- `register(tool)` — adds tool, raises on duplicate name
- `unregister(name)` — removes tool by name; raises if not found. Needed when an MCP server disconnects and its tools must be removed.
- `get(name)` — returns tool, raises on unknown
- `list_schemas()` — returns OpenAI function-calling format: `[{"type": "function", "function": {"name", "description", "parameters"}}]`
- `names()` — sorted tuple of registered tool names
- `names_by_origin(prefix)` — sorted tuple of tool names whose `origin` starts with `prefix`. Enables bulk cleanup: `names_by_origin("mcp:filesystem")` returns all tools from a disconnected MCP server.

**Changes from reference:** Add `unregister()` and `names_by_origin()`.

```python
def unregister(self, name: str) -> None:
    if name not in self._tools:
        raise ValueError(f"Tool '{name}' is not registered.")
    del self._tools[name]

def names_by_origin(self, prefix: str) -> tuple[str, ...]:
    return tuple(
        sorted(name for name, tool in self._tools.items()
               if tool.origin.startswith(prefix))
    )
```

---

## Step 4: `taui/tools/builtins/_common.py` — Shared Utilities

Port from `.refs/tools/builtins/_common.py`. Three helpers:

| Function | Purpose |
|---|---|
| `resolve_path(context, raw_path) → Path` | Resolves relative paths against workspace; **rejects paths outside workspace** (sandbox). |
| `format_numbered_lines(lines, start_line) → str` | Formats output like `00001\| line content`. |
| `normalize_tool_error(message, metadata?) → ToolResult` | Shorthand for `ToolResult.fail()`. |

**No changes from reference.** Direct port.

---

## Step 5: Built-in Tools (6 tools)

Each tool is a `@dataclass(slots=True)` implementing the `Tool` protocol. Schema is defined in `__post_init__`. All tools are in `taui/tools/builtins/`.

**Change from reference:** Each tool sets `self.origin = "builtin"` in `__post_init__` alongside the schema. No other changes.

### 5.1 `ReadTool` (`read.py`)

- **Schema:** `filePath` (required string), `offset` (optional int), `limit` (optional int, default 2000)
- **Behavior:** Reads file, returns numbered lines. Calls `session.mark_read(path, "success")` on success, `"missing"` on not-found.
- **Sandbox:** Path resolved via `resolve_path()` (workspace-confined).
- **Session interaction:** `mark_read()` — the read-before-write guard starts here.

### 5.2 `EditTool` (`edit.py`)

- **Schema:** `filePath`, `old_string`, `new_string` (all required strings), `replace_all` (optional bool)
- **Guard:** `session.read_status(path)` must be `"success"` — edit requires prior read.
- **Behavior:** Exact string replacement. If `old_string` not found → error. If multiple matches and `replace_all` is false → error. Atomic write via `tempfile` + `Path.replace()`.

### 5.3 `WriteTool` (`write.py`)

- **Schema:** `filePath`, `content` (required strings), `create_if_missing` (optional bool)
- **Guard:** `session.has_read(path)` must be true. For new files: `read_status` must be `"missing"` and `create_if_missing` must be true.
- **Behavior:** Overwrites file content. Creates parent dirs if needed. Atomic write.

### 5.4 `BashTool` (`bash.py`)

- **Schema:** `command` (required string), `timeout` (optional int), `workdir` (optional string)
- **Sandbox:** Workdir confinement (if `restrict_workdir_to_workspace` is true in policy). Env filtering via `env_allowlist`.
- **Execution:** `asyncio.create_subprocess_shell` with `start_new_session=True` (enables process group kill). Timeout via `asyncio.wait_for`. On timeout: SIGTERM → 1s grace → SIGKILL.
- **Output:** stdout/stderr formatted, truncated to `max_output_bytes`.

### 5.5 `GlobTool` (`glob.py`)

- **Schema:** `pattern` (required string), `path` (optional string)
- **Behavior:** `Path.glob(pattern)` from base dir, sorted by mtime (newest first). Returns newline-separated paths.

### 5.6 `GrepTool` (`grep.py`)

- **Schema:** `pattern` (required string), `path` (optional string), `include` (optional string — filename filter like `"*.py"`)
- **Behavior:** Recursive `rglob("*")` with regex matching. Returns `file:line| content` format.

**Note on performance:** The reference `GrepTool` uses pure Python `rglob` + `re.search`. This is functional but slow on large repos. A future optimization could shell out to `ripgrep`. For Phase 3a, the pure Python version is correct and sufficient.

### 5.7 `taui/tools/builtins/__init__.py`

`register_builtin_tools(registry)` — registers all 6 tools.

---

## Step 6: `taui/tools/executor.py` — Tool Executor

Port from `.refs/tools/executor.py`. The single enforcement point for all tool execution.

### Outcome Types

| Type | Meaning |
|---|---|
| `ExecutionCompleted` | Tool ran (success or tool-level error). Contains `ToolResult`. |
| `ExecutionRequiresApproval` | Policy says "confirm" and no approval provided yet. Contains preview. |
| `ExecutionDenied` | Policy says "deny" or user rejected. Contains error `ToolResult`. |

`ExecutionOutcome = ExecutionCompleted | ExecutionRequiresApproval | ExecutionDenied`

### `ToolExecutor.run()` Flow

```
1. Resolve tool from registry (unknown tool → ExecutionCompleted with error)
2. Validate arguments against JSON Schema (type checking, required fields)
3. Evaluate policy:
   - deny → ExecutionDenied
   - confirm + no approval → ExecutionRequiresApproval
   - confirm + approved=False → ExecutionDenied
   - confirm + approved=True → proceed
   - allow → proceed
4. Execute with asyncio.wait_for(timeout)
   - TimeoutError → ExecutionCompleted with error
   - Exception → ExecutionCompleted with error
5. Attach metadata (duration_ms, tool_name, arguments_digest)
6. Return ExecutionCompleted
```

### Argument Validation

The reference uses a lightweight custom validator (`_validate_schema`):
- Checks `required` fields are present
- Checks `type` matches for each property (`string`, `integer`, `number`, `boolean`, `array`, `object`)
- Does NOT validate `enum`, `pattern`, `minLength`, `anyOf`, etc.

This is sufficient for built-in tools. If we later need full JSON Schema validation, we can swap in `jsonschema` library.

---

## Step 7: Package Init Files

### `taui/tools/__init__.py`

Re-exports: `Tool`, `ToolContext`, `ToolResult`, `ToolRegistry`, `ToolExecutor`, `ExecutionCompleted`, `ExecutionRequiresApproval`, `ExecutionDenied`, `ExecutionOutcome`, `register_builtin_tools`.

---

## Step 8: Minimal Session (for tool guards)

We need a lightweight `Session` class that provides:
- `mark_read(path: Path, status: str) → None`
- `has_read(path: Path) → bool`
- `read_status(path: Path) → str | None`
- `messages: list` (can be empty list for now)
- `add_message(message) → None`
- `record_usage(usage) → None`

**Approach:** Port the full `Session` from `.refs/agent/session.py` but **without the SQLite persistence** (no `save()`, `load()`, `load_or_create()`, `save_default()`, no `_session_lock`). Those get added when we build the storage layer. The `Session` class itself is pure data + read-tracking + token estimation + compaction — all of which are needed immediately.

This also requires:
- `taui/llm/types.py` — the `Message`, `ToolCall`, `Usage`, `StreamEvent` types (needed by Session)
- `taui/agent/session.py` — the Session class

**Build order:**
1. `taui/llm/types.py` (no dependencies)
2. `taui/agent/session.py` (depends on `llm/types.py`, skip persistence for now)

---

## Step 9: Tests

Port and adapt from `.refs/tests/`:

### 9.1 `tests/test_tools_guards.py`
- `test_edit_requires_prior_read` — edit without read → error
- `test_edit_succeeds_after_read` — read then edit → success, file updated
- `test_write_create_requires_missing_read` — write new file without read → error; read missing → write succeeds

### 9.2 `tests/test_executor_outcomes.py`
- `test_confirm_required_outcome` — uncategorized tool → `ExecutionRequiresApproval`
- `test_approved_execution_completes` — auto_approve tool → `ExecutionCompleted`
- `test_denied_after_prompt` — confirm tool + approved=False → `ExecutionDenied`

### 9.4 `tests/test_registry_origin.py`
- `test_builtin_origin` — all 6 built-in tools have `origin == "builtin"`
- `test_unregister_removes_tool` — register, unregister, `get()` raises
- `test_unregister_unknown_raises` — unregister unknown name raises `ValueError`
- `test_names_by_origin_builtin` — `names_by_origin("builtin")` returns all 6 built-in names
- `test_names_by_origin_mcp_prefix` — register a fake `mcp:test` tool, `names_by_origin("mcp:")` returns it, `names_by_origin("builtin")` does not

### 9.3 `tests/test_builtins_search_and_bash.py`
- `test_glob_matches_files` — glob finds .py files
- `test_grep_invalid_regex_errors` — bad regex → error
- `test_grep_matches_lines` — grep finds correct lines
- `test_bash_timeout` — slow command → timeout error
- `test_bash_output_truncation` — large output gets truncated

### Testing infrastructure
- Add `pytest` to `[dependency-groups] dev` in `pyproject.toml`
- Tests use `tempfile.TemporaryDirectory` for workspace isolation
- Tests use `asyncio.run()` for async tool execution
- No mocking needed — all tools operate on real temp files

---

## Step 10: Integration Point — Preparing for Phase 3b/3c

After Phase 3a, the following are ready:

**Available for Phase 3b (LLM provider refactor):**
- `ToolRegistry.list_schemas()` returns the `tools` array the provider needs
- `llm/types.py` provides `Message`, `ToolCall`, `StreamEvent`

**Available for Phase 3c (Agent loop):**
- `ToolExecutor.run()` is the single point the agent loop calls for tool execution
- `Session` tracks messages, read state, and usage
- `Policy` + `ToolContext` are the execution environment
- `AgentEvent` types (Phase 3c) will reference `ToolCall` and `ToolResult`

**The wiring looks like:**
```python
# Phase 3c: agent/loop.py
registry = ToolRegistry()
register_builtin_tools(registry)
executor = ToolExecutor(registry)
policy = Policy.from_settings(settings)
context = ToolContext(working_dir=workspace, session=session, policy=policy)

# In the agent loop:
outcome = await executor.run(
    tool_call_id=call.id,
    tool_name=call.name,
    arguments=call.arguments,
    context=context,
)
```

---

## Files to Create (in order)

| # | File | Lines (approx) | Source |
|---|---|---|---|
| 1 | `taui/config/__init__.py` | 10 | New |
| 2 | `taui/config/settings.py` | ~220 | Port + `McpServerSettings` additions |
| 3 | `taui/config/policies.py` | 50 | Port from `.refs/config/policies.py` |
| 4 | `taui/config/auth_config.py` | ~60 | Extract from existing `taui/config.py` |
| 5 | `taui/llm/__init__.py` | 10 | New |
| 6 | `taui/llm/types.py` | 98 | Port from `.refs/llm/types.py` |
| 7 | `taui/agent/__init__.py` | 5 | New |
| 8 | `taui/agent/session.py` | ~200 | Port from `.refs/agent/session.py` (minus persistence) |
| 9 | `taui/tools/__init__.py` | 26 | Port from `.refs/tools/__init__.py` |
| 10 | `taui/tools/base.py` | ~45 | Port + `origin: str` on `Tool` protocol |
| 11 | `taui/tools/registry.py` | ~55 | Port + `unregister()`, `names_by_origin()` |
| 12 | `taui/tools/executor.py` | 194 | Port from `.refs/tools/executor.py` |
| 13 | `taui/tools/builtins/__init__.py` | 22 | Port from `.refs/tools/builtins/__init__.py` |
| 14 | `taui/tools/builtins/_common.py` | 38 | Port from `.refs/tools/builtins/_common.py` |
| 15 | `taui/tools/builtins/read.py` | ~100 | Port + `self.origin = "builtin"` |
| 16 | `taui/tools/builtins/edit.py` | ~101 | Port + `self.origin = "builtin"` |
| 17 | `taui/tools/builtins/write.py` | ~88 | Port + `self.origin = "builtin"` |
| 18 | `taui/tools/builtins/bash.py` | ~156 | Port + `self.origin = "builtin"` |
| 19 | `taui/tools/builtins/glob.py` | ~60 | Port + `self.origin = "builtin"` |
| 20 | `taui/tools/builtins/grep.py` | ~95 | Port + `self.origin = "builtin"` |
| 21 | `tests/test_tools_guards.py` | 103 | Port from `.refs/tests/` |
| 22 | `tests/test_executor_outcomes.py` | 123 | Port from `.refs/tests/` |
| 23 | `tests/test_builtins_search_and_bash.py` | 86 | Port from `.refs/tests/` |
| 24 | `tests/test_registry_origin.py` | ~50 | New — covers `origin`, `unregister`, `names_by_origin` |
| 25 | `pyproject.toml` | Update | Add pytest to dev deps |

**Files to modify:**
- `taui/auth/__init__.py` — update imports from `taui.config` → `taui.config.auth_config`
- `taui/auth/copilot.py` — same import update
- `taui/auth/gemini.py` — same
- `taui/auth/antigravity.py` — same
- `taui/auth/codex.py` — same
- Delete `taui/config.py` (replaced by `taui/config/` package)

**Total new code:** ~1,670 lines across 25 files.

---

## Design Decisions & Rationale

### Why not use the Vercel AI SDK approach (like opencode)?
Taui is Python, not TypeScript. There's no Python equivalent of the Vercel AI SDK that handles tool serialization per provider. We handle this ourselves in the provider layer (Phase 3b) — each provider's `_to_api_message()` serializes tools to its wire format. The `ToolRegistry.list_schemas()` outputs OpenAI function-calling format, which is the most common denominator.

### Why not Cline's multi-variant-per-model approach?
Cline maintains separate tool specs (descriptions, required params) per model family. This is high-maintenance and premature for Taui. We use a single tool spec and adjust at the provider level only where necessary (e.g., different serialization for Gemini vs OpenAI). If we find model-specific tool description tuning is needed, we can add it later without restructuring.

### Why a custom schema validator instead of `jsonschema`?
The reference implementation uses a ~50-line custom validator that checks required fields and type matching. This covers 100% of our built-in tools' schemas. Adding `jsonschema` as a dependency for no practical benefit is unnecessary. We can add it later if MCP tools or plugin tools need full JSON Schema validation.

### Why add `origin` to the `Tool` protocol now?
MCP servers expose tools that are dynamically registered at runtime. When an MCP server disconnects, its tools must be removed from the registry. `origin` on the protocol is the minimal hook that enables:
1. **Bulk unregistration** — `names_by_origin("mcp:filesystem")` then unregister each
2. **Default policy** — the executor (or future policy logic) can apply stricter defaults to `"mcp:*"` tools
3. **UI provenance** — display tells the user which tools come from which MCP server
4. **No breaking changes** — adding `origin` now costs 1 field per tool; retrofitting it later would require changing every tool implementation

### Why `mcp__<server>__<tool>` naming?
MCP tools arrive with short names (e.g., `read_file`, `search`). These collide with built-in names. Double underscore is unambiguous as a namespace separator (single underscore is common in tool names, double is not). The pattern is consistent with how other tools systems (e.g., LangChain) namespace external tools.

### Why `confirm` by default for MCP tools?
MCP tools run arbitrary code on external servers. The user has no intrinsic knowledge of what an MCP server will do with a given call. Defaulting to `confirm` keeps the human in the loop, consistent with the MCP spec's own security guidance ("there SHOULD always be a human in the loop"). Users can promote specific trusted tools to `auto_approve` explicitly in `config.toml`.

### Why only stdio transport in Phase 4?
Stdio (spawn a subprocess, communicate via stdin/stdout) covers the vast majority of community MCP servers. HTTP/SSE adds implementation complexity and is needed only for remote servers — a use case we don't have yet. We add HTTP support when a concrete need arises.

### Why port Session now instead of later?
The tools have a hard dependency on `session.mark_read()` / `session.has_read()` for the read-before-write guard. This guard is a core invariant (spec §13.1). Stubbing it out would mean the tools work differently in Phase 3a than in Phase 3c, which defeats the purpose of testing them now.

### Why atomic writes?
Both `EditTool` and `WriteTool` use `tempfile.NamedTemporaryFile` + `Path.replace()`. This ensures that a crash mid-write doesn't corrupt the file. `Path.replace()` is atomic on POSIX systems (it's a single rename syscall).

### Tool groups (from main_plan.md §3.1)
The main plan defines 7 tool groups: `read`, `write`, `programmatic`, `lsp`, `git`, `plan`, `spawn`. Phase 3a implements tools from the first three groups. The `group` attribute is **not** on the `Tool` protocol in the reference implementation — it's an organizational concept, not a runtime property. We defer adding `group` to the protocol until Phase 4 when minion tool access control needs it. MCP tools will carry their group designation via `origin` for now.

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Auth imports break when `config.py` → `config/` | Test auth flow manually after migration. Keep the same function signatures. |
| GrepTool slow on large repos | Acceptable for Phase 3a. Future: shell out to `rg` (ripgrep). |
| Session without persistence loses state on crash | Acceptable for Phase 3a. SQLite persistence is Phase 3c+. |
| Bash sandbox insufficient (no network control) | `env_allowlist` and workdir restriction are the current controls. Full sandboxing (seccomp, nsjail) is out of scope. |
| MCP tool name collision with built-ins | Prevented by `mcp__<server>__<tool>` naming convention enforced by the MCP client (Phase 4+). Registry's duplicate-name check is the last-resort guard. |

---

## Verification Criteria

Phase 3a is complete when:

1. All 6 built-in tools execute correctly in isolation (via test suite)
2. Read-before-write guard is enforced for `edit` and `write`
3. Policy evaluation works: auto_approve / confirm / deny paths
4. Executor handles timeout, unknown tool, validation error, and exception cases
5. Workspace sandbox prevents path traversal
6. Bash output truncation and timeout work
7. `ToolRegistry.list_schemas()` produces valid OpenAI function-calling format
8. All 6 built-in tools have `origin == "builtin"`
9. `registry.unregister()` and `registry.names_by_origin()` work correctly
10. `Settings.mcp_servers` parses `[mcp_servers.<name>]` tables from config.toml
11. All existing auth tests still pass (no import breakage)
12. `pytest` runs clean with no failures
