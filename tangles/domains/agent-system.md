---
title: Agent System
last_updated: 2026-04-11
---

# Agent System

Prime, root, and sub agents — LLM orchestration, session management, tool execution, and the multi-agent hierarchy.

Depends on: [Backend](backend.md), [Tangle Module](tangle-module.md)

## Responsibility

Owns agent lifecycle, LLM communication, tool dispatch, and the agent hierarchy (prime → root → sub). Agents read and write tangles, execute tools, and interact with users through the chat pane.

- **Prime agent** — always-on singleton per workspace (`taui/agent/prime.py:PrimeAgent`)
  - Maintains full conversation history across restarts
  - `send_message` (line 118) drives the outer request/response cycle
  - `_think_loop` (line 237) runs the inner LLM iteration until the model stops requesting tools
  - Can launch root agents for longer tasks
- **Root agents** — longer-running task agents managed by `taui/agent/manager.py:AgentManager.launch` (line 71)
  - Each gets a unique ID, display name from `taui/agent/naming.py:generate_name`, and color from `generate_color`
  - Each gets its own tab in the UI and can spawn sub-agents
- **Sub-agents** — scoped agents for specific subtasks within a root agent's work
  - Executed through the same `taui/agent/runner.py:AgentRunner` loop but with a narrower `taui/agent/box.py:Box` capability set
- **Tool execution** — file read/write, bash commands, search, tangle operations
  - Dispatched from `taui/agent/runner.py:AgentRunner._execute_tool` (line 795)
- **Session persistence** — all messages, tool calls, and results stored in `.taui/agents.db`
  - via `taui/tangle/agent_db.py:AgentHistoryDB.add_message` (line 242)
- **Branch locking** — prevents concurrent agents from editing the same files
  - Enforced inside `taui/agent/manager.py:AgentManager`
- **Cost tracking** — token usage and cost accumulated per session by `taui/agent/cost_tracker.py:CostTracker`

## Invariants

- Agent conversation history persisted to `.taui/agents.db` via `taui/tangle/agent_db.py:AgentHistoryDB` — survives restart
  - Sessions created with `create_session` (line 210); retrieved with `get_messages` (line 282)
- Prime agent session is singleton per workspace
  - `taui/agent/prime.py:PrimeAgent._ensure_initialized` (line 622) enforces this on first use
- Root agents get unique IDs and display colors — assigned at launch by `taui/agent/manager.py:AgentManager.launch` (line 71)
- Branch locks prevent concurrent file edits by different agents — managed in `taui/agent/manager.py:AgentManager`
- All agent messages and tool calls are recorded for audit/replay
  - via `taui/tangle/history_store.py:ProjectHistoryStore.add_message` (line 57)
- System prompts loaded from `.taui/settings.json` with built-in defaults as fallback
  - via `taui/agent/system_prompt_loader.py:get_prompt_template_for_workspace` (line 36) and `_load_sections` (line 13)

## Interfaces

- `taui/agent/prime.py:PrimeAgent` — prime agent entry point
  - `send_message` (line 118), `cancel` (line 150)
- `taui/agent/manager.py:AgentManager` — root/sub agent lifecycle
  - `launch` (line 71), `cancel` (line 272), `subscribe` (line 249), `startup_recovery` (line 487)
- `taui/agent/runner.py:AgentRunner` — single agent execution loop
  - `run` (line 171), `_handle_message` (line 236), `_task_loop` (line 489)
- `taui/agent/box.py:Box` — agent capability sandbox
  - `start` (line 89), `complete` (line 100), `fail` (line 117)
- `taui/agent/planner.py:TaskGraph` — task graph for multi-step plans (line 70)
  - `TaskNode` dataclass (line 36): `id`, `title`, `description`, `status`, `depends_on`, `agent_id`
- `taui/agent/system_prompt_loader.py:get_prompt_template_for_workspace` — loads prompts from settings with fallback (line 36)

## Key Components

- **PrimeAgent** (`taui/agent/prime.py:PrimeAgent`, lines 46–1013) — main agent
  - `send_message` (line 118) — handles user messages
  - `_think_loop` (line 237) — inner LLM iteration loop
  - `_stream_text` (line 460) — streams output tokens to the UI
  - `_handle_tool_result` (line 387) — processes tool call results
  - `_build_system_prompt` (line 708) — assembles model context
  - `_ensure_initialized` (line 622) — lazy singleton init
  - `cancel` (line 150) — cancels in-flight generation
- **AgentManager** (`taui/agent/manager.py:AgentManager`, lines 27–597) — root/sub agent lifecycle
  - `launch` (line 71) — creates a new runner, assigns naming/color, and registers it
  - `_create_runner` (line 169) — wires up an `AgentRunner`
  - `subscribe` / `unsubscribe` (lines 249/261) — UI event bus registration
  - `cancel` (line 272) — cancels a running agent
  - `startup_recovery` (line 487) — re-attaches in-progress agents after a server restart
- **AgentRunner** (`taui/agent/runner.py:AgentRunner`, lines 153–1048) — core execution loop
  - `run` (line 171) — initialises and starts the session
  - `_handle_message` (line 236) — processes incoming messages and dispatches to `_task_loop`
  - `_task_loop` (line 489) — LLM call + tool dispatch cycle
  - `_execute_tool` (line 795) — invokes individual tools
  - `_build_agent_policy` (line 962) — constructs per-agent capability constraints
- **Box** (`taui/agent/box.py:Box`, lines 73–166) — capability container for an agent (tools, permissions, context)
  - Status lifecycle tracked by `taui/agent/box.py:BoxStatus` enum (lines 31–38): `running → completed | failed | cancelled`
  - Transitions via `start` (line 89), `complete` (line 100), `fail` (line 117)
- **Planner** (`taui/agent/planner.py:TaskGraph`, lines 70–247) — task graph for multi-step agent plans
  - Each node is a `taui/agent/planner.py:TaskNode` dataclass (lines 36–67): `id`, `title`, `description`, `status`, `depends_on`, `agent_id`
- **AgentDefinitions** (`taui/agent/agents.py`) — predefined agent roles as `AgentDefinition` dataclasses (lines 11–27: `name`, `role`, `description`, `tools`)
  - Predefined roles: `EXPLORER` (line 32), `PLANNER` (line 50), `BUILDER` (line 69), `GENERAL` (line 80)
- **CostTracker** (`taui/agent/cost_tracker.py:CostTracker`) — accumulates token usage and cost per session; called from `AgentRunner` after each LLM response
- **Naming** (`taui/agent/naming.py`) — `generate_name` produces human-readable display names; `generate_color` assigns stable UI colors; both called at `AgentManager.launch` (line 71)
- **System Prompt Loader** (`taui/agent/system_prompt_loader.py`) — loads and renders role-specific prompts
  - `get_prompt_template_for_workspace` (line 36) — loads per-role sections from `.taui/settings.json`, falling back to bundled `taui/agent/system_prompts.md`
    - Bundled sections: `## Prime` (lines 3–39), `## Root` (lines 40–61), `## Sub-Agent` (lines 62–81)
  - `_load_sections` (line 13) — parses the markdown prompt file
  - `render_prompt_template` (line 82) — variable substitution
- **AgentHistoryDB** (`taui/tangle/agent_db.py:AgentHistoryDB`, lines 186–598) — SQLite-backed store for agent sessions and messages
  - `create_session` (line 210), `add_message` (line 242), `get_messages` (line 282), `get_sessions` (line 322)
  - Lives in `tangle/` but logically belongs in `agent/` — see Open Questions
- **ProjectHistoryStore** (`taui/tangle/history_store.py:ProjectHistoryStore`, lines 9–138) — workspace-scoped facade over `AgentHistoryDB`
  - `init` (line 20) opens the DB
  - `create_session` (line 37) and `add_message` (line 57) are the primary write paths used by `AgentRunner`

## Verification

- `tests/test_agent.py` — agent session and execution tests
- `tests/test_agent_rpc.py` — agent RPC method tests
- `tests/test_prime.py` — prime agent specific tests
- `tests/test_history.py` — agent history persistence tests

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
