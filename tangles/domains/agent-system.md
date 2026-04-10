---
title: Agent System
last_updated: 2026-04-10
---

# Agent System

Prime, root, and sub agents — LLM orchestration, session management, tool execution, and the multi-agent hierarchy.

Depends on: [Backend](backend.md), [Tangle Module](tangle-module.md)

## Responsibility

Owns agent lifecycle, LLM communication, tool dispatch, and the agent hierarchy (prime -> root -> sub). Agents read and write tangles, execute tools, and interact with users through the chat pane.

Specifically:

- **Prime agent**: Always-on singleton per workspace (`taui/agent/prime.py:PrimeAgent`). Maintains full conversation history across restarts. Users interact through the main chat pane. The `send_message` method (line 118) drives the outer request/response cycle; `_think_loop` (line 237) runs the inner LLM iteration until the model stops requesting tools. Can launch root agents for longer tasks.
- **Root agents**: Longer-running task agents managed by `taui/agent/manager.py:AgentManager.launch` (line 71). Each gets a unique ID, a display name from `taui/agent/naming.py:generate_name`, and a color from `generate_color`. Each gets its own tab in the UI. Can spawn sub-agents.
- **Sub-agents**: Scoped agents for specific subtasks within a root agent's work. Executed through the same `taui/agent/runner.py:AgentRunner` loop as root agents but with a narrower `taui/agent/box.py:Box` capability set.
- **Tool execution**: file read/write, bash commands, search, tangle operations — dispatched from `taui/agent/runner.py:AgentRunner._execute_tool` (line 795).
- **Session persistence**: all messages, tool calls, and tool results stored in `.taui/agents.db` via `taui/tangle/agent_db.py:AgentHistoryDB.add_message` (line 242).
- **Branch locking**: prevents concurrent agents from editing the same files, enforced inside `taui/agent/manager.py:AgentManager`.
- **Cost tracking**: token usage and cost accumulated per session by `taui/agent/cost_tracker.py:CostTracker`.

## Invariants

- Agent conversation history is persisted to `.taui/agents.db` via `taui/tangle/agent_db.py:AgentHistoryDB` — survives restart. Sessions are created with `create_session` (line 210) and retrieved with `get_messages` (line 282).
- Prime agent session is singleton per workspace — `taui/agent/prime.py:PrimeAgent._ensure_initialized` (line 622) enforces this on first use.
- Root agents get unique IDs and display colors — assigned at launch time by `taui/agent/manager.py:AgentManager.launch` (line 71) using `taui/agent/naming.py:generate_name` and `generate_color`.
- Branch locks prevent concurrent file edits by different agents — managed in `taui/agent/manager.py:AgentManager`.
- All agent messages and tool calls are recorded for audit/replay via `taui/tangle/history_store.py:ProjectHistoryStore.add_message` (line 57).
- System prompts are loaded from `.taui/settings.json` with built-in defaults as fallback — see `taui/agent/system_prompt_loader.py:get_prompt_template_for_workspace` (line 36) and `_load_sections` (line 13).

## Interfaces

- `taui/agent/prime.py:PrimeAgent` — prime agent entry point; `send_message` (line 118), `cancel` (line 150)
- `taui/agent/manager.py:AgentManager` — root/sub agent lifecycle; `launch` (line 71), `cancel` (line 272), `subscribe` (line 249), `startup_recovery` (line 487)
- `taui/agent/runner.py:AgentRunner` — single agent execution loop; `run` (line 171), `_handle_message` (line 236), `_task_loop` (line 489)
- `taui/agent/box.py:Box` — agent capability sandbox; `start` (line 89), `complete` (line 100), `fail` (line 117)
- `taui/agent/planner.py:TaskGraph` — task graph for multi-step plans (line 70); `TaskNode` dataclass (line 36)
- `taui/agent/system_prompt_loader.py:get_prompt_template_for_workspace` — loads prompts from settings with fallback (line 36)

## Key Components

- **PrimeAgent** (`taui/agent/prime.py:PrimeAgent`, lines 46–1013) — Main agent: handles user messages via `send_message` (line 118), runs the LLM iteration loop in `_think_loop` (line 237), streams output tokens through `_stream_text` (line 460), and builds the model's context with `_build_system_prompt` (line 708). Delegates tool results to `_handle_tool_result` (line 387).
- **AgentManager** (`taui/agent/manager.py:AgentManager`, lines 27–597) — Manages root/sub agent lifecycle. `launch` (line 71) creates a new runner, assigns naming/color, and registers it. `_create_runner` (line 169) wires up the `AgentRunner`. `subscribe`/`unsubscribe` (lines 249/261) expose an event bus for UI updates. `startup_recovery` (line 487) re-attaches in-progress agents after a server restart.
- **AgentRunner** (`taui/agent/runner.py:AgentRunner`, lines 153–1048) — Core execution loop: `run` (line 171) initializes the session; `_handle_message` (line 236) processes incoming messages and dispatches to `_task_loop` (line 489); `_execute_tool` (line 795) invokes individual tools; `_build_agent_policy` (line 962) constructs per-agent capability constraints.
- **Box** (`taui/agent/box.py:Box`, lines 73–166) — Capability container for an agent (tools, permissions, context). Status lifecycle tracked by `taui/agent/box.py:BoxStatus` enum (lines 31–38): `running → completed | failed | cancelled`. Transitions via `start` (line 89), `complete` (line 100), and `fail` (line 117).
- **Planner** (`taui/agent/planner.py:TaskGraph`, lines 70–247) — Task graph for multi-step agent plans. Each node is a `taui/agent/planner.py:TaskNode` dataclass (lines 36–67) with fields: `id`, `title`, `description`, `status`, `depends_on`, `agent_id`. Moved from the old `tangle/taskgraph.py`.
- **AgentDefinitions** (`taui/agent/agents.py`) — Predefined agent roles as `AgentDefinition` dataclasses (lines 11–27, fields: `name`, `role`, `description`, `tools`). Predefined agents: `EXPLORER` (line 32), `PLANNER` (line 50), `BUILDER` (line 69), `GENERAL` (line 80).
- **CostTracker** (`taui/agent/cost_tracker.py:CostTracker`) — Accumulates token usage and cost per agent session. Referenced from `AgentRunner` after each LLM response.
- **Naming** (`taui/agent/naming.py`) — `generate_name` produces human-readable display names; `generate_color` assigns a stable UI color. Both called at `AgentManager.launch` (line 71).
- **System Prompt Loader** (`taui/agent/system_prompt_loader.py`) — `get_prompt_template_for_workspace` (line 36) loads per-role prompt sections from `.taui/settings.json`, falling back to the bundled `taui/agent/system_prompts.md` (sections: `## Prime` lines 3–39, `## Root` lines 40–61, `## Sub-Agent` lines 62–81). `_load_sections` (line 13) parses the markdown file; `render_prompt_template` (line 82) does variable substitution.
- **AgentHistoryDB** (`taui/tangle/agent_db.py:AgentHistoryDB`, lines 186–598) — SQLite-backed store for agent sessions and messages. Key methods: `create_session` (line 210), `add_message` (line 242), `get_messages` (line 282), `get_sessions` (line 322). Lives in `tangle/` but logically belongs in `agent/` — see Open Questions.
- **ProjectHistoryStore** (`taui/tangle/history_store.py:ProjectHistoryStore`, lines 9–138) — Thin facade over `AgentHistoryDB` scoped to a single workspace project. `init` (line 20) opens the DB; `create_session` (line 37) and `add_message` (line 57) are the primary write paths used by `AgentRunner`.

## Code References

- `taui/agent/prime.py:PrimeAgent` (lines 46–1013) — prime agent class
  - `taui/agent/prime.py:PrimeAgent.send_message` (lines 118–148) — outer message handler
  - `taui/agent/prime.py:PrimeAgent._think_loop` (lines 237–384) — inner LLM iteration loop
  - `taui/agent/prime.py:PrimeAgent._handle_tool_result` (lines 387–458) — processes tool call results
  - `taui/agent/prime.py:PrimeAgent._stream_text` (lines 460–505) — streams tokens to the UI
  - `taui/agent/prime.py:PrimeAgent._ensure_initialized` (lines 622–706) — lazy singleton init
  - `taui/agent/prime.py:PrimeAgent._build_system_prompt` (lines 708–798) — assembles system prompt
  - `taui/agent/prime.py:PrimeAgent.cancel` (lines 150–168) — cancels in-flight generation
- `taui/agent/manager.py:AgentManager` (lines 27–597) — root/sub agent lifecycle
  - `taui/agent/manager.py:AgentManager.launch` (lines 71–167) — creates and registers a new agent
  - `taui/agent/manager.py:AgentManager._create_runner` (lines 169–247) — wires up an AgentRunner
  - `taui/agent/manager.py:AgentManager.subscribe` (lines 249–259) — register UI event listener
  - `taui/agent/manager.py:AgentManager.unsubscribe` (lines 261–270) — deregister event listener
  - `taui/agent/manager.py:AgentManager.cancel` (lines 272–300) — cancels a running agent
  - `taui/agent/manager.py:AgentManager.startup_recovery` (lines 487–585) — re-attaches agents after restart
- `taui/agent/runner.py:AgentRunner` (lines 153–1048) — single agent execution loop
  - `taui/agent/runner.py:AgentRunner.run` (lines 171–234) — initializes and starts the session
  - `taui/agent/runner.py:AgentRunner._handle_message` (lines 236–487) — message dispatch
  - `taui/agent/runner.py:AgentRunner._task_loop` (lines 489–701) — LLM call + tool dispatch cycle
  - `taui/agent/runner.py:AgentRunner._execute_tool` (lines 795–945) — invokes a single tool
  - `taui/agent/runner.py:AgentRunner._build_agent_policy` (lines 962–1007) — capability constraints
- `taui/agent/box.py:Box` (lines 73–166) — agent capability container
  - `taui/agent/box.py:BoxStatus` (lines 31–38) — `running | completed | failed | cancelled`
  - `taui/agent/box.py:Box.start` (lines 89–98)
  - `taui/agent/box.py:Box.complete` (lines 100–115)
  - `taui/agent/box.py:Box.fail` (lines 117–132)
- `taui/agent/planner.py:TaskGraph` (lines 70–247) — multi-step task dependency graph
  - `taui/agent/planner.py:TaskNode` (lines 36–67) — node dataclass: `id`, `title`, `description`, `status`, `depends_on`, `agent_id`
- `taui/agent/agents.py:AgentDefinition` (lines 11–27) — agent role descriptor dataclass
  - `taui/agent/agents.py:EXPLORER` (lines 32–48)
  - `taui/agent/agents.py:PLANNER` (lines 50–67)
  - `taui/agent/agents.py:BUILDER` (lines 69–78)
  - `taui/agent/agents.py:GENERAL` (lines 80–84)
- `taui/agent/cost_tracker.py:CostTracker` — per-session token usage and cost accumulator
- `taui/agent/naming.py:generate_name` — generates human-readable agent display names
- `taui/agent/naming.py:generate_color` — assigns stable UI colors to agents
- `taui/agent/system_prompt_loader.py:get_prompt_template_for_workspace` (lines 36–79) — loads prompt with settings fallback
  - `taui/agent/system_prompt_loader.py:_load_sections` (lines 13–29) — parses `system_prompts.md`
  - `taui/agent/system_prompt_loader.py:render_prompt_template` (lines 82–86) — variable substitution
- `taui/agent/system_prompts.md` — bundled default prompts
  - `## Prime` (lines 3–39), `## Root` (lines 40–61), `## Sub-Agent` (lines 62–81)
- `taui/tangle/agent_db.py:AgentHistoryDB` (lines 186–598) — SQLite session/message store
  - `taui/tangle/agent_db.py:AgentHistoryDB.create_session` (lines 210–240)
  - `taui/tangle/agent_db.py:AgentHistoryDB.add_message` (lines 242–280)
  - `taui/tangle/agent_db.py:AgentHistoryDB.get_messages` (lines 282–320)
  - `taui/tangle/agent_db.py:AgentHistoryDB.get_sessions` (lines 322–360)
- `taui/tangle/history_store.py:ProjectHistoryStore` (lines 9–138) — workspace-scoped facade over `AgentHistoryDB`
  - `taui/tangle/history_store.py:ProjectHistoryStore.init` (lines 20–35)
  - `taui/tangle/history_store.py:ProjectHistoryStore.create_session` (lines 37–55)
  - `taui/tangle/history_store.py:ProjectHistoryStore.add_message` (lines 57–80)
- `taui/agent/__init__.py` — module exports

## Verification

- `tests/test_agent.py` — Agent session and execution tests
- `tests/test_agent_rpc.py` — Agent RPC method tests
- `tests/test_prime.py` — Prime agent specific tests
- `tests/test_history.py` — Agent history persistence tests

```
pytest tests/test_agent.py tests/test_agent_rpc.py tests/test_prime.py tests/test_history.py -q
```

## Open Questions

- Should `taui/tangle/agent_db.py:AgentHistoryDB` and `taui/tangle/history_store.py:ProjectHistoryStore` move from `taui/tangle/` to `taui/agent/`?
- The `spec_ref` → `tangle_ref` rename is incomplete in `taui/agent/box.py:Box`, `taui/agent/planner.py:TaskNode`, `taui/agent/prime.py:PrimeAgent`, and `taui/agent/runner.py:AgentRunner` — when to finish?
- `taui/agent/box.py:Box` still uses `spec_ref` as its primary field and `spec_compliance` naming — needs `tangle_ref` / `tangle_compliance`

## Related Features

- [Editable Prompts](../features/editable-prompts.md)
- [Stateless UI](../features/stateless-ui.md)

## Related Decisions

No decisions recorded yet.
