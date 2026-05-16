# Sub-Agents

Taui supports spawning child agents from within the agent loop. A sub-agent is a fully
isolated `AgentLoop` with its own conversation, its own tool subset, and its own turn
budget — but it shares the parent's LLM provider, event store, and working directory.

---

## Architecture

```
Parent AgentLoop
  └── sub_agent tool
        └── Session.create_sub_session()
              └── Child AgentLoop
                    ├── scoped ToolRegistry (subset of parent)
                    ├── own message list (empty, no parent history)
                    ├── own turn budget
                    └── own system prompt
```

### Shared resources

| Resource | Shared |
|---|---|
| LLM provider | Yes — same `_provider` instance |
| Event stream / store | Yes — child stream written under `agents/<sub_id>` with `parent_id` pointing to parent stream |
| Working directory | Yes — inherited from parent `Session.config` |
| Cost tracker | Yes — charges accumulate in the parent session |
| Hooks | Yes — parent `HookRegistry` passed to child |

### Isolated resources

| Resource | Isolated |
|---|---|
| Message history | Child starts empty; cannot see parent conversation |
| ToolRegistry | Child gets a `registry.subset(tool_names)` or the parent's full registry |
| Turn budget | Configured independently via `max_turns` |
| System prompt | Overridable per sub-session; defaults to parent prompt |
| Session ID / stream ID | Unique per child (`agents/<uuid12>`) |

---

## `sub_agent` Tool

`taui/tools/builtins/sub_agent.py:SubAgentTool`

Registers as tool name `"sub_agent"` in the `AGENT` category.

### Schema

```json
{
  "task":      "string (required) — clear description of the sub-task",
  "tools":     "array of strings (optional) — tool names the child may use",
  "max_turns": "integer (optional) — turn cap for the child"
}
```

### Defaults

| Parameter | Default | Hard cap |
|---|---|---|
| `tools` | `["read", "glob", "grep", "bash"]` | — |
| `max_turns` | `10` | `25` |

### Execution path

1. Validate `task` is a non-empty string.
2. Filter `"sub_agent"` from the requested tool list (recursion prevention — see below).
3. Clamp `max_turns` to `min(requested, 25)`.
4. Call `Session.create_sub_session(tools, system_prompt, model, max_turns)`.
5. Call `sub.send(task)` and await completion.
6. Return `ToolResult.ok(result.text, turns=..., state=...)`.

Any exception raised by the child session is caught and returned as
`ToolResult.fail("Sub-agent failed: <exc>")`.

### Legacy fallback

When `SubAgentTool._session` is `None` (e.g. in tests) the tool falls back to
constructing `AgentLoop` directly using injected `_llm`, `_stream`, and
`_parent_executor` attributes. This path is not used in production.

---

## `Session.create_sub_session()`

`taui/session.py:Session.create_sub_session`

```python
async def create_sub_session(
    *,
    name: str | None = None,
    tools: list[str] | None = None,
    system_prompt: str | None = None,
    model: str | None = None,
    max_turns: int | None = None,
) -> Session
```

Creates and persists a child `Session`. Steps:

1. Generate `sub_id = name or uuid4().hex[:12]`.
2. Build a scoped `ToolRegistry` via `registry.subset(tools)` if `tools` is given,
   otherwise reuse the parent registry.
3. Create a `ToolExecutor` with the parent's policy and timeout.
4. Resolve `system_prompt`, `model`, and `max_turns` — fall back to parent values.
5. Create the child stream in the store (`agents/<sub_id>`) with `parent_id` set to
   the parent stream ID.
6. Construct `AgentLoop` with `stream_id = "agents/<sub_id>"`.
7. Persist a new session record in the store.
8. Return the fully wired `Session`.

The returned session can be used like any other: `await sub.send(message)`.

---

## Recursion Prevention

`"sub_agent"` is always removed from the child's tool list before the child registry is
built:

```python
tool_names = [t for t in requested_tools if t != "sub_agent"]
```

This prevents unbounded nesting. A sub-agent can use any other tool the parent grants,
but it cannot spawn further sub-agents.

---

## Error Handling

| Failure mode | Outcome |
|---|---|
| `task` is empty or not a string | `ToolResult.fail("'task' must be a non-empty string.")` |
| No parent session configured | `ToolResult.fail("Sub-agent not configured. No parent session.")` |
| Child agent raises an exception | `ToolResult.fail("Sub-agent failed: <exc>")` |
| Child exhausts `max_turns` | Returns normally; `result.state` reflects the exhausted state |

Tool exceptions never propagate to the parent loop — they are always wrapped in
`ToolResult.fail()`.

---

## `task` Tool

`taui/tools/builtins/task.py:TaskTool`

Despite the similar name, the `task` tool is **not** a sub-agent launcher. It is a
**persistent in-session task list** for tracking multi-step work within a single agent
conversation.

### Operations

| Operation | Parameters | Description |
|---|---|---|
| `list` | — | Show all tasks with status icons |
| `add` | `title`, `priority?`, `notes?` | Create a new task |
| `update` | `task_id`, `status?`, `priority?`, `notes?`, `title?` | Modify an existing task |
| `complete` | `task_id` | Mark a task completed |
| `remove` | `task_id` | Delete a task |
| `clear` | — | Remove all tasks |

### Storage

Tasks are persisted as JSON at:

```
<working_dir>/.taui/sessions/<session_id>/tasks.json
```

They survive across turns within the same session and are accessible on replay.
Status values: `pending`, `in_progress`, `completed`, `cancelled`.
Priority values: `high`, `medium` (default), `low`.

---

## Typical Use Cases for `sub_agent`

- **Research**: gather information about a topic, library, or codebase section without
  polluting the parent conversation context.
- **Code analysis**: explore a module or file tree and return a structured summary.
- **Parallel exploration**: the parent can call `sub_agent` multiple times (sequentially)
  with different tool subsets or prompts to compare approaches.
- **Focused execution**: delegate a well-defined, bounded task (e.g. "find all usages of
  `ToolResult.fail` and list the call sites") with a read-only tool set so the parent
  can act on the result.

Prefer `sub_agent` when the delegated task benefits from a fresh context and has a clear
deliverable. For in-place step tracking within a single flow, use the `task` tool instead.
