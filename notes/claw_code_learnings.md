# Claw-Code Analysis & Learnings for Taui

Source: `ultraworkers/claw-code-parity` — a cleanroom rewrite of the Claude Code agent harness in Rust + Python.

## Architecture Overview

- **Rust runtime** (~5,300 LOC): session, compaction, permissions, hooks, sandbox, MCP, config
- **API client** (~1,500 LOC): Anthropic HTTP client + SSE streaming + OpenAI compat
- **CLI REPL** (~3,600 LOC): interactive terminal with slash commands, tool rendering
- **Plugin system**: manifest-based plugins with tools, commands, and hooks
- **Tool framework**: 40 tool specs (20 real, 20 stubs)
- **Python porting workspace**: reference data + parity audit tooling

---

## 1. Structured Conversation Compaction

**Current Taui gap**: `Session.compact_for_token_budget()` just drops oldest messages.

Claw-code compaction extracts structured summaries:
- Recent user requests (last 3)
- Pending work items (inferred from assistant messages)
- Key files referenced across the session
- Current work context
- Tool usage timeline
- Message counts by role

Summary merging: when compacting an already-compacted session, nests "previously compacted context" vs "newly compacted context" inside `<summary>` tags.

Continuation message instructs the model to "resume directly — do not acknowledge the summary, do not recap."

Config: `CompactionConfig { preserve_recent_messages: 4, max_estimated_tokens: 10_000 }`.

**Action**: Replace Taui's drop-oldest compaction with structured summarization that preserves intent and context.

---

## 2. Permission Policy Engine

**Current Taui gap**: Basic tool guards in `config/policies.py`.

Claw-code implements a full allow/deny/ask rule engine:

```
Permission modes (ordered):
  ReadOnly < WorkspaceWrite < DangerFullAccess < Prompt < Allow
```

- **Deny rules** checked first — instant block with reason
- **Ask rules** trigger interactive approval prompt
- **Allow rules** bypass mode checks
- **Hook overrides**: pre-tool-use hooks can return Allow/Deny/Ask decisions
- **Prompter trait**: pluggable UI for approval dialogs

Each tool declares its `required_permission` mode. The policy checks `current_mode >= required_mode` after applying rule overrides.

**Action**: Upgrade Taui's policy system to allow/deny/ask rule lists with pattern matching against tool names and inputs.

---

## 3. Pre/Post Tool-Use Hook Pipeline

**Current Taui gap**: No hook system exists.

Hook events: `PreToolUse`, `PostToolUse`, `PostToolUseFailure`

Hook commands are arbitrary shell scripts configured in settings:
```json
{
  "hooks": {
    "pre_tool_use": ["./scripts/validate.sh"],
    "post_tool_use": ["./scripts/notify.sh"],
    "post_tool_use_failure": ["./scripts/alert.sh"]
  }
}
```

Hook results can:
- Deny tool execution (with reason)
- Override permission decisions
- Modify tool input JSON
- Report progress to UI

Hooks are cancellable via `HookAbortSignal` (atomic bool).

**Action**: Add hook pipeline to `ToolExecutor`. Use cases: lint validation on writes, destructive command blocking, audit logging.

---

## 4. Sandbox & Container Isolation

**Current Taui gap**: No sandbox support.

Container detection checks:
- `/.dockerenv`, `/run/.containerenv`
- Env vars: `CONTAINER`, `DOCKER`, `PODMAN`, `KUBERNETES_SERVICE_HOST`
- `/proc/1/cgroup` markers: docker, containerd, kubepods, podman, libpod

Filesystem isolation modes: `Off`, `WorkspaceOnly`, `AllowList`

Linux namespace sandbox via `unshare` for process/network isolation.

Per-command sandbox config: each bash execution can override sandbox settings.

**Action**: Add container detection. Default to `WorkspaceOnly` filesystem isolation for bash tools. Relax in detected containers.

---

## 5. Plugin System with Tool/Command Extension

**Current Taui gap**: `plugins/` exists but is minimal.

Claw-code plugin manifest (`plugin.json`):
```json
{
  "name": "example",
  "version": "1.0.0",
  "description": "...",
  "permissions": ["read", "write", "execute"],
  "defaultEnabled": true,
  "hooks": { "PreToolUse": ["hooks/pre.sh"] },
  "tools": [{ "name": "...", "description": "...", "inputSchema": {}, "command": "...", "required_permission": "workspace-write" }],
  "commands": [{ "name": "/deploy", "description": "..." }]
}
```

Plugin kinds: Builtin, Bundled, External.

Conflict detection: no duplicate names between builtin and plugin tools.

**Action**: Adopt manifest-based plugin model. Let users add custom tools (e.g., deploy, test, lint) without modifying Taui core.

---

## 6. Config Layering

**Current Taui gap**: Flat config in `config/settings.py`.

Claw-code loads from three scoped sources (merged in order):
1. **User**: `~/.claude.json` (personal preferences)
2. **Project**: `.claude.json` in repo root (team conventions)
3. **Local**: `.claude/settings.local.json` (machine-specific, gitignored)

Each layer can define: permissions, hooks, MCP servers, plugins, model, sandbox config.

**Action**: Add `.taui.json` (project) and `~/.taui.json` (user) config sources. Merge with precedence: Local > Project > User.

---

## 7. MCP Client Orchestration

**Current Taui gap**: Has LSP client but no MCP support.

Claw-code supports 6 MCP transport types:
- **Stdio**: spawn subprocess, JSON-RPC over stdin/stdout
- **SSE**: server-sent events over HTTP
- **HTTP**: standard HTTP
- **WebSocket**: bidirectional
- **SDK**: native SDK integration
- **ManagedProxy**: proxied through cloud service

Tool name prefixing: `mcp__servername__toolname` prevents collisions.

Full PKCE-based OAuth flow for remote MCP servers.

Server signature hashing for deduplication of equivalent configs.

**Action**: Add MCP client support to connect to external tool servers (databases, APIs, custom tooling) via the standard MCP protocol. Start with Stdio transport.

---

## 8. Usage & Cost Tracking with Prompt Cache Monitoring

**Current Taui gap**: Basic `agent/cost_tracker.py`.

Claw-code tracks 4 token buckets: `input`, `output`, `cache_creation`, `cache_read`.

Model-specific pricing tables:
- Haiku: $1/$5 per million (input/output)
- Sonnet: $3/$15
- Opus: $15/$75

Prompt cache monitoring: detects unexpected drops in `cache_read_input_tokens` and reports them. This catches cases where the system prompt or context changed unnecessarily, causing expensive re-processing.

Per-turn and cumulative tracking with `UsageTracker`.

**Action**: Add prompt-cache awareness to cost tracking. Add per-model pricing tables. Wire cache-miss alerts into agent event stream.

---

## 9. Slash Commands & Session Management

**Current Taui gap**: Basic commands in `commands/builtins.py`.

Notable claw-code commands Taui should add:
- `/compact` — trigger manual session compaction
- `/model [name]` — switch model mid-session
- `/permissions [mode]` — change permission mode on the fly
- `/undo` — revert last file edit (from stored `originalFile` data)
- `/search` — search conversation history by keyword
- `/diff` — show git diff with colored output
- `/export` — export conversation to file
- `/sandbox` — show sandbox isolation status
- `/memory` — show/manage agent memory

**Action**: Add `/compact`, `/model`, `/undo`, `/search` as priority commands.

---

## 10. Telemetry & Request Profiling

**Current Taui gap**: No structured telemetry.

Claw-code telemetry provides:
- Client identity (app name, version, runtime)
- Anthropic request profiling (version headers, beta flags)
- Session tracing for debugging
- Persistent session traces to disk

**Action**: Add structured request profiling to LLM calls. Log session traces for debugging provider issues.

---

## Priority Matrix

| Priority | Feature | Impact | Effort |
|----------|---------|--------|--------|
| **P0** | Structured compaction with summaries | High | Medium |
| **P0** | Permission allow/deny/ask rules | High | Medium |
| **P1** | Pre/post tool-use hooks | High | Medium |
| **P1** | Config layering (user/project/local) | Medium | Small |
| **P1** | Prompt cache monitoring | Medium | Small |
| **P2** | Plugin manifest with tool extension | Medium | Large |
| **P2** | MCP client support | Medium | Large |
| **P2** | Sandbox/container detection | Medium | Medium |
| **P3** | Full slash command set | Low | Small |
| **P3** | Session tracing/telemetry | Low | Small |
