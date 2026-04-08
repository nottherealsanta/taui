# Taui Architecture — Spec-First Unified Plan

## 1. Prime Goal

Taui is a **spec-driven agentic coding system**.

The spec tree is the primary product surface. Agents execute from spec nodes, verify against spec requirements, and report requirement-level compliance. Chat remains an escape hatch for exploration and urgent ad-hoc work, not the default execution path.

Core principles:

- **Spec-first execution.** Major work is always tied to a canonical `spec_ref`.
- **Minimal core, maximal composability.** Primitives (`llm`, `tools`, `agent`, `lsp`, `spec`) remain independently testable.
- **Streaming-first.** Interfaces consume `AsyncIterator[AgentEvent]`.
- **Explicit context management.** Agents load, free, and summarize context deliberately.
- **Hierarchy with accountability.** Parents delegate; minions return Boxes; parents verify before accept.
- **Policy as the single enforcement point.** No tool, write, or git operation bypasses policy.

---

## 2. Canonical Spec Tree Contract

All project specs live under `<project>/specs/`.

### 2.1 Root Node

The root is always `specs/_main.md` and must include:

- project title
- one-line project intent
- first-level child index (links)

### 2.2 Child Nodes (Recursive Rule)

A child node is either:

- file node: `specs/<node>.md`
- folder node: `specs/<node>/_main.md` - only level 1 children of root can be folders

Folder nodes recurse with the same contract.

### 2.3 Heading Depth = Tree Depth

Heading depth encodes traversal depth:

- `#` depth 1
- `##` depth 2
- `###` depth 3

### 2.4 Node Schema (Minimum)

Each node document includes:

- title
- one-line intent
- status: `draft | ready | in_progress | done | blocked`
- child index for non-leaf nodes
- optional dependencies by `spec_ref`
- acceptance criteria (required for executable leaves)

### 2.5 Leaf Node Termination

A leaf node terminates in exactly one of:

1. detailed implementation requirements (behavior, constraints, files, tests, acceptance)
2. explicit code anchors (`<file_path>:<line_range>`)

Examples:

- `taui/agent/loop.py:120-230`
- `taui/tools/executor.py:1-180`

---

## 3. Spec Reference and Traversal

### 3.1 Canonical `spec_ref`

Every executable task resolves to:

- `<spec_path>#<heading-anchor>`

Examples:

- `specs/_main.md#project-structure`
- `specs/agent/runtime.md#tool-execution`

### 3.2 Traversal Strategy

Traversal order:

1. tree edges (parent to child)
2. dependency edges (`depends_on`)

Traversal is deterministic for repeatable planning and replay.

### 3.3 Traceability Requirement

Everything maps back to `spec_ref`:

- TaskGraph nodes
- tool calls
- file changes
- verification/test evidence
- clarifications and amendments
- Box acceptance/rejection

---

## 4. Execution Model (Spec-First)

### 4.1 Entry Point

Execution starts from a selected spec node/subtree, not unconstrained chat.

### 4.2 Lifecycle

1. load spec subtree from selected `spec_ref`
2. parse requirements/constraints
3. generate clarifications
4. block on unresolved blocking clarifications
5. build TaskGraph mapped to spec sections
6. execute via root + minions
7. verify against spec requirements and acceptance
8. write status and evidence back to spec artifacts

### 4.3 Clarification Gate

For blocking ambiguity:

- no code writes for that node
- node remains `blocked`
- unresolved clarification is persisted in session/spec metadata

```python
@dataclass
class Clarification:
    spec_ref: str
    question: str
    options: list[str]
    blocking: bool
```

### 4.4 Spec-Driven Verification

Verification is requirement-level, not only compile/lint-level.

```python
@dataclass
class SpecVerification:
    spec_ref: str
    requirement: str
    status: Literal["met", "unmet", "ambiguous"]
    evidence: str
```

### 4.5 Amendment Protocol

If implementation and spec conflict:

- do not silently guess
- generate amendment proposal
- require explicit approval before mutation

Example amendment block:

```markdown
## Open Questions (Agent)
- Response body format for `201 Created` is unspecified.
  Proposed: `{"id": "uuid", "email": "string", "created_at": "iso8601"}`
```

Spec format example:

```markdown
<!-- filepath: specs/auth/registration.md -->
# User Registration

## Behavior
- Accept email + password via POST /api/register
- Validate email format and password strength
- Hash password with argon2id
- Store in `users` table, return 201 with user ID

## Constraints
- No external validation library
- Must pass `tests/test_auth.py`

## Files
- `src/routes/auth.py`
- `src/models/user.py`
- `src/utils/validation.py`
```

---

## 5. Core Interface & User Interaction

### 5.1 Workspace Layout

Primary surface is spec-first:

1. spec tree navigator/editor
2. execution graph mapped by `spec_ref`
3. agent stream + Box inspector
4. chat panel (secondary, steering + escape hatch)

### 5.2 User Steering

Users can inject steering messages at runtime:

- default target is root agent
- optional direct target by minion ID
- applied on next think cycle; if tool is running, message queues

### 5.3 Autonomous Git

Git policy defaults:

| Operation | Default Policy |
|---|---|
| `git status`, `git diff`, `git log` | `auto_approve` |
| `git add`, `git commit` | `confirm` |
| `git push`, `git rebase`, `git reset` | `confirm` |
| `git push --force` | `deny` |

---

## 6. The Tool Ecosystem

Taui organizes tools into **eight groups**.

### 6.1 Tool Groups

| Group | Purpose | Built-in Tools |
|---|---|---|
| `read` | Ingest files/context | `read_file`, `glob`, `grep` |
| `write` | Modify code | `write_file`, `edit_file` |
| `programmatic` | Script/OS execution | `bash` |
| `lsp` | Language intelligence | `diagnostics`, `references`, `definition`, `symbols`, `hover`, `completions` |
| `git` | Version control | `git_status`, `git_diff`, `git_add`, `git_commit`, `git_push`, `git_log` |
| `plan` | Task decomposition | `plan` |
| `spawn` | Agent lifecycle | `spawn_minion`, `halt_minion`, `get_minion_status` |
| `spec` | Spec-first execution | `parse_spec`, `ask_clarification`, `verify_spec`, `propose_spec_amendment`, `audit_spec` |

### 6.2 Tool Contract

```python
class Tool(Protocol):
    name: str
    description: str
    group: str
    schema: dict[str, Any]

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult: ...
```

### 6.3 Extensibility

- File drop-ins: `~/.config/taui/tools/<group>/`
- Entry-point plugins (post-MVP): `[project.entry-points."taui.tools"]`
- New groups allowed via registration

### 6.4 Tool Executor (Enforcement Point)

1. resolve tool
2. validate schema
3. evaluate policy
4. request approval when needed
5. execute with timeout
6. normalize errors
7. attach metadata (duration, digest)

---

## 7. Context & Memory Management

### 7.1 `load(path)`

Bring file content into active conversation context.

### 7.2 `free(path)`

Remove file content from context while leaving a breadcrumb:

- `"[freed: file.py - use load() to re-read]"`

### 7.3 `summarize(range)`

Condense message ranges or completed minion branches to preserve decision context with lower token footprint.

### 7.4 Automatic Compaction (Fallback)

- soft limit: 85%
- hard limit: 95%
- preserve latest system/user and unresolved tool pairs

Order of preference: explicit `free()/summarize()` first, auto-compaction second.

---

## 8. Agentic Hierarchy

### 8.1 Root Agent

- accepts user intent and selected `spec_ref`
- builds/updates TaskGraph
- spawns minions with scoped ownership and tier
- verifies Boxes against requirement compliance
- updates spec node statuses

### 8.2 Minion Agents

- execute scoped `spec_ref` work only
- respect `tools_allowed` and `owned_files`
- may spawn sub-minions within `max_depth`
- return Box only

### 8.3 Model Tiers

| Tier | Intended For | Example Model |
|---|---|---|
| `junior` | boilerplate/simple edits | `gemini-flash`, `codex-mini` |
| `mid` | standard implementation | `claude-haiku`, `gpt-4.1-mini` |
| `senior` | complex logic/architecture | `claude-opus`, `gpt-5` |

```toml
[minions.tiers.junior]
model = "copilot:gemini-flash"

[minions.tiers.mid]
model = "copilot:claude-haiku-4.5"

[minions.tiers.senior]
model = "copilot:claude-opus-4.5"

[minions.tiers.specialist]
model = "codex:gpt-5.1-codex-mini"
```

### 8.4 Depth and Concurrency

```toml
[minions]
max_depth = 3
max_concurrent = 5
```

### 8.5 Spawn Interface

```python
{
    "task": "Implement registration endpoint",
    "spec_ref": "specs/auth/registration.md#behavior",
    "tier": "mid",
    "tools_allowed": ["read", "write", "programmatic", "lsp", "spec"],
    "context_files": ["src/routes/auth.py", "src/models/user.py"],
    "owned_files": ["src/routes/auth.py", "src/models/user.py"],
    "dependencies": [],
}
```

### 8.6 File Ownership Rules

1. write tools are restricted to `owned_files`
2. read/LSP may span all files
3. concurrent ownership overlap is forbidden
4. glob overlaps are treated as conflicts
5. ownership is declared at spawn, not discovered silently

---

## 9. TaskGraph & DAG Scheduling

### 9.1 Task Graph Contract

```python
@dataclass
class TaskNode:
    id: str
    spec_ref: str
    description: str
    tier: str
    tools_required: list[str]
    context_files: list[str]
    owned_files: list[str]
    dependencies: list[str]
    estimated_complexity: str
    rationale: str

@dataclass
class TaskGraph:
    goal: str
    nodes: list[TaskNode]
    execution_order: list[list[str]]
    rationale: str
```

### 9.2 Scheduling Rules

- dependency-ready tasks run in parallel when ownership is non-conflicting
- ownership conflicts serialize even within same wave
- runtime scheduler is the final enforcement point
- scheduler preserves deterministic spec-order where possible

### 9.3 Plan Visibility

UI exposes:

- queued/running/completed/failed tasks
- dependencies
- tier assignment
- `spec_ref` lineage

---

## 10. The Box - Structured Handoff

### 10.1 Box Contract

```python
@dataclass
class Box:
    minion_id: str
    task_id: str
    spec_ref: str
    status: Literal["completed", "failed", "halted", "partial"]

    summary: str
    files_modified: list[FileChange]
    files_created: list[str]
    files_deleted: list[str]

    verification: VerificationResult | None
    spec_compliance: list[SpecVerification]
    issues_encountered: list[str]
    proposed_amendments: list[str]

    usage: Usage
    duration_ms: int
    tool_calls_count: int

@dataclass
class FileChange:
    path: str
    diff: str
    summary: str

@dataclass
class VerificationResult:
    diagnostics_clean: bool
    tests_passed: bool | None
    details: str
```

### 10.2 Parent Processing

1. inspect summary + diffs
2. verify diagnostics/tests
3. evaluate requirement-level compliance
4. accept/reject and mark task status

### 10.3 Partial Boxes

Halted minions return `status: "halted"` with resumable state.

---

## 11. LSP Integration

### 11.1 Architecture

Taui includes an LSP client so agents use IDE-equivalent code intelligence.

### 11.2 LSP Tool Surface

| Tool | LSP Method | Purpose |
|---|---|---|
| `diagnostics` | `textDocument/diagnostic` | compile-time and semantic issues |
| `references` | `textDocument/references` | safe refactor coverage |
| `definition` | `textDocument/definition` | symbol navigation |
| `symbols` | `textDocument/documentSymbol` | structure discovery |
| `hover` | `textDocument/hover` | type/doc inspection |
| `completions` | `textDocument/completion` | completion candidates |

### 11.3 Lifecycle

Lifecycle can be lazy-start or eager-start per language; final strategy selected during implementation.

### 11.4 Verification Path

1. minion self-check before Box
2. parent check before acceptance
3. optional pre-commit diagnostic gate

File ownership is required for reliable LSP state.

---

## 12. Policy System

### 12.1 Evaluation

Order: `deny` -> `confirm` -> `auto_approve`.

### 12.2 Default Policy

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
max_output_bytes = 1048576
default_timeout_sec = 120

[policy.git]
auto_commit = false
auto_push = false
```

### 12.3 Inheritance

Minions inherit parent policy and may only be further restricted.

### 12.4 Non-Interactive Mode

`confirm` behaves as `deny` unless explicitly elevated to `auto_approve`.

---

## 13. Session & Persistence

### 13.1 Session Structure

```python
@dataclass
class Session:
    session_id: str
    parent_session_id: str | None
    messages: list[Message]
    usage: SessionUsage
    read_attempts: dict[str, str]
    active_minions: dict[str, MinionState]
    task_graph: TaskGraph | None
```

### 13.2 Persisted Artifacts

Persist:

- spec index and content hashes
- canonical `spec_ref` map
- TaskGraph snapshots
- Box history
- node status transitions
- clarification/amendment history

### 13.3 Storage

- SQLite: `~/.local/share/taui/sessions.db`
- root sessions resumable
- minion sessions ephemeral by default
- locking required for safe concurrent access

---

## 14. Implementation Roadmap

Roadmap uses **A-E as canonical ordering**, with prior numeric phase detail merged.

### Phase A: Spec Tree Foundation (highest priority)

- enforce `specs/_main.md` contract
- recursive spec tree model and parser
- heading-depth traversal and `spec_ref` resolver
- spec index, hash tracking, and node status model

### Phase B: Spec Toolchain

- implement `parse_spec`, `ask_clarification`, `verify_spec`, `propose_spec_amendment`, `audit_spec`
- blocking clarification gate and amendment workflow
- requirement extraction and acceptance-criteria indexing

### Phase C: Execution Binding

- TaskGraph nodes mapped 1:1 to spec sections
- scheduler enforces dependency and ownership constraints
- Box generation includes `spec_ref` and requirement compliance
- integrate prior Phase 3 tool-system outcomes into spec-execution path

### Phase D: Agentic Scale

- spawn/halt/status APIs and minion orchestration
- tiered routing and bounded-depth sub-minion support
- deterministic subtree parallelism

### Phase E: Verification and UX

- LSP-backed verification gates
- spec-first interface layout (spec navigator primary)
- compliance-centric summaries and audit views

Legacy phase mapping preserved as sub-deliverables:

- `3a` tool-system core, `3b` built-in tools, `3c` single-agent loop
- `4a` context management, `4b` plan tool, `4c` spawn system, `4d` DAG scheduler
- `5` LSP integration, `6a` headless CLI, `6b` interface shell, `7` skills system

Status note: `3a` is already implemented (`.plans/phase3a_tools.md`, dated 2026-03-06).

---

## 15. Module Structure (Target)

```
taui/
├── __init__.py
├── __main__.py
├── cli.py
├── app.py
│
├── config/
│   ├── settings.py
│   └── policies.py
│
├── auth/
│   ├── pkce.py
│   ├── copilot.py
│   ├── gemini.py
│   ├── antigravity.py
│   └── codex.py
│
├── llm/
│   ├── types.py
│   ├── provider.py
│   ├── registry.py
│   ├── stream.py
│   └── providers/
│       ├── copilot.py
│       ├── gemini.py
│       ├── antigravity.py
│       └── codex.py
│
├── tools/
│   ├── base.py
│   ├── registry.py
│   ├── executor.py
│   └── builtins/
│       ├── read.py
│       ├── write.py
│       ├── programmatic.py
│       ├── git.py
│       ├── context.py
│       ├── plan.py
│       └── spawn.py
│
├── spec/
│   ├── parser.py
│   ├── refs.py
│   ├── clarifications.py
│   ├── verify.py
│   ├── amend.py
│   ├── audit.py
│   └── tools.py
│
├── lsp/
│   ├── client.py
│   ├── lifecycle.py
│   ├── registry.py
│   └── tools.py
│
├── agent/
│   ├── loop.py
│   ├── session.py
│   ├── events.py
│   ├── planner.py
│   ├── minion.py
│   └── box.py
│
├── storage/
│   └── sqlite.py
│
└── skills/
    ├── loader.py
    └── builtins/
        └── ...

specs/
├── _main.md
└── ...
```

---

## 16. Key Invariants

1. No major coding task without a target `spec_ref`.
2. No silent spec drift; conflicts go through amendment flow.
3. Policy is the sole enforcement gate for tool execution.
4. Boxes are the only parent/minion handoff artifact.
5. Completion requires requirement-level verification evidence.
6. File ownership is exclusive for concurrent writers.
7. Minions cannot escalate privileges beyond parent policy.
8. Context is finite and must be explicitly managed.
9. Depth/concurrency bounds are always enforced.
10. Tool calls are logged with arguments digest, duration, and outcome.

---

## 17. Open Considerations

1. Summarization cost and when to trigger automatic branch summarization.
2. Parent verification bottlenecks with many parallel Boxes.
3. Multi-provider credential lifecycle across tiered routing.
4. Re-planning strategy after partial/failed task waves.
5. Halt safety when cancellation intersects active writes.
6. Parent-to-minion context transfer strategy (fresh load vs transfer).
7. Strictness of spec parser for high-level vs low-level node granularity.
