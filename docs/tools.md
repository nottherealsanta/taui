# Tools

Tools are the only way an agent reads, writes, searches, shells out, asks questions, or
spawns sub-agents.

## Core Contracts

- Tool categories: `taui/tools/base.py:10`
- `ToolResult.ok()` / `ToolResult.fail()`: `taui/tools/base.py:24`
- Tool protocol: `taui/tools/base.py:52`
- Registry: `taui/tools/registry.py:10`
- Builtin registration: `taui/tools/builtins/__init__.py:28`
- Executor and policy gate: `taui/tools/executor.py:180`

## Execution Path

1. `AgentLoop` receives provider tool calls: `taui/agent/loop.py:365`.
2. The loop sends each call to `ToolExecutor.execute()`: `taui/tools/executor.py:219`.
3. Policy checks decide auto, confirm, or deny: `taui/tools/executor.py:60`.
4. Expected tool failures return `ToolResult.fail()`: `taui/tools/base.py:34`.
5. Results are stored as stream events: `taui/agent/loop.py:547`.

Read and search categories can run concurrently in the loop:
`taui/agent/loop.py:493`.

## Builtins

| Tool area | Code |
| --- | --- |
| file read/write/glob/grep | `taui/tools/builtins/files.py:68` |
| edit | `taui/tools/builtins/edit.py:206` |
| apply_patch | `taui/tools/builtins/apply_patch.py:50` |
| bash | `taui/tools/builtins/bash.py:67` |
| git | `taui/tools/builtins/git.py:63` |
| MCP | `taui/tools/builtins/mcp.py:72` |
| memory | `taui/tools/builtins/memory.py:18` |
| question | `taui/tools/builtins/question.py:59` |
| skills | `taui/tools/builtins/skills.py:61` |
| sub-agent | `taui/tools/builtins/sub_agent.py:84` |
| task | `taui/tools/builtins/task.py:97` |
| webfetch | `taui/tools/builtins/webfetch.py:80` |
| LSP | `taui/tools/builtins/lsp.py:100` |
| repo overview | `taui/tools/builtins/repo_overview.py:41` |
| notebook edit | `taui/tools/builtins/notebook_edit.py:64` |

## Policies

Per-tool defaults and overrides are handled by `ToolPolicy`: `taui/tools/executor.py:42`.
Pattern rules are handled by `PermissionRuleset`: `taui/permissions.py:38`.

See `docs/permission-dsl.md:1` for TOML examples.

## Tool Authoring Rules

- Keep schemas explicit and JSON-serializable; provider conversion happens downstream:
  `taui/llm_provider/base.py:127`.
- Return `ToolResult.fail()` for normal user-facing failures.
- Raise only for truly unexpected bugs.
- Put filesystem path checks in the tool, not only in the UI.
- Register through `ToolRegistry.register()` or `register_or_replace()`:
  `taui/tools/registry.py:27`.
