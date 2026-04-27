# Tool System Overview

Tools are how the agent interacts with the outside world. Every file read, edit, shell command, and git operation goes through a tool.

---

## Architecture

```
LLM response (tool_calls)
  → AgentLoop._execute_tool()
    → ToolExecutor.run(call_id, name, arguments)
      → ToolPolicy.decide(name) → AUTO | CONFIRM | DENY
        → DENY: return Denied
        → CONFIRM + not approved: return NeedsApproval
        → AUTO or approved: tool.execute(arguments)
          → ToolResult(.ok | .fail)
      → wrap in Completed
    → append Message(role="tool", content, tool_call_id)
  → next LLM turn
```

---

## Core Types (`taui/tools/base.py`)

### ToolCategory

```python
class ToolCategory(str, Enum):
    FILE_READ = "file_read"    # read, glob
    FILE_WRITE = "file_write"  # write, edit
    SEARCH = "search"          # grep
    SHELL = "shell"            # bash
    GIT = "git"                # git
    AGENT = "agent"            # (future: sub-agents)
    MEMORY = "memory"          # memory
    QUESTION = "question"      # question
```

Categories serve two purposes:
1. **Policy grouping** — set policies by category (e.g., auto-approve all `FILE_READ`)
2. **Schema filtering** — `registry.schemas(include={FILE_READ})` for scoped sub-agents

### ToolResult

```python
@dataclass(slots=True)
class ToolResult:
    content: str                          # Text returned to the LLM
    error: bool = False                   # If True, content is an error message
    metadata: dict[str, Any] = {}         # Machine-readable extras (duration_ms, path, etc.)

    @classmethod ok(content, **metadata)  # Convenience: error=False
    @classmethod fail(content, **metadata)  # Convenience: error=True
```

The LLM only sees `content`. `metadata` is for frontends and diagnostics. `error` affects how the CLI displays results (red vs dim).

### Tool Protocol

```python
class Tool(Protocol):
    name: str                             # Unique identifier (e.g. "read", "bash")
    description: str                      # Shown to LLM in tool schema
    schema: dict[str, Any]                # JSON Schema for parameters
    category: ToolCategory

    async def execute(self, arguments: dict[str, Any]) -> ToolResult: ...
```

Tools are duck-typed. Any class with these attributes and an async `execute` method satisfies the protocol. No base class inheritance required.

**Optional attribute**: `guidelines: str` — per-tool usage hints injected into the system prompt.

---

## Registry (`taui/tools/registry.py`)

```python
class ToolRegistry:
    register(tool)                        # Add tool, raises on duplicate
    register_or_replace(tool)             # Add or overwrite
    unregister(name) -> Tool              # Remove and return
    get(name) -> Tool                     # Lookup, raises on miss
    names -> list[str]                    # Sorted tool names
    by_category(cat) -> list[Tool]        # Filter
    schemas(*, include, exclude)          # OpenAI function-calling format
    subset(names) -> ToolRegistry         # New registry with subset of tools
    guidelines() -> str                   # Collected per-tool guidelines
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

**`subset()`** creates scoped registries for sub-agents (e.g., a read-only sub-agent gets only `["read", "glob", "grep"]`).

**`guidelines()`** collects `tool.guidelines` strings from all tools that have them, formatted as a markdown list.

---

## Executor (`taui/tools/executor.py`)

The executor sits between the agent loop and tools, enforcing policy:

### Policy

```python
class PolicyDecision(str, Enum):
    AUTO = "auto"         # Execute without asking
    CONFIRM = "confirm"   # Ask user first
    DENY = "deny"         # Block entirely

class ToolPolicy:
    decide(tool_name) -> PolicyDecision   # Check overrides, then defaults
    set(tool_name, decision)              # Override for specific tool
```

Default: all tools are `AUTO`. The CLI can set tools like `bash` or `write` to `CONFIRM` for safety.

### Execution Outcomes

```python
Completed(result: ToolResult)        # Tool ran (success or graceful failure)
NeedsApproval(tool_call_id, ...)     # Policy says CONFIRM, user not yet asked
Denied(result: ToolResult)           # Policy says DENY, or user rejected
```

The agent loop handles `NeedsApproval` by calling `on_approval` callback, then re-running with `approved=True/False`.

### Error Handling

- Unknown tool → `Completed(ToolResult.fail("Unknown tool: ..."))`
- Tool raises exception → `Completed(ToolResult.fail("Tool failed: ..."))`
- Tool times out → `Completed(ToolResult.fail("Tool timed out..."))`
- Default timeout: 120 seconds

Errors are always returned as `Completed` with `error=True` — never as exceptions that break the loop.

---

## Extension Points

For self-edit, extensions register tools via:

```python
# Extension creates a tool class satisfying the Tool protocol
registry.register(my_custom_tool)         # Add new tool
registry.register_or_replace(my_tool)     # Override existing tool
registry.unregister("old_tool")           # Remove a tool
```

The registry is accessible via `session._registry`. Extensions loaded at startup can modify it before the first LLM turn.

---

## Files

| File | Lines | Purpose |
|------|-------|---------|
| `taui/tools/base.py` | 53 | ToolCategory, ToolResult, Tool Protocol |
| `taui/tools/registry.py` | 113 | ToolRegistry: register, lookup, schemas, subset |
| `taui/tools/executor.py` | 161 | ToolPolicy, outcomes, ToolExecutor |
| `taui/tools/__init__.py` | 14 | Re-exports |
| `taui/tools/builtins/__init__.py` | 43 | register_builtins() |
