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

- **Prime agent**: Always-on agent with full conversation history. Users interact through the main chat pane. Can launch root agents for longer tasks.
- **Root agents**: Longer-running task agents. Each gets its own tab and color in the UI. Can spawn sub-agents.
- **Sub-agents**: Scoped agents for specific subtasks within a root agent's work.
- Tool execution: file read/write, bash commands, search, tangle operations
- Session persistence: all messages, tool calls, tool results stored in `agents.db`
- Branch locking: prevents concurrent agents from editing the same files
- Cost tracking: token usage per agent session

## Invariants

- Agent conversation history is persisted to `.taui/agents.db` — survives restart.
- Prime agent session is singleton per workspace.
- Root agents get unique IDs and display colors.
- Branch locks prevent concurrent file edits by different agents.
- All agent messages and tool calls are recorded for audit/replay.
- System prompts are loaded from `.taui/settings.json` with built-in defaults as fallback.

## Interfaces

- `taui/agent/prime.py:PrimeAgent` — prime agent entry point
- `taui/agent/manager.py:AgentManager` — root/sub agent lifecycle
- `taui/agent/runner.py:AgentRunner` — single agent execution loop
- `taui/agent/session.py` — session state management
- `taui/agent/box.py:Box` — agent capability sandbox
- `taui/agent/planner.py` — task graph for multi-step plans
- `taui/agent/system_prompt_loader.py` — loads prompts from settings

## Key Components

- **PrimeAgent** (`taui/agent/prime.py`) — Main agent: handles user messages, tree rendering, root agent launching -> `taui/agent/prime.py:PrimeAgent`
- **AgentManager** (`taui/agent/manager.py`) — Manages root/sub agent lifecycle, branch locks -> `taui/agent/manager.py:AgentManager`
- **AgentRunner** (`taui/agent/runner.py`) — Execution loop: LLM call -> tool dispatch -> response -> repeat -> `taui/agent/runner.py:AgentRunner`
- **Box** (`taui/agent/box.py`) — Capability container for an agent (tools, permissions, context) -> `taui/agent/box.py:Box`
- **Planner** (`taui/agent/planner.py`) — Task graph for multi-step agent plans (moved from `tangle/taskgraph.py`) -> `taui/agent/planner.py`
- **CostTracker** (`taui/agent/cost_tracker.py`) — Token usage tracking -> `taui/agent/cost_tracker.py:CostTracker`
- **Naming** (`taui/agent/naming.py`) — Agent name and color generation -> `taui/agent/naming.py`
- **System Prompt Loader** (`taui/agent/system_prompt_loader.py`) — Loads from `settings.json` with defaults -> `taui/agent/system_prompt_loader.py`
- **AgentHistoryDB** (`taui/tangle/agent_db.py`) — Agent session/message persistence (note: lives in `tangle/` but belongs in `agent/`) -> `taui/tangle/agent_db.py:AgentHistoryDB`
- **ProjectHistoryStore** (`taui/tangle/history_store.py`) — Facade over AgentHistoryDB -> `taui/tangle/history_store.py:ProjectHistoryStore`

## Code References

- `taui/agent/__init__.py`
- `taui/agent/prime.py`
- `taui/agent/manager.py`
- `taui/agent/runner.py`
- `taui/agent/session.py`
- `taui/agent/box.py`
- `taui/agent/planner.py`
- `taui/agent/cost_tracker.py`
- `taui/agent/naming.py`
- `taui/agent/system_prompt_loader.py`
- `taui/agent/agents.py`
- `taui/tangle/agent_db.py`
- `taui/tangle/history_store.py`

## Verification

- `tests/test_agent.py` — Agent session and execution tests
- `tests/test_agent_rpc.py` — Agent RPC method tests
- `tests/test_prime.py` — Prime agent specific tests
- `tests/test_history.py` — Agent history persistence tests

```
pytest tests/test_agent.py tests/test_agent_rpc.py tests/test_prime.py tests/test_history.py -q
```

## Open Questions

- Should `agent_db.py` and `history_store.py` move from `taui/tangle/` to `taui/agent/`?
- The `spec_ref` -> `tangle_ref` rename is incomplete in `box.py`, `planner.py`, `prime.py`, and `runner.py` — when to finish?
- `box.py` still uses `spec_ref` as its primary field and `spec_compliance` naming — needs `tangle_ref` / `tangle_compliance`

## Related Features

- [Editable Prompts](../features/editable-prompts.md)
- [Stateless UI](../features/stateless-ui.md)

## Related Decisions

No decisions recorded yet.
