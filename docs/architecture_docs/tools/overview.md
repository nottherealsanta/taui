# Tool System Overview

Tools are how the agent interacts with the outside world. Every file read, edit, shell
command, git operation, and web fetch goes through a tool.

---

## Architecture Flow

```
LLM response (tool_calls)
  → AgentLoop._execute_tool()
    → ToolExecutor.run(call_id, name, arguments, approved=None)
      │
      ├─ resolve tool from ToolRegistry
      │    └─ unknown tool → Completed(ToolResult.fail(...))
      │
      ├─ ToolPolicy.decide(name, arguments)
      │    ├─ DENY  → Denied(ToolResult.fail(...))
      │    └─ CONFIRM + not auto-approved + approved is None
      │         → NeedsApproval(tool_call_id, tool_name, arguments)
      │
      ├─ _execute_with_retry(tool_name, tool, arguments)
      │    ├─ asyncio.wait_for(tool.execute(arguments), timeout=120s)
      │    ├─ retry on error for FILE_READ/SEARCH categories (0.25s, 1.0s, 4.0s)
      │    └─ exceptions → ToolResult.fail(...)
      │
      ├─ TruncationStore.maybe_truncate(result.content, tool_name)
      │    └─ outputs > 8 KiB are stored behind a peek handle
      │
      └─ Completed(result)
           └─ result.metadata["duration_ms"] set automatically

  → AgentLoop appends Message(role="tool", content, tool_call_id)
  → next LLM turn
```

---

## Core Types (`taui/tools/base.py`)

### ToolCategory

```python
class ToolCategory(StrEnum):
    FILE_READ  = "file_read"   # read, webfetch, peek, lsp, repo_overview
    FILE_WRITE = "file_write"  # write, edit, apply_patch, notebook_edit
    SEARCH     = "search"      # glob, grep, lsp, repo_overview
    SHELL      = "shell"       # bash
    GIT        = "git"         # git
    AGENT      = "agent"       # sub_agent, task, skills, session_name, mcp
    MEMORY     = "memory"      # memory
    QUESTION   = "question"    # question
```

Categories serve two purposes:

1. **Policy grouping** — set policies by category (e.g., auto-approve all `FILE_READ`)
2. **Schema filtering** — `registry.schemas(include={FILE_READ})` for scoped sub-agents
3. **Retry eligibility** — `FILE_READ` and `SEARCH` tools retry on transient errors

### ToolResult

```python
@dataclass(slots=True)
class ToolResult:
    content: str               # Text returned to the LLM
    error: bool = False        # True → content is an error message
    metadata: dict[str, Any]   # Machine-readable extras (duration_ms, path, ...)

    @classmethod
    def ok(cls, content: str, **metadata) -> ToolResult: ...

    @classmethod
    def fail(cls, content: str, **metadata) -> ToolResult: ...
```

- The LLM only sees `content`. `metadata` is used by the TUI for rendering and
  diagnostics.
- `error=True` affects how the TUI displays the result and signals to the agent that
  the call did not succeed.
- `duration_ms` is set automatically by the executor after every call.
- Tools should return `ToolResult.fail(...)` for expected failures, not raise.

### Tool Protocol

```python
class Tool(Protocol):
    name: str               # Unique identifier, e.g. "read", "bash"
    description: str        # Shown to the LLM in the tool schema
    schema: dict[str, Any]  # JSON Schema for parameters (OpenAI format)
    category: ToolCategory

    async def execute(self, arguments: dict[str, Any]) -> ToolResult: ...
```

Tools are duck-typed. Any class with these attributes and an async `execute` method
satisfies the protocol. No base class inheritance is required.

**Optional attributes:**

| Attribute | Type | Purpose |
|-----------|------|---------|
| `guidelines` | `str` | Per-tool usage hints injected into the system prompt |
| `output_schema` | `dict` | JSON Schema describing the tool's result shape |

---

## Registry (`taui/tools/registry.py`)

```python
class ToolRegistry:
    # Registration
    register(tool)                    # Add tool; raises ValueError on duplicate name
    register_or_replace(tool)         # Add or silently overwrite
    unregister(name) -> Tool          # Remove and return; raises on miss

    # Lookup
    get(name) -> Tool                 # Raises ValueError if not found
    __contains__(name) -> bool
    __len__() -> int
    names -> list[str]                # Sorted list of registered tool names

    # Filtering
    by_category(category) -> list[Tool]  # All tools in a category

    # Schema export (OpenAI function-calling format)
    schemas(
        *,
        include: set[ToolCategory] | None,  # Only these categories
        exclude: set[ToolCategory] | None,  # Skip these categories
    ) -> list[dict]

    # Sub-agent scoping
    subset(names: list[str]) -> ToolRegistry  # New registry with only named tools

    # System prompt integration
    guidelines() -> str               # Formatted markdown from all tool.guidelines

    # Output schema access
    output_schema(name) -> dict | None
```

**Schema export** produces OpenAI function-calling format:

```json
[{
    "type": "function",
    "function": {
        "name": "read",
        "description": "Read the contents of a file...",
        "parameters": { "type": "object", "properties": {...}, "required": [...] }
    }
}]
```

**`subset()`** creates scoped registries for sub-agents (e.g., a read-only sub-agent
can be given `registry.subset(["read", "glob", "grep"])`).

**`guidelines()`** collects `tool.guidelines` strings from all tools that expose them,
formatted as a markdown list under a `## Tool Guidelines` header.

---

## Executor (`taui/tools/executor.py`)

The executor sits between the agent loop and tools, enforcing policy and handling
timeouts, retries, and output truncation.

### PolicyDecision

```python
class PolicyDecision(StrEnum):
    AUTO    = "auto"     # Execute without asking the user
    CONFIRM = "confirm"  # Ask the user before executing
    DENY    = "deny"     # Block entirely
```

### ToolPolicy

```python
class ToolPolicy:
    # Built-in defaults (destructive tools):
    # bash → CONFIRM, write → CONFIRM, edit → CONFIRM
    # Everything else → AUTO

    decide(tool_name: str, arguments: dict | None) -> PolicyDecision
    #   Consults in order: ruleset → per-tool overrides → built-in defaults

    set(tool_name: str, decision: PolicyDecision)
    #   Override the policy for a specific tool

    set_overrides(overrides: dict[str, PolicyDecision])
    #   Replace all per-tool overrides at once

    set_ruleset(ruleset: PermissionRuleset | None)
    #   Attach a pattern-based permission ruleset (highest priority)

    add_pattern(tool_name: str, pattern: str)
    #   Add a glob pattern for persistent auto-approval of similar calls

    should_auto_approve(tool_name: str, arguments: dict) -> bool
    #   True if the call matches a stored auto-approve pattern or ruleset AUTO rule
    #   Subject for matching: bash → command string, write/edit → file_path
```

### Execution Outcomes

```python
@dataclass(slots=True)
class Completed:
    result: ToolResult    # Tool ran — may be ok or fail, but loop continues

@dataclass(slots=True)
class NeedsApproval:
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]  # Shown in the TUI approval prompt

@dataclass(slots=True)
class Denied:
    result: ToolResult    # Blocked by policy or rejected by the user

Outcome = Completed | NeedsApproval | Denied
```

The agent loop handles `NeedsApproval` by surfacing an approval prompt, then
re-calling `executor.run(..., approved=True/False)`.

### Retry Behaviour

| Category | Eligible | Delays |
|----------|----------|--------|
| `FILE_READ` | yes | 0.25s, 1.0s, 4.0s (max 3 retries) |
| `SEARCH` | yes | 0.25s, 1.0s, 4.0s |
| All others | no | — |

Only `error=True` results trigger a retry. Exceptions and timeouts are caught and
converted to `ToolResult.fail(...)` before the retry check.

### Error Handling

| Condition | Outcome |
|-----------|---------|
| Unknown tool name | `Completed(ToolResult.fail("Unknown tool: ..."))` |
| Tool raises exception | `Completed(ToolResult.fail("Tool <name> failed: ..."))` |
| Tool exceeds timeout | `Completed(ToolResult.fail("Tool <name> timed out after 120s"))` |
| Policy DENY | `Denied(ToolResult.fail("Tool <name> is denied by policy."))` |
| User rejected | `Denied(ToolResult.fail("Tool execution rejected by user."))` |

Errors always surface as `Completed` or `Denied` — never as exceptions that would break
the agent loop.

### ToolExecutor Constructor

```python
ToolExecutor(
    registry: ToolRegistry,
    policy: ToolPolicy | None = None,   # defaults to ToolPolicy()
    *,
    timeout: float = 120.0,             # per-call timeout in seconds
    truncation_store: TruncationStore | None = None,
)
```

---

## TruncationStore (`taui/tools/truncation.py`)

Large tool outputs are stored behind handles to avoid flooding the LLM context window.

```python
class TruncationStore:
    DEFAULT_MAX_INLINE_BYTES = 8192   # 8 KiB — outputs larger than this are truncated
    DEFAULT_PEEK_WINDOW      = 4096   # 4 KiB — bytes returned per peek call

    maybe_truncate(content: str, tool_name: str = "") -> str
    #   If content <= 8 KiB: returned as-is.
    #   If content >  8 KiB: stores full content, returns truncated preview with handle:
    #     "<first 8 KiB>\n\n[truncated; N KiB more — use peek tool with handle="tr_xxxx" offset=0]"

    peek(handle: str, offset: int = 0, limit: int | None = None) -> str | None
    #   Retrieve a byte-addressed window of a stored output.
    #   Returns None if handle is not found (expired with the session).
    #   Appends a continuation hint when more bytes remain.

    clear()              # Drop all stored outputs
    handles -> list[str] # All active handle strings (e.g. ["tr_abc12345"])
```

Handles are short UUIDs with prefix `tr_`, e.g. `tr_abc12345`. They are session-scoped
and do not persist across restarts. The `peek` built-in tool provides agent-facing
access to the store.

The executor skips truncation for the `peek` tool itself (circular guard) and for
`error=True` results.

---

## Extension Points

Extensions register tools via the extension context or directly on the registry:

```python
def register(ctx):
    ctx.tools.register(my_tool)           # New tool
    ctx.tools.register_or_replace(tool)   # Override a builtin
```

Direct registry access (e.g., in tests or self-edit):

```python
registry.register(my_tool)
registry.register_or_replace(my_tool)
registry.unregister("old_tool")
```

The registry is accessible via `session._registry`. Extensions loaded at startup can
modify it before the first LLM turn.

---

## Source Files

| File | Purpose |
|------|---------|
| `taui/tools/base.py` | `ToolCategory`, `ToolResult`, `Tool` protocol |
| `taui/tools/registry.py` | `ToolRegistry`: register, lookup, schemas, subset, guidelines |
| `taui/tools/executor.py` | `PolicyDecision`, `ToolPolicy`, outcome types, `ToolExecutor` |
| `taui/tools/truncation.py` | `TruncationStore`, `TruncatedOutput` |
| `taui/tools/builtins/` | All built-in tool implementations |
| `taui/tools/builtins/common.py` | Shared utilities: path safety, binary detection, truncation |
