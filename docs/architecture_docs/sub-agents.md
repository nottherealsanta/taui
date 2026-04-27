# Sub-Agents

Sub-agents let the parent agent delegate focused work to a child agent that runs in its own conversation context with a scoped set of tools.

---

## Architecture

```
Parent Agent
  │
  ├── SubAgentTool.execute(task, tools, max_turns)
  │       │
  │       ├── Create scoped ToolRegistry (subset of parent)
  │       ├── Create child ToolExecutor + ToolPolicy
  │       ├── Create child AgentLoop (own messages, own turns)
  │       ├── Run child loop to completion
  │       └── Return final text as ToolResult
  │
  └── (continues with child's response in context)
```

The child agent shares the parent's LLM provider and event stream but has its own:
- Message history (clean context window)
- Tool registry (scoped subset)
- Turn budget (default 10, max 25)
- System prompt (focused research agent)

---

## Tool Schema

```python
{
    "task": str,         # Required — what the sub-agent should do
    "tools": list[str],  # Optional — tool names to give the child
                         # Default: ["read", "glob", "grep", "bash"]
    "max_turns": int,    # Optional — turn budget (default 10, capped at 25)
}
```

---

## Tool Resolution

The parent passes tool names to scope the child. Only tools that exist in the parent's registry are included:

```python
# Requested tools are intersected with parent registry
tool_names = [t for t in requested_tools if t in parent_registry]

# "sub_agent" is always filtered out — no recursion
tool_names = [t for t in tool_names if t != "sub_agent"]
```

If no tools are requested, the child gets `["read", "glob", "grep", "bash"]` (read-only defaults). If the result is empty (e.g., all requested tools are unknown), the child runs in thinking-only mode with an empty registry.

---

## Recursion Prevention

Sub-agents cannot spawn sub-agents. The `sub_agent` tool name is explicitly filtered from the child's tool list regardless of what the parent requests. This prevents unbounded recursion and context explosion.

---

## Shared Dependencies

| Resource | Shared? | Notes |
|----------|---------|-------|
| LLM provider | Yes | Same authenticated provider instance |
| Event stream | Yes | Child events go to same Store |
| Tool registry | No | Child gets a `subset()` copy |
| Messages | No | Child starts with clean history |
| Turn budget | No | Independent from parent's budget |
| System prompt | No | Child gets its own focused prompt |
| Working directory | Yes | Inherited via tool `working_dir` attribute |

---

## Wiring (Session.create)

```python
sub_agent = registry.get("sub_agent")
sub_agent._llm = provider         # Shared LLM
sub_agent._stream = stream         # Shared event stream
sub_agent._parent_executor = executor  # For registry access
sub_agent._model = config.model
sub_agent._system_prompt = ""      # Uses default
```

---

## Error Handling

If the child loop raises an exception, the sub-agent returns `ToolResult.fail()` with the error message. The parent continues its conversation — a child failure does not crash the parent.

---

## Use Cases

- **Research**: Read files and grep for patterns in a fresh context
- **Code analysis**: Analyze a module without polluting parent's context window
- **Exploration**: Try multiple approaches in isolation
- **Thinking-only**: Zero-tool sub-agents for reasoning tasks
