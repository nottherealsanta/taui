Done:
- [x] add a "/skills" and "/prompts" to list them like agents and models
- [x] multi line (more than x) input needs to have scroll to let user know
- [x] ./.taui folder should auto have .gitignore file with "*"
- [x] group tools: <tool_group_name>[<number_of_tools>] , list only group names (click to show more)
- [x] session_name tool not available after set  (unregistered once it names the session)
- [x] if cancelled before first tool call, then show the previous turn in the input
- [x] add more git tools (with auth access)  (fetch, pull, push, branch_create)
- [x] in agent - self-edit - toggle for edit requires user permission  (self_edit_confirm_edits)

Open:
- maybe tools need not have two scopes
- monty
- maybe worktree should not be a tool, just bash it
- "/worktree" for user to quickly jump to a worktree (a session cannot change worktree, new session will be created with the worktree)


---

### 1. Skills: when to evict tokens

The Agent Skills spec is **very clear** on this — it says the opposite of evicting:

> **Exempt skill content from pruning.** Skill instructions are durable behavioral guidance — losing them mid-conversation silently degrades the agent's performance without any visible error. The model continues operating but without the specialized instructions the skill provided.

The recommended approach from agentskills.io is:
- Flag skill tool outputs as **protected** so compaction skips them
- Use structured tags to identify and preserve skill content

So **neither "after a turn" nor "after task done"** — the spec says **keep them for the session**. The rationale is sound: skills are behavioral guidance, not ephemeral data. Silently losing them mid-task causes invisible degradation.

However, your instinct about token cost is valid. The spec's answer to that is **not eviction but budget control at load time**:

1. Keep `SKILL.md` under **5,000 tokens** (the spec recommends this hard)
2. Use **progressive disclosure** within skills — main instructions in `SKILL.md`, detailed references in separate files loaded on demand
3. **Subagent delegation** — run the skill in a separate subagent session instead of loading into the main context

If you still want an "unload" mechanism, the spec doesn't prohibit it — but it should be **explicit** (model or user calls `skills unload`), and it should **actually remove the message** from `_messages` rather than just toggling a flag (which is the current bug in your implementation).

**My recommendation**: Keep skills protected from compaction. Fix `_unload` to actually remove the system message. Don't auto-evict. If a skill is too expensive, the answer is a smaller skill, not auto-eviction.

---

### 2. MCP tool exposure: ephemeral meta-tool

The MCP spec's **Client Best Practices** page has an entire section called **Progressive Tool Discovery** that is *exactly* your idea. Key points:

**When to use it**: Once tool definitions exceed ~1-5% of the context window, switch from "load all tools" to progressive discovery.

**Three-layer pattern**:
1. **Catalog** — a `search_tools` meta-tool that accepts natural-language queries and returns names + one-line descriptions
2. **Inspect** — `get_tool_details` fetches the full schema for a single tool on demand
3. **Execute** — call the tool with full knowledge of its interface

Your current `McpTool` is already halfway there — it has `mcp tools` (catalog) and `mcp call` (execute). What's missing is the **inspect** layer and the **ephemeral injection** concept. Right now `mcp tools` dumps all tool names + descriptions into context and they stay there.

The spec also describes **Dynamic Server Management** — connect/disconnect entire servers on demand rather than at startup. You already have this with `mcp connect` / `mcp disconnect`.

**Prompt caching consideration** the spec raises: adding/removing tool definitions mid-conversation invalidates prompt cache, which can cost more tokens than the definitions you removed. Their suggestion: route everything through a **single stable `call_tool({name, args})` meta-tool** so the tools array never changes. This is exactly what your `mcp call` already does.

There's also a **Programmatic Tool Calling / Code Mode** pattern — instead of tool-calling MCP tools individually, the model writes code that calls tools in a sandbox, and only the final result returns to context. This goes even further than your idea — not just hiding tool definitions, but keeping tool *results* out of context too. Notably, the spec mentions **Monty** (from Pydantic) as an experimental Python sandbox for this, which is on your todo list.

**My recommendation**: Your `McpTool` meta-tool pattern is already the right architecture. To align with the spec:
1. Add a `search` operation to `McpTool` — natural-language search over connected server tools (even simple keyword matching would help)
2. Add an `inspect` operation — return the full schema for a single tool, so the model doesn't need `mcp tools` to dump everything
3. Consider **not auto-connecting** MCP servers at startup. Let the model call `mcp servers` to see what's available, then `mcp connect` only when needed. This is the "Dynamic Server Management" pattern.
4. Long-term, Monty / code mode would be the biggest context-savings win

---

### Where the two ideas converge (and diverge)

My earlier answer suggested they both need "ephemeral context with auto-eviction." After reading the specs, I'd revise that:

- **Skills**: the spec explicitly says **don't auto-evict**. Protect them. Budget-control at authoring time instead.
- **MCP tools**: the spec says **yes, progressive/ephemeral discovery is correct**. Don't load tool definitions into context until needed, and route calls through a stable meta-tool.

The underlying principle from both specs is the same — **progressive disclosure** — but applied differently. Skills progressively disclose *within* a skill (catalog → instructions → resources). MCP tools progressively disclose *across* tools (search → inspect → execute). Neither recommends time-based eviction.
---