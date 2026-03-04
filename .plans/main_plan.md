# Taui Architecture — Complete Specification

## 1. Design Philosophy

Taui is not a chatbot. It is a **virtual engineering team** — a hierarchical multi-agent system that plans, delegates, executes, verifies, and commits code. The core principles:

- **Minimal core, maximal composability.** Each primitive (`llm`, `tools`, `agent`, `lsp`) works independently.
- **Streaming-first.** Every interface consumes `AsyncIterator[AgentEvent]`. No batch paths.
- **Explicit resource management.** Context is a finite resource. Load what you need, free what you don't, summarize what you might need later.
- **Hierarchy with accountability.** Parent agents delegate to minions. Minions return structured results in Boxes. Parents verify before accepting.
- **Policy as the single enforcement point.** Every action (tool call, git operation, file write) passes through policy evaluation. Nothing bypasses it.

---

## 2. Core Interface & User Interaction

### 2.1 Workspace Layout

A dedicated workspace with a main conversation view and a bottom panel showing agent activity, tool execution, and minion status.

### 2.2 User Steering

The user can inject a **steering message** at any time during agent execution:

- **Default target:** The root agent receives the message. It decides whether to:
  - Stop running children and change course
  - Pass the message to a specific running child
  - Absorb it into its own planning
- **Optional targeting:** The user can direct a message to a specific minion by ID/name
- **Mechanics:** Steering messages are injected as high-priority user messages. The targeted agent processes them on its next think cycle. If the agent is mid-tool-execution, the message waits until the current tool completes.

### 2.3 Autonomous Git

Git operations are policy-configurable per operation:

| Operation | Default Policy |
|---|---|
| `git status`, `git diff`, `git log` | `auto_approve` |
| `git add`, `git commit` | `confirm` |
| `git push`, `git rebase`, `git reset` | `confirm` |
| `git push --force` | `deny` |

Users can override any of these in their policy config. An agent granted `auto_approve` on commit can stage, commit, and manage branches without interruption.

---

## 3. The Tool Ecosystem

Taui organizes tools into **seven groups**. Each group represents a category of capability. The groups are extensible — users can add custom tools to existing groups or create entirely new groups.

### 3.1 Tool Groups

| Group | Purpose | Built-in Tools |
|---|---|---|
| **`read`** | Ingest code, files, and context | `read_file`, `glob`, `grep` |
| **`write`** | Output or modify code | `write_file`, `edit_file` |
| **`programmatic`** | Script execution, OS commands | `bash` |
| **`lsp`** | Language-aware code intelligence | `diagnostics`, `references`, `definition`, `symbols`, `hover`, `completions` (TBD) |
| **`git`** | Version control | `git_status`, `git_diff`, `git_add`, `git_commit`, `git_push`, `git_log`, etc. |
| **`plan`** | High-level reasoning and task decomposition | `plan` (produces structured task graph) |
| **`spawn`** | Agent hierarchy management | `spawn_minion`, `halt_minion`, `get_minion_status` |

### 3.2 Tool Contract

```python
class Tool(Protocol):
    name: str
    description: str
    group: str                    # which tool group this belongs to
    schema: dict[str, Any]        # JSON Schema for arguments

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult: ...
```

### 3.3 Extensibility

Tools follow a plugin model. Extension points:

- **File-based drop-ins** (MVP): Place a Python file in `~/.config/taui/tools/<group>/` implementing the `Tool` protocol.
- **Entry-point plugins** (post-MVP): Standard Python packaging with `[project.entry-points."taui.tools"]`.
- **New groups:** Drop-ins can declare a new `group` value. The registry auto-creates the group.

### 3.4 Tool Executor

The executor is the **single enforcement point** for all tool execution:

1. Resolve tool from registry
2. Validate arguments against JSON Schema
3. Evaluate policy (`auto_approve` / `confirm` / `deny`)
4. If `confirm`: pause, yield `ApprovalRequiredEvent`, wait for resolution
5. Execute with timeout (`asyncio.wait_for`)
6. Normalize errors into `ToolResult`
7. Attach metadata (duration, argument digest)

---

## 4. Context & Memory Management

Context is a finite, managed resource. Taui provides three mechanisms:

### 4.1 `load(path)` — Bring Into Context

The agent calls `load()` (via `read_file` or similar) to bring file content into the conversation. The session tracks what has been loaded.

### 4.2 `free(path)` — Remove From Context

The agent calls `free()` to **completely remove** a file's content from context. The content is deleted from the message history. A minimal breadcrumb remains: `"[freed: file.py — use load() to re-read]"`.

This is the agent proactively managing its own context window. Use case: after modifying `file.py` and verifying it with LSP, the agent frees it to make room for the next file.

### 4.3 `summarize(range)` — Condense a Conversation Branch

`summarize()` operates on a **range of conversation messages** (a "branch"). The selected messages are condensed into a compact summary that replaces them in context.

- **Scope:** A segment of the message history, identified by message range or a label (e.g., "the bug fix discussion").
- **Mechanism:** An LLM call (potentially a cheaper/faster model) generates the summary.
- **Minion branches:** Each minion operates on its own conversation branch. When a minion's Box is received by the parent, the parent can choose to summarize the minion's branch rather than keeping the full log.
- **User-initiated:** The user can also trigger summarization — e.g., after finishing a bug fix, summarize that branch before starting a new feature.

### 4.4 Automatic Compaction (Baseline)

Underneath, the existing token budget compaction runs as a safety net:

- **Soft limit (85%):** Drop oldest non-preserved messages
- **Hard limit (95%):** More aggressive trimming
- **Preserved:** Latest system message, latest user message, unresolved tool call/result pairs
- **Summary injection:** When messages are dropped, a system note is inserted

The hierarchy is: explicit `free()` and `summarize()` are preferred (agent-directed). Auto-compaction is the fallback (system-directed).

---

## 5. The Agentic Hierarchy

### 5.1 Agent Roles

Every agent instance (root or minion) has the same core loop: **think → act → observe**. The difference is scope and permissions.

**Root Agent (Hybrid):**
- Receives user requests directly
- Can do work itself (for simple tasks, it works alone)
- Can plan and spawn minions (for complex tasks, it delegates)
- Reviews minion Boxes and verifies results
- Responds to user steering messages

**Minions:**
- Receive a scoped task from their parent
- Execute using the tools available to them
- Can spawn their own sub-minions (up to configurable depth)
- Return a Box to their parent when done

### 5.2 Minion Model Tiers

The parent does not pick a specific model for each minion. Instead, the user pre-configures **model tiers**, and the parent assigns a tier to each task based on estimated complexity.

**Default Tiers:**

| Tier | Intended For | Example Model |
|---|---|---|
| `junior` | Boilerplate, formatting, simple edits | `gemini-flash`, `codex-mini` |
| `mid` | Standard implementation, refactoring | `claude-haiku`, `gpt-4.1-mini` |
| `senior` | Complex logic, architecture, debugging | `claude-opus`, `gpt-5` |

**Configuration:**

```toml
[minions.tiers.junior]
model = "copilot:gemini-flash"

[minions.tiers.mid]
model = "copilot:claude-haiku-4.5"

[minions.tiers.senior]
model = "copilot:claude-opus-4.5"

# Custom tiers
[minions.tiers.specialist]
model = "codex:gpt-5.1-codex-mini"
```

The parent's `plan` tool output specifies a tier for each task node. The system resolves the tier to a concrete model+provider at spawn time.

### 5.3 Configurable Depth

Minions can spawn sub-minions, controlled by policy:

```toml
[minions]
max_depth = 3          # default: 2
max_concurrent = 5     # max parallel minions at any level
```

Depth 0 = root agent. Depth 1 = direct minion. Depth 2 = sub-minion. And so on up to `max_depth`.

### 5.4 Spawn Interface

```python
# The spawn tool's arguments
{
    "task": "Implement the user registration endpoint",
    "tier": "mid",
    "tools_allowed": ["read", "write", "programmatic", "lsp"],  # tool groups
    "context_files": ["src/routes/auth.py", "src/models/user.py"],
    "owned_files": ["src/routes/auth.py", "src/models/user.py"],  # exclusive write access
    "dependencies": [],                    # task IDs this depends on
}
```

- **`owned_files`:** Files this minion has **exclusive write access** to. A minion may only write to files it owns. Multiple minions may read any file, but no two concurrently running minions may own the same file. The scheduler enforces this — see §6.3.

- **Fire-and-forget with monitoring:** The parent spawns and continues planning/working. It does not block.
- **Halt capability:** Parent can call `halt_minion(minion_id)` at any time. This cancels the minion's current work and retrieves its current state as a partial Box.
- **Status check:** Parent can call `get_minion_status(minion_id)` to see progress without halting.

### 5.5 Minion Isolation

Each minion gets:
- Its own conversation branch (separate message history)
- Its own session context (read tracking, loaded files)
- Access only to the tool groups specified in `tools_allowed`
- The model specified by its tier
- A scoped working directory (same workspace, but the minion's context is limited to the files it's given + what it discovers)
- **Exclusive ownership** of the files listed in `owned_files`

### 5.6 File Ownership

File ownership is the mechanism that prevents concurrent write conflicts between minions — and critically, prevents LSP from seeing inconsistent state across parallel edits.

**Rules:**

1. **Write-gating:** A minion's `edit_file` and `write_file` tools are restricted to its `owned_files` list. Writes to non-owned files are rejected by the tool executor (policy layer).
2. **Read is unrestricted:** Any minion can `read_file` or run LSP queries (`diagnostics`, `references`, `definition`) on any file, regardless of ownership.
3. **Ownership is exclusive:** No two **concurrently running** minions may own the same file. The DAG scheduler enforces this at spawn time (see §6.3).
4. **Glob ownership:** Ownership entries support globs (e.g., `"src/routes/*.py"`). Two globs that overlap are treated as conflicting.
5. **Ownership is declared, not discovered.** The parent declares `owned_files` at spawn time based on the plan. A minion cannot acquire ownership of new files at runtime — if it needs to create/modify an unexpected file, it must report this in its Box and let the parent handle it (or re-plan).

**Why this matters for LSP:**

Language servers maintain an in-memory model of the workspace. When two agents write to the same file concurrently, the LSP sees interleaved `didChange` notifications that corrupt its state — leading to phantom diagnostics, stale references, and invalid completions. File ownership ensures that at any point in time, each file has at most one writer, so the LSP's view stays consistent.

---

## 6. The Plan Tool & DAG Scheduling

### 6.1 The Plan Tool

The `plan` tool is how the root agent (or any parent) decomposes work. It outputs a **structured task graph** — a DAG (Directed Acyclic Graph) of tasks with explicit dependencies.

### 6.2 Task Graph Format

```python
@dataclass
class TaskNode:
    id: str                          # unique within this plan
    description: str                 # what this task accomplishes
    tier: str                        # "junior", "mid", "senior", or custom
    tools_required: list[str]        # tool groups needed
    context_files: list[str]         # files to preload
    owned_files: list[str]           # files this task has exclusive write access to
    dependencies: list[str]          # task IDs that must complete first
    estimated_complexity: str        # "trivial", "moderate", "complex"
    rationale: str                   # natural language: why this task, why this tier

@dataclass
class TaskGraph:
    goal: str                        # the overall objective
    nodes: list[TaskNode]            # the tasks
    execution_order: list[list[str]] # waves: [[parallel tasks], [next wave], ...]
    rationale: str                   # natural language: overall plan reasoning
```

### 6.3 DAG Scheduling

The system executes the task graph respecting dependencies **and file ownership constraints**:

1. **Wave 0:** All tasks with no dependencies run in parallel (up to `max_concurrent`), **provided their `owned_files` do not overlap**
2. **Wave 1:** Tasks whose dependencies are all complete run next, subject to the same ownership constraint
3. **Continue** until all tasks are done or a task fails

**File ownership conflict detection:**

Before spawning a task, the scheduler checks its `owned_files` against all currently running minions' `owned_files`. If any overlap is found (including glob expansion), the task is **held** until the conflicting minion completes and releases ownership. This means two tasks with no explicit `dependencies` between them will still be serialized if they own the same file.

The scheduler maintains a **file ownership table** — a map from file path (or glob pattern) to the minion ID that currently owns it. Entries are added at spawn time and removed when the minion's Box is received.

**Conflict at plan time vs. runtime:**

- **Plan-time validation:** When the `plan` tool generates the `execution_order` waves, it should detect ownership overlaps and place conflicting tasks in separate waves. This is advisory — it produces a better plan but is not the enforcement point.
- **Runtime enforcement:** The scheduler is the enforcement point. Even if the plan places two ownership-conflicting tasks in the same wave, the scheduler will hold one until the other completes.

If a task fails:
- The parent is notified via the Box (which includes error state)
- Ownership of the failed task's files is released
- The parent can re-plan, retry with a different tier, or absorb the task itself

### 6.4 Plan Visibility

The task graph is rendered to the user in the UI so they can see:
- What the agent is planning
- Which tasks are queued, running, completed, or failed
- The dependency structure
- Which model tier each task is assigned to

---

## 7. The Box — Structured Handoff

### 7.1 What Is a Box

When a minion completes (or is halted), it packages its work into a **Box** — a standardized handoff artifact returned to the parent.

### 7.2 Box Structure

```python
@dataclass
class Box:
    minion_id: str
    task_id: str                            # from the TaskGraph
    status: Literal["completed", "failed", "halted", "partial"]

    # What was done
    summary: str                            # natural language summary of work performed
    files_modified: list[FileChange]        # structured list of changes
    files_created: list[str]
    files_deleted: list[str]

    # Verification
    verification: VerificationResult | None  # LSP diagnostics, test results
    issues_encountered: list[str]            # problems hit during execution

    # Metrics
    usage: Usage                             # tokens consumed
    duration_ms: int                         # wall-clock time
    tool_calls_count: int                    # how many tool invocations

@dataclass
class FileChange:
    path: str
    diff: str                               # unified diff of changes
    summary: str                            # what was changed and why

@dataclass
class VerificationResult:
    diagnostics_clean: bool                 # LSP reports no errors
    tests_passed: bool | None               # if tests were run
    details: str                            # any specifics
```

### 7.3 Box Processing

When a parent receives a Box:

1. **Trace through logs** — the parent reads the summary and file diffs
2. **Verify via LSP** — the parent can run diagnostics on modified files to confirm correctness
3. **Accept or reject** — if verification passes, the task is marked complete. If not, the parent can:
   - Re-spawn a minion with corrective instructions
   - Fix it directly (hybrid mode)
   - Escalate to the user

### 7.4 Partial Boxes

If a minion is halted mid-execution, it returns a **partial Box** with `status: "halted"`. This contains whatever work was completed plus the current state, so the parent (or a replacement minion) can resume.

---

## 8. LSP Integration

### 8.1 Architecture

Taui includes a **full LSP client** that connects to standard language servers. This gives the agent the same code intelligence an IDE has.

### 8.2 LSP Tool Surface (TBD — Final List)

Candidates for the `lsp` tool group:

| Tool | LSP Method | Purpose |
|---|---|---|
| `diagnostics` | `textDocument/diagnostic` | Get errors, warnings, hints for a file |
| `references` | `textDocument/references` | Find all references to a symbol |
| `definition` | `textDocument/definition` | Go to definition |
| `symbols` | `textDocument/documentSymbol` | List symbols (classes, functions) in a file |
| `hover` | `textDocument/hover` | Get type info / documentation for a symbol |
| `completions` | `textDocument/completion` | Get completion candidates |

The exact set will be determined during implementation. At minimum: `diagnostics` (critical for verification) and `definition` + `references` (critical for safe refactoring).

### 8.3 Language Server Lifecycle (TBD)

To be determined during implementation. Options under consideration:
- Lazy start (on first use per language) with session-scoped lifetime
- Pre-configured eager start
- Dynamic start/stop based on resource pressure

### 8.4 LSP for Verification

The primary use of LSP in the agentic hierarchy:

1. **Self-check:** A minion runs `diagnostics` on files it modified before packaging its Box
2. **Parent review:** The parent runs `diagnostics` on files received in a Box before accepting
3. **Pre-commit gate:** Before an autonomous commit, LSP diagnostics must be clean (configurable)

**LSP and file ownership:** LSP reliability depends on file ownership (§5.6). Language servers track file state via `didOpen`/`didChange`/`didClose` notifications. If two minions write to the same file concurrently, the LSP's in-memory model diverges from disk — diagnostics become unreliable, references point to stale locations, and completions use wrong type information. The file ownership constraint (one writer per file at any time) guarantees the LSP sees a consistent, sequential stream of changes for every file.

---

## 9. Policy System

### 9.1 Policy Evaluation

Every tool call passes through policy. The policy is the **sole enforcement point** — no tool bypasses it.

**Evaluation order:**
1. `deny` list → immediately blocked
2. `confirm` list → paused, requires approval (from user or parent agent)
3. `auto_approve` → executes without interruption

### 9.2 Default Policy

```toml
[policy]
auto_approve = ["read_file", "glob", "grep", "diagnostics", "references",
                "definition", "symbols", "git_status", "git_diff", "git_log"]
confirm = ["edit_file", "write_file", "bash", "git_add", "git_commit", "git_push"]
deny = ["git_push_force", "git_reset_hard"]

[policy.bash]
restrict_workdir_to_workspace = true
allow_network = false
env_allowlist = ["PATH", "HOME", "LANG"]
max_output_bytes = 1048576        # 1 MB
default_timeout_sec = 120

[policy.git]
auto_commit = false               # set true to auto-approve commits
auto_push = false                 # set true to auto-approve pushes
```

### 9.3 Minion Policy Inheritance

Minions inherit the policy of their parent by default. The parent can further **restrict** (but not expand) a minion's policy when spawning it:

```python
{
    "task": "...",
    "tools_allowed": ["read", "write", "lsp"],    # no git, no bash
}
```

### 9.4 Non-Interactive Mode

In headless/CI mode, `confirm`-gated tools are treated as `deny` unless the policy explicitly sets them to `auto_approve`. No prompt means no approval.

---

## 10. Session & Persistence

### 10.1 Session Structure

Each agent (root or minion) has its own session:

```python
@dataclass
class Session:
    session_id: str
    parent_session_id: str | None     # None for root
    messages: list[Message]
    usage: SessionUsage
    read_attempts: dict[str, str]     # path → status
    active_minions: dict[str, MinionState]
    task_graph: TaskGraph | None      # current plan
```

### 10.2 Persistence

- **Storage:** SQLite at `~/.local/share/taui/sessions.db`
- **Root sessions** persist across restarts
- **Minion sessions** are ephemeral by default (retained only while parent needs them)
- **Advisory locking** prevents concurrent writer corruption

### 10.3 Conversation Branches

Sessions are **linear** for MVP (per ADR-0003). The `summarize()` tool operates on message ranges within a linear history. Full session branching (tree/fork) is deferred to post-MVP.

---

## 11. Implementation Phases

Building on the existing Phase 1 (project scaffold) and Phase 2 (multi-provider auth + chat REPL):

| Phase | What | Key Deliverables |
|---|---|---|
| **3a** | Tool system core | `tools/base.py`, `registry.py`, `executor.py`, policy enforcement |
| **3b** | Built-in tools | `read`, `edit`, `write`, `bash`, `glob`, `grep`, `git` tools |
| **3c** | Single agent loop | `agent/loop.py`, `session.py`, `events.py` — flat agent, no spawning |
| **4a** | Context management | `free()` tool, `summarize()` tool, integration with session |
| **4b** | Plan tool | Structured task graph generation, DAG representation |
| **4c** | Spawn system | `spawn_minion`, `halt_minion`, `get_minion_status`, Box handoff |
| **4d** | DAG scheduler | Wave-based execution, dependency resolution, concurrent minion management |
| **5** | LSP integration | LSP client, language server lifecycle, `diagnostics`/`references`/`definition` tools |
| **6a** | Headless CLI | `cli.py` consuming `AgentEvent` stream, JSON event output mode |
| **6b** | Textual TUI | `app.py` with conversation panel, agent activity view, plan visualization |
| **7** | Skills system | Skill loader, built-in skills, `~/.config/taui/skills/` drop-ins |

Phase 3 is designed with **spawn hooks** — the agent loop, session, and event types are structured so that Phase 4 (hierarchy) is a clean extension, not a rewrite.

---

## 12. Module Structure (Target)

```
taui/
├── __init__.py
├── __main__.py
├── cli.py                      # headless CLI
├── app.py                      # Textual TUI
│
├── config/
│   ├── settings.py             # global config, model selection
│   └── policies.py             # permission rules
│
├── auth/                       # [Phase 2 — exists]
│   ├── pkce.py
│   ├── copilot.py
│   ├── gemini.py
│   ├── antigravity.py
│   └── codex.py
│
├── llm/
│   ├── types.py                # Message, ToolCall, StreamEvent, Usage
│   ├── provider.py             # Provider protocol
│   ├── registry.py             # model routing
│   ├── stream.py               # streaming helpers
│   └── providers/
│       ├── copilot.py
│       ├── gemini.py
│       ├── antigravity.py
│       └── codex.py
│
├── tools/
│   ├── base.py                 # Tool protocol, ToolResult, ToolContext
│   ├── registry.py             # tool registry + group management
│   ├── executor.py             # policy + execution + timeout
│   └── builtins/
│       ├── read.py             # read_file, glob, grep
│       ├── write.py            # write_file, edit_file
│       ├── programmatic.py     # bash
│       ├── git.py              # git operations
│       ├── context.py          # free, summarize
│       ├── plan.py             # plan (task graph generation)
│       └── spawn.py            # spawn_minion, halt_minion, get_minion_status
│
├── lsp/
│   ├── client.py               # LSP client protocol implementation
│   ├── lifecycle.py            # server start/stop management
│   ├── registry.py             # language → server mapping
│   └── tools.py                # diagnostics, references, definition (Tool impls)
│
├── agent/
│   ├── loop.py                 # think → act → observe cycle
│   ├── session.py              # session state + persistence
│   ├── events.py               # AgentEvent types
│   ├── planner.py              # TaskGraph, TaskNode, DAG scheduling
│   ├── minion.py               # minion lifecycle, spawn/halt/status
│   └── box.py                  # Box, FileChange, VerificationResult
│
├── storage/
│   └── sqlite.py               # SQLite session store
│
└── skills/
    ├── loader.py               # skill discovery + activation
    └── builtins/
        └── ...
```

---

## 13. Key Invariants

These must hold at all times:

1. **Read-before-write guard.** `edit_file` and `write_file` require a prior successful `read_file` on that path.
2. **Policy is the sole gatekeeper.** No tool executes without policy evaluation. No exception.
3. **Boxes are the only handoff.** Minions communicate results to parents exclusively via Boxes. No side-channel.
4. **Context is finite.** `free()` and `summarize()` are not optional luxuries — they are core to the system's ability to handle large codebases.
5. **Minions cannot escalate privilege.** A minion's tool access is a subset of (never exceeds) its parent's policy.
6. **Depth is bounded.** `max_depth` is always enforced. A minion at max depth cannot spawn.
7. **Every tool call is logged.** Duration, arguments digest, result status — all captured for traceability.
8. **File ownership is exclusive.** No two concurrently running minions may own the same file. The scheduler enforces this at spawn time. A minion may only write to files it owns. Violation is a hard error, not a warning.

---

## 14. Open Considerations

1. **Summarize cost.** LLM-based summarization of conversation branches costs tokens and latency. Consider having minions self-summarize (they already have context) rather than requiring a separate LLM call.

2. **Box verification bottleneck.** If the parent serially verifies every Box via LSP, it becomes a bottleneck with many parallel minions. Minions should self-verify before packaging; the parent spot-checks.

3. **Cross-provider credentials.** Tiers can map to different providers. The auth layer must support concurrent multi-provider credentials with independent refresh cycles.

4. **DAG re-planning.** When a task fails, the parent may generate an entirely new TaskGraph or patch the existing one. Strategy TBD — patching is efficient but harder to reason about.

5. **Steering race conditions.** Halt must be cancellation-safe. A minion mid-write could leave partial changes. The halt mechanism must handle graceful cleanup.

6. **Context transfer to minions.** Whether minions load files fresh or receive pre-loaded content from the parent. Fresh is simpler; transfer is faster. Strategy TBD.

---

## 15. Spec-Driven Execution (Literate Programming Model)

### 15.1 Concept

Taui supports a **spec-driven interaction mode** inspired by literate programming. Instead of interpreting vague chat requests, agents execute against **living spec documents** — structured, natural-language-plus-code descriptions of what the system should do. The user writes clear specs; agents execute them and ask questions when something is ambiguous.

This is complementary to chat, not a replacement. Chat is for exploration. Specs are for anything that matters — where you want traceability, where "why was this decision made" matters, where code review should check against requirements.

The spec becomes the single source of truth. The code is the derived artifact.

### 15.2 Spec Format

Specs are Markdown files with conventions. They live in a configurable directory (default: `specs/`).

```markdown
<!-- filepath: specs/auth/registration.md -->
# User Registration

## Behavior
- Accept email + password via POST /api/register
- Validate email format (RFC 5322) and password strength (min 12 chars, 1 uppercase, 1 number)
- Hash password with argon2id, cost factor 3
- Store in `users` table, return 201 with user ID
- On duplicate email, return 409

## Constraints
- No external validation libraries — use stdlib `re`
- Must pass existing test suite in `tests/test_auth.py`

## Files
- `src/routes/auth.py` — endpoint handler
- `src/models/user.py` — User model
- `src/utils/validation.py` — validation helpers (new file)
```

### 15.3 Execution Loop

The agent loop in spec mode differs from chat mode:

```
load spec → parse requirements → generate clarifications →
wait for user answers → plan (TaskGraph mapped to spec sections) →
execute via minions → verify against spec → report compliance
```

Key difference: there is a **formalized question phase** before execution begins. The agent reads the spec, identifies ambiguities and gaps, and batches questions to the user. Execution starts only after clarifications are resolved.

### 15.4 Clarification Protocol

Agents ask structured questions rather than guessing:

```python
@dataclass
class Clarification:
    spec_ref: str          # "registration.md#Constraints"
    question: str          # "Should the 12-char minimum include or exclude whitespace?"
    options: list[str]     # suggested answers
    blocking: bool         # can we proceed without this?
```

The agent reads the spec, generates a batch of clarifications, the user answers them (updating the spec or answering inline), and then execution begins. This is fundamentally different from asking questions mid-execution.

### 15.5 Spec-Driven Verification

Instead of generic "does it compile?" verification, the Box includes **spec compliance**:

```python
@dataclass
class SpecVerification:
    spec_ref: str
    requirement: str                    # extracted from spec
    status: Literal["met", "unmet", "ambiguous"]
    evidence: str                       # how it was verified (test, LSP, inspection)
```

The parent doesn't just check "did LSP diagnostics pass" — it checks "did the minion satisfy every stated requirement in the spec section it was assigned."

### 15.6 Spec Amendments

The agent may discover during implementation that the spec is incomplete or contradictory. Instead of guessing, it proposes **spec amendments**:

```markdown
<!-- agent-proposed addition to specs/auth/registration.md -->
## Open Questions (Agent)
- Spec says "return 201 with user ID" but doesn't specify response body format.
  Proposed: `{"id": "uuid", "email": "string", "created_at": "iso8601"}`
- Spec says "must pass existing test suite" but `tests/test_auth.py` expects
  a `register_user()` function, not a route handler. Should tests be updated?
```

### 15.7 Spec Audit & Drift Detection

Over time, specs and code can drift. An agent can be asked to **audit** — read the current spec and the current code, report divergences. This enables specs to function as invariant documentation that persists alongside the code.

### 15.8 Spec Tool Group

A new `spec` tool group:

| Tool | Purpose |
|---|---|
| `parse_spec` | Extract requirements, constraints, file mappings from a spec document |
| `ask_clarification` | Batch structured questions to user before execution |
| `verify_spec` | Check implementation against spec requirements |
| `propose_spec_amendment` | Suggest spec changes based on implementation discoveries |
| `audit_spec` | Compare current code against spec, report drift |

### 15.9 Integration with Existing Architecture

The spec-driven model layers on top of the existing architecture without restructuring:

- **Tool system, policy, LSP, Boxes** — unchanged. These are execution primitives that are interaction-model-agnostic.
- **DAG scheduler** — maps naturally. Each `TaskNode` corresponds to a spec section. The spec itself provides the dependency structure (if "authentication" references "user model," there's a dependency).
- **Plan tool** — now decomposes a spec rather than a chat request. Task graph nodes map back to spec sections.
- **Minions** — receive spec-section-scoped tasks instead of chat-derived tasks.

### 15.10 Configuration

```toml
[spec]
spec_dir = "specs/"                  # where spec files live
format = "markdown"                  # markdown with conventions
ask_before_execute = true            # always run question phase first
update_specs_on_completion = true    # agent updates spec with implementation notes
```

### 15.11 Spec-Driven Dev as a Product Feature

Taui provides spec-driven development **to the user's project** — it is a core product capability, not just an internal methodology.

**Onboarding flow:** When a user first runs Taui on their project, it creates a `specs/` folder with starter markdown files. This is the project's spec workspace — the primary surface through which the user drives development.

**UI model:** The interface has two primary surfaces:

1. **Spec editor panel.** The user views and edits spec documents directly in the UI. Each spec section can spawn agents — the user selects a section (or the whole spec) and triggers execution. Agents are born from specs, not from chat messages.

2. **Agent chat panel.** A secondary panel for conversing with agents. The user can:
   - Chat with already-spawned agents (ask questions, steer, give feedback)
   - Spawn new agents ad-hoc via chat (the chat escape hatch from §15.11.3)
   - See agent status, progress, and Boxes as they complete

**The relationship:** Specs are the **source of work**. Chat is the **communication channel**. The spec editor is where you say "what to build." The chat panel is where you interact with the builders while they work.

**Lifecycle:**
1. User opens project in Taui → `specs/` folder exists (or is created)
2. User writes/edits specs in the spec editor
3. User triggers execution on a spec (or section)
4. Agents spawn, appear in the agent panel, execute against the spec
5. User can chat with running agents, steer, or let them finish
6. Agents return Boxes, spec is updated with completion status
7. User reviews, iterates on the spec, triggers next round

### 15.12 Limitations & Escape Hatches

1. **Spec quality is the bottleneck.** The model assumes the user can write clear specs. A **spec assistant mode** helps: the agent helps write the spec before executing it.
2. **Chat escape hatch.** Sometimes you just want to say "fix this bug" without writing a formal spec. Both modes coexist — chat for exploration, specs for production work.
3. **Granularity mismatch.** Some specs are too high-level, some too low-level. The spec parser must handle the full spectrum without rigid format requirements.
