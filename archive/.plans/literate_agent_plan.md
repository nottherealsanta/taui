# Literate Programming Architecture for Taui

Transform Taui into a literate programming environment where specs are the primary interface to code. Hard-linked code references (functions, variables, files) are resolved via semantic resolution, viewable inline in spec nodes, and editable through slash commands. A three-tier agent hierarchy (Prime → Root → Minion) provides autonomous and steered collaboration.

Two interaction modes for the user: editing the spec directly, and tasking/talking to agents. Both modes are equal in power and compatible in outcome. Both converge on the same artifact — the spec tree — which is the single source of truth linking intent to implementation. The goal is not to replace code with prose. The goal is to make the spec the human-facing semantic layer through which users inspect, steer, and safely edit code.

---

## Guiding Principles

1. **Spec is canonical.** The spec tree is the human-facing artifact. Semantic resolution augments the spec but does not replace it. The system never forces users to operate only in code coordinates.

2. **Two equal modes.** Editing a spec node by hand and sending a task to an agent must produce compatible state transitions against the same spec structure.

3. **Code through the spec.** When a spec references code, the UI renders implementation context through the spec — symbol previews, file previews, editable variable widgets, backlinks — so users do not have to leave the spec context.

4. **Agents are not a chat island.** They work on spec-scoped tasks and return spec-linked diffs, questions, and proposals. Agent output is always grounded in the spec tree.

5. **Inline over panes.** Prefer showing semantic ref state inline where possible. Avoid making the user bounce between multiple heavy panels to see the value of a bound variable.

---

## Phase 1: Spec Model and Semantic Reference Foundations

The spec model layer and semantic resolution layer. Everything else depends on having a rich, typed reference system and a fast resolver.

### 1.1 Reference Taxonomy

Replace the current opaque `code_refs` with four distinct reference kinds:

| Ref Kind | Metadata Tag | Points To | Editability |
|----------|-------------|-----------|-------------|
| `line_ref` | `{{line_ref: ...}}` | Concrete file span (path + line range) | Read-only |
| `symbol_ref` | `{{symbol_ref: ...}}` | A language symbol (function, method, class, constant, type) | Read-only |
| `variable_ref` | `{{variable_ref: ...}}` | A symbol intended for value inspection and possibly inline editing | Conditionally writable |
| `file_ref` | `{{file_ref: ...}}` | A file as a whole | Read-only |

All four are stored as spec node metadata using the existing `{{key: value}}` inline syntax. The markdown format remains human-editable:

```md
- Tune page background
    {{variable_ref: `app/src/theme.ts#theme.backgroundColor`}}
    {{verification: pnpm test}}

- Improve hero palette
    {{symbol_ref: `app/src/lib/theme.ts#ThemeTokens.heroBackground`}}
    {{variable_ref: `app/src/lib/theme.ts#ThemeTokens.heroBackground`}}
    {{file_ref: `app/src/lib/theme.ts`}}
```

### 1.2 Canonical Identity

References must not be stored only as line numbers because lines drift. The canonical identity for semantic references is stable and semantic-first:

```python
@dataclass
class SemanticRef:
    file_path: str              # Relative to project root
    symbol_path: str | None     # e.g. "ThemeTokens.heroBackground"
    ref_kind: str               # "line_ref" | "symbol_ref" | "variable_ref" | "file_ref"
    language: str | None        # "python" | "typescript" | "rust" | "css" (needed for resolution)
    edit_policy: str | None     # "replace_literal" | "replace_property" | "replace_enum" | None (read-only)
    line_start: int | None      # Derived resolution data, not source of truth
    line_end: int | None        # Derived resolution data, not source of truth
```

Line numbers are derived resolution data. The file path + symbol path is the source of truth.

### 1.3 Semantic Resolver

The backend exposes a resolver abstraction. In v1 this is backed by a tree-sitter symbol indexer. It can be upgraded to LSP later for deeper capabilities (refactoring, type-aware resolution).

The resolver accepts a `SemanticRef` and returns:

```python
@dataclass
class ResolvedRef:
    file_path: str               # Resolved absolute or relative path
    line_start: int              # Current line range (1-based)
    line_end: int                # Current line range (1-based)
    column_start: int | None     # Column if available
    column_end: int | None
    preview_snippet: str         # Source text at location
    symbol_kind: str | None      # "function" | "class" | "variable" | "constant" | etc.
    symbol_metadata: dict        # Name, parent, scope, etc.
    writable: bool               # Whether the spec can safely edit this target
    edit_strategy: str | None    # "replace_literal" | "replace_property" | "replace_enum" | None
    confidence: str              # "high" | "medium" | "low"
    fallback_reason: str | None  # If not writable, why (e.g., "computed expression", "multiple definitions")
    diagnostic: str              # "resolved" | "resolved_warning" | "unresolved" | "stale" | "ambiguous"
```

### 1.4 Editability Policy

Not every symbol should be editable from the spec editor. v1 supports write access only for targets with a safe, narrow mutation shape.

Writable in v1:
1. Literal constant assignments (`MAX_RETRIES = 3`)
2. Theme tokens (`--color-bg: #1a1a2e`)
3. Configuration values (single-source scalars)
4. Single-source scalar values with one unambiguous definition

Read-only in v1:
1. Computed expressions
2. Values derived through runtime logic
3. Symbols with multiple candidate definitions
4. Targets whose mutation would require structural refactoring

If the resolver cannot assign a safe edit strategy, the ref remains read-only. The system still shows preview and jump-to-code affordances for read-only refs.

### 1.5 Edit Strategy Classification

Each writable variable ref declares an edit strategy:

| Strategy | Description | Example |
|----------|-------------|---------|
| `replace_literal` | Replace a literal token in an assignment | `MAX_RETRIES = 3` → `MAX_RETRIES = 5` |
| `replace_property` | Replace an object property literal | `{ bg: "#fff" }` → `{ bg: "#000" }` |
| `replace_enum` | Replace an enum-like constant value | `MODE = "dev"` → `MODE = "prod"` |

If the resolver cannot assign one of these strategies, the ref is read-only.

### 1.6 Diagnostic Status

Every semantic ref has a resolution status tracked as an enum:

| Status | Meaning |
|--------|---------|
| `resolved` | Target found, current, no issues |
| `resolved_warning` | Target found but may have drifted or is in an unusual state |
| `unresolved` | Target not found in the codebase |
| `stale` | Target existed at last index but file has changed since |
| `ambiguous` | Multiple candidate definitions found |

Diagnostics surface in the UI (inline warning indicators on spec nodes) and constrain agent behavior (agents must not claim success on unresolved refs).

### 1.7 Tree-sitter Symbol Indexer

New module `taui/symbols/` with `indexer.py`, `models.py`, `db.py`.

Tree-sitter is chosen for v1 because it is fast, offline, multi-language, and requires no server lifecycle management. LSP is the upgrade path for deeper capabilities (find references, backlinks, type-aware resolution).

The indexer extracts:
- Functions (including methods)
- Classes and types
- Variables and constants
- Imports
- CSS custom properties

`SymbolEntry` dataclass:

```python
@dataclass
class SymbolEntry:
    id: str
    name: str               # "SpecNode", "MAX_RETRIES", "--color-bg"
    kind: str               # "function" | "class" | "variable" | "constant" | "import" | "css_property"
    file_path: str          # Relative to project root
    line_start: int         # 1-based
    line_end: int           # 1-based, inclusive
    scope: str              # "module" | "class:ClassName" | "function:func_name"
    parent_symbol: str | None
    language: str           # "python" | "typescript" | "rust" | "css"
    value_preview: str | None  # For variables: "3", "'#1a1a2e'"
    content_hash: str       # Hash of source file at index time
```

Storage: SQLite table `symbols` in existing SpecDB:

```sql
CREATE TABLE symbols (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    line_start  INTEGER NOT NULL,
    line_end    INTEGER NOT NULL,
    scope       TEXT NOT NULL,
    parent_symbol TEXT,
    language    TEXT NOT NULL,
    value_preview TEXT,
    content_hash TEXT NOT NULL
);
CREATE INDEX idx_symbols_name ON symbols(name);
CREATE INDEX idx_symbols_file ON symbols(file_path);
CREATE INDEX idx_symbols_kind ON symbols(kind);
```

Indexing lifecycle:
- Full scan on project open
- Incremental re-index on file change via filesystem watch (fsevents on macOS, inotify on Linux)
- Content hash per file to skip unchanged files
- Index rebuilt from scratch if tree-sitter grammar version changes

Languages: Python, TypeScript/JavaScript, Rust, CSS.

### 1.8 Reverse Indexes

Taui must maintain reverse indexes so the system can answer:

1. Which spec nodes reference this file?
2. Which spec nodes reference this symbol?
3. Which nodes discuss editable values in a given subsystem?
4. Which agent tasks are currently attached to the referenced artifact?

Implementation: SQLite tables mapping `(file_path → spec_node_id[])` and `(symbol_path → spec_node_id[])`, rebuilt on spec sync and updated incrementally on ref insertion/removal:

```sql
CREATE TABLE ref_index (
    id          TEXT PRIMARY KEY,
    ref_kind    TEXT NOT NULL,      -- "line_ref" | "symbol_ref" | "variable_ref" | "file_ref"
    file_path   TEXT NOT NULL,      -- target file
    symbol_path TEXT,               -- target symbol (null for file_ref/line_ref)
    spec_node_id TEXT NOT NULL,     -- owning spec node
    diagnostic  TEXT NOT NULL DEFAULT 'resolved'
);
CREATE INDEX idx_ref_by_file ON ref_index(file_path);
CREATE INDEX idx_ref_by_symbol ON ref_index(symbol_path);
CREATE INDEX idx_ref_by_node ON ref_index(spec_node_id);
```

### 1.9 RPC Methods

```
refs/search
  params: { query: string, kind?: string, scope?: string, limit?: int }
  returns: SymbolEntry[]

refs/resolve
  params: { ref: SemanticRef }
  returns: ResolvedRef

refs/getDefinition
  params: { file_path: string, symbol_name: string }
  returns: { symbol: SymbolEntry, source_text: string, context_before: string, context_after: string }

refs/updateValue
  params: { file_path: string, symbol_name: string, new_value: string }
  returns: { success: bool, old_value: string, new_value: string, line: int }
  (rejects if edit_strategy is null or ref is not writable)

refs/backlinks
  params: { file_path: string, symbol_name?: string }
  returns: { spec_nodes: SpecNodeSummary[], count: int }

refs/validate
  params: { spec_ref?: string }
  returns: { results: { ref: SemanticRef, diagnostic: string, detail: string }[] }
  (validates all refs on a node or subtree; if spec_ref omitted, validates all)
```

Files touched:
- New: `taui/symbols/__init__.py`, `taui/symbols/indexer.py`, `taui/symbols/models.py`, `taui/symbols/db.py`
- Modified: `taui/specs/db.py` (symbols + ref_index tables), `taui/specs/models.py` (SemanticRef, ResolvedRef), `taui/server/handlers.py` (register RPCs), `taui/server/state.py` (hold indexer instance)

---

## Phase 2: Literate Code View and Editor Affordances

The spec editor becomes an active authoring environment. Spec nodes with semantic refs show code inline. Users can insert, inspect, and manipulate refs without losing markdown legibility.

### 2.1 Inline Renderers

Semantic refs render inline as attached widgets inside the spec editor. Each ref kind gets a distinct renderer:

| Ref Kind | Inline Rendering | Affordances |
|----------|-----------------|-------------|
| `symbol_ref` | Symbol pill with current signature preview | Click to jump to definition, hover for full signature |
| `variable_ref` | Variable pill with current value and edit affordance | Inline edit control (see 2.3), click to see source context |
| `file_ref` | File pill with path | Click to open file preview |
| `line_ref` | Line range badge | Click to jump to source |
| (any, stale/unresolved) | Warning state with diagnostic indicator | Tooltip explains why unresolved |

These renderings preserve the underlying markdown model while making the editor feel semantic.

### 2.2 Code Preview

When a spec node has semantic refs, the tree row renders a collapsed code preview below the spec text:

- Symbol name and kind (e.g., "function handle_login")
- Syntax-highlighted snippet (~10 lines)
- Visual indicator of total line count if truncated

Clicking the preview expands to a full Monaco editor inline (read-write for writable refs, read-only otherwise). This Monaco instance is scoped to the referenced symbol or line range, not the entire file. Multiple refs on a node render as stacked previews, each independently collapsible.

### 2.3 Inline Variable Editing

For editable variable refs, the UI provides type-appropriate editing controls:

| Value Type | Control |
|-----------|---------|
| String | Text field |
| Numeric | Numeric input with step controls |
| Color | Color picker (for color tokens, CSS custom properties) |
| Boolean | Toggle switch |
| Enum-like | Dropdown with known values |

Editing flow:
1. Current value displayed inline in the variable pill
2. User clicks to activate the type-appropriate edit control
3. Preview of the affected file and span shown alongside the control
4. If the change is high-impact (determined by policy), a confirmation dialog appears
5. On confirmation, backend writes via `refs/updateValue`
6. Immediate refresh of the resolved value and preview

### 2.4 Bidirectional Sync

When source files change (via agent, minion, or external editor):

```
spec/codeRefChanged
  params: { spec_ref: string, ref: SemanticRef, old_hash: string, new_hash: string }
```

Frontend re-fetches the code preview for affected nodes. If the user has an inline Monaco editor open on that ref, the editor shows "file changed externally" with options to reload or keep local changes.

When the user edits a ref target (changing the referenced symbol or file), the backend re-resolves the ref and returns the new diagnostic status.

### 2.5 Backlinks

The spec editor shows which spec nodes reference the same code artifact. Backlinks surface as:

- A "Referenced by" section under code previews showing other spec nodes that point to the same file or symbol
- A BacklinksPanel (existing component) enhanced to show semantic ref backlinks
- Navigation from a code artifact back to all spec nodes that discuss it

### 2.6 Spec-Centric Navigation

Users can navigate from a spec node to:
1. Bound code symbol (jump to definition)
2. Bound file (open file preview)
3. Backlinks from code to specs (which other specs reference this artifact)
4. Active agent task working on the same node or reference

The UI keeps the spec visible as the main context during navigation. Code opens in inline previews or side panels, not by replacing the spec view.

### 2.7 Frontend Components

New components:
- `CodePreview.svelte` — collapsed/expanded code view inside TreeRow
- `RefPill.svelte` — inline pill renderer for each ref kind (symbol, variable, file, line) with appropriate affordances
- `VariableEditor.svelte` — type-appropriate inline edit control (text field, color picker, numeric input, toggle, dropdown)

Modifications:
- `TreeRow.svelte` — renders RefPill for each semantic ref, renders CodePreview for expandable refs
- `MonacoEditor.svelte` — inline mode (no chrome, compact dimensions)
- `BacklinksPanel.svelte` — enhanced with semantic ref backlinks

New service: `app/src/lib/services/refService.ts`
- Wraps `refs/search`, `refs/resolve`, `refs/updateValue`, `refs/backlinks`, `refs/validate` RPC calls
- Caches resolved refs client-side with invalidation on `spec/codeRefChanged`

---

## Phase 3: Slash Commands and Insertion

### 3.1 Slash Command Framework

Typing `/` at the beginning of a line or after whitespace in the spec editor opens a dropdown menu anchored to the cursor. The dropdown filters as the user types.

Built-in slash commands:

| Command | Action |
|---------|--------|
| `/ref: variable` | Opens symbol picker filtered to variables, inserts `{{variable_ref: ...}}` |
| `/ref: symbol` | Opens symbol picker for all symbols, inserts `{{symbol_ref: ...}}` |
| `/ref: file` | Opens file picker, inserts `{{file_ref: ...}}` |
| `/ref: spec` | Opens spec node picker, inserts a spec cross-reference link |
| `/status <value>` | Sets the node's status metadata |
| `/run <command>` | Executes a verification command |
| `/ask <team-or-agent>` | Sends a question to an agent or team |
| `/delegate <team-or-agent>` | Delegates a task to an agent or team |
| `/red <message>` | Steers the red root agent |
| `/blue <message>` | Steers the blue root agent |
| ... | (one per active agent color) |

The command registry is extensible. New commands can be added without modifying the dropdown component.

### 3.2 Dropdown Search

The symbol picker for `/ref: variable` supports:

1. Fuzzy search by symbol name
2. Filtering by file or subsystem
3. Display of symbol kind and path
4. Indication of whether the target is editable (writable vs read-only)
5. Preview of the symbol before insertion (source snippet)

The dropdown must feel like code completion — fast, not a modal workflow.

### 3.3 Variable Reference Insertion Flow

1. User types `/ref: variable`
2. Taui opens picker backed by `refs/search` with `kind: "variable"`
3. Picker shows variables with current values: `MAX_RETRIES = 3`, `--color-bg = #1a1a2e`
4. Editability indicator: writable variables show an edit icon, read-only ones show a lock icon
5. User selects a variable
6. Taui inserts `{{variable_ref: `taui/config/settings.py#MAX_RETRIES`}}` into the spec node
7. Taui renders a variable pill with current value inline
8. If writable, clicking the value opens the type-appropriate edit control
9. User edits → backend writes → immediate refresh

### 3.4 Color-Steering Slash Commands

When root agents are active, `/color <message>` routes a steering message to the root agent owning that color channel:

- `/red fix the login timeout issue` → looks up root agent with color "red" → calls `agent/steer`
- If no agent has that color → error: "No active agent with color red"
- Autocomplete for `/` dynamically includes active agent colors

Routing policy:
1. Team color names a Root-owned channel
2. Steering message targets the Root first
3. Root may pass it to Minions or reinterpret it into subtasks
4. Direct fan-out to all Minions is optional, not the default

### 3.5 Frontend Components

New:
- `SlashCommandMenu.svelte` — dropdown triggered by `/`, extensible command registry
- `SymbolPicker.svelte` — fuzzy search over symbols with editability indicators and preview

Modifications:
- `InlineEditor.svelte` — listen for `/` at valid positions, open SlashCommandMenu
- `MessageBar.svelte` — parse `/color <msg>` for agent steering, parse `/ask`/`/delegate` for agent routing

---

## Phase 4: Three-Tier Agent Architecture

### 4.1 Agent Tier Model

Extend `AgentRunner` with tier-related fields:

```python
class AgentRunner:
    # existing fields...
    tier: Literal["prime", "root", "minion"]
    color: str | None = None            # For root agents
    depth: int = 0                      # For minions (0 = direct child of root)
    max_concurrent_minions: int = 3
    parent_agent_id: str | None = None  # Existing, now enforced
    spec_scope: str | None = None       # spec_ref of the branch this agent owns
    capability_profile: str = "full"    # "router" (Prime) | "coordinator" (Root) | "full" (Minion)
    interruption_permissions: str = "none"  # "all" (Root) | "escalation_only" (Prime) | "none" (Minion)
```

Configuration in `taui/config/settings.py`:

```python
AGENT_COLOR_PALETTE = ["red", "blue", "green", "orange", "purple", "cyan", "yellow", "pink"]
MAX_MINION_DEPTH = 2
MAX_CONCURRENT_MINIONS = 3
PRIME_WATCH_INTERVAL_SEC = 5
PRIME_MODEL = "gemini-flash"
ROOT_MODEL = "codex"
MINION_MODEL = "codex"
```

### 4.2 Task Model

Introduce a formal task model separate from plain messages. Every agent task is attached to a spec node:

```python
@dataclass
class AgentTask:
    task_id: str
    parent_task_id: str | None      # For delegated subtasks
    owner_agent_id: str
    target_spec_ref: str            # Spec node this task operates on
    related_refs: list[SemanticRef]  # Semantic refs relevant to this task
    status: str                     # "pending" | "in_progress" | "done" | "blocked" | "failed"
    artifacts: list[str]            # File paths modified, created, etc.
    result: TaskResult | None       # Proposal, diff, question, or completion summary
```

```python
@dataclass
class TaskResult:
    kind: str                  # "spec_patch" | "code_edit" | "question" | "warning" | "proposal"
    spec_patch: dict | None    # Proposed spec node changes
    code_edits: list | None    # Proposed code edits linked to variable refs
    question: str | None       # Question with affected node context
    warning: str | None        # Warning with unresolved semantic ref context
    linked_spec_ref: str | None
    linked_semantic_refs: list[SemanticRef] | None
```

DB table:

```sql
CREATE TABLE agent_tasks (
    task_id         TEXT PRIMARY KEY,
    parent_task_id  TEXT,
    owner_agent_id  TEXT NOT NULL,
    target_spec_ref TEXT NOT NULL,
    related_refs    TEXT,           -- JSON array of SemanticRef
    status          TEXT NOT NULL DEFAULT 'pending',
    artifacts       TEXT,           -- JSON array of file paths
    result_kind     TEXT,
    result_data     TEXT,           -- JSON serialized TaskResult
    created_at      REAL NOT NULL,
    completed_at    REAL
);
CREATE INDEX idx_tasks_by_agent ON agent_tasks(owner_agent_id);
CREATE INDEX idx_tasks_by_spec ON agent_tasks(target_spec_ref);
CREATE INDEX idx_tasks_by_parent ON agent_tasks(parent_task_id);
```

### 4.3 Prime Agent (Singleton)

Prime is the main user-facing conversational agent and the single coherent conversation surface. It is mostly a router and synthesizer, not the main worker.

Lifecycle (hybrid):
1. On session start, Prime initializes in dormant state
2. Lightweight watcher runs on `PRIME_WATCH_INTERVAL_SEC`, checking spec files for content hash changes
3. When changes detected, Prime collects diffs (before/after of modified spec nodes)
4. Prime activates: sends diffs to its LLM with project-wide system prompt
5. Prime produces one of:
   - A suggestion for the user (displayed as notification/toast)
   - A task delegation to a new or existing root agent
   - Nothing (changes insignificant)
6. Returns to dormant state

Prime model strategy: use a fast/cheap model (e.g., Gemini Flash) for diff monitoring. Escalate to a stronger model when fully activating for task planning.

Prime capabilities:
- Sees all spec diffs since last activation
- Sees summarized status from all Root agents
- Can spawn/assign Root agents to spec branches
- Cannot directly modify code or specs (delegates)
- Maintains a running summary of project state (persisted in DB)
- Presents agent outputs as spec diffs, semantic-ref changes, and linked code diffs

Prime system prompt includes:
- Project overview (from `specs/_main.md` top-level nodes)
- List of active Root agents and their assigned branches
- Summary of recent changes (diffs that triggered activation)
- Available actions: suggest to user, spawn root, steer existing root

RPC methods:

```
prime/status
  params: {}
  returns: { state: "dormant" | "active", last_activation: timestamp, pending_suggestions: Suggestion[] }

prime/activate
  params: {}
  returns: { activated: bool, reason: string }

prime/configure
  params: { watch_interval?: int, auto_activate?: bool, model?: string }
  returns: { config: PrimeConfig }
```

### 4.4 Root Agents (Team Leaders)

A Root agent is a team lead responsible for a task domain or spec-scoped workstream.

Responsibilities:
1. Own a task assignment from Prime
2. Coordinate Minions
3. Hold a team color identity in the UI
4. Surface interruptions to the user when clarification is needed
5. Aggregate Minion outputs into coherent proposals or diffs

Creation flow:
1. User says "launch agent on specs/auth.md#login-flow" → `agent/launch` with `tier: "root"`
2. AgentManager assigns next available color from palette
3. Root starts, receives branch context as system prompt
4. Colored dot appears on tree row for that spec branch

Color assignment:
- Colors drawn from `AGENT_COLOR_PALETTE` in order
- Overflow: numeric suffix (red-2, blue-2)
- Users can rename/recolor via `agent/configure`
- Colors are routing handles and UI identity, not permission boundaries

Root agent capabilities:
- Scoped to its assigned spec branch (can read entire tree, can only modify its branch)
- Can spawn minions for sub-tasks
- Can interrupt user with questions, clarifications, proposals, warnings, status escalations, and steering prompts
- Receives steer messages via `/color <msg>` or `agent/steer`

Root system prompt includes:
- Assigned spec branch (full detail)
- Parent spec nodes (context)
- Sibling branches (parallel work awareness)
- Available tools
- Instructions for when to ask questions vs proceed autonomously

Limits:
- Max `MAX_CONCURRENT_MINIONS` active minions (default: 3)
- Cannot modify specs outside its assigned branch
- Cannot directly communicate with other root agents (goes through Prime)

### 4.5 Minions (Workers)

Minions execute subtasks, use tools, and return outputs to their parent.

Creation flow:
1. Root (or parent minion) calls `spawn_minion(task, spec_ref?)`
2. AgentManager creates AgentRunner with `tier: "minion"`, `depth: parent.depth + 1`
3. Depth check: rejected if `depth > MAX_MINION_DEPTH`
4. Minion starts with narrow task context

Minion capabilities:
- Full access to builtin tools (read, edit, write, bash, glob, grep)
- Access to spec-tree tools (read/update nodes within parent's locked branch)
- Can spawn sub-minions if depth allows
- Cannot interrupt the user directly — outputs flow through the Root unless explicitly promoted
- Cannot ask user questions directly — must escalate to parent

Lifecycle:
1. Receives task → runs think-tool loop (max 50 turns)
2. On completion → emits `minionCompleted` event to parent
3. Parent receives result summary → incorporates into reasoning
4. Minion runner terminated and cleaned up

Result propagation:
- Completion event: `{ minion_id, task, result_summary, files_modified, errors }`
- Parent receives as system message injected into conversation

### 4.6 Interruption Model

Root agents can interrupt the user. The interruption model supports six classes:

| Class | Description | Example |
|-------|-------------|---------|
| `question` | Blocking question requiring answer | "Should I use OAuth or SAML?" |
| `clarification` | Non-blocking clarification request | "Do you mean the old or new auth module?" |
| `proposal` | Proposed change awaiting accept/reject | "Proposing: refactor login to use async" |
| `warning` | High-risk warning | "This change will break 3 tests" |
| `status_escalation` | Task blocked or stuck | "Can't proceed — missing dependency" |
| `steering_prompt` | Suggesting a direction change | "Consider splitting this into two tasks" |

Every interruption carries a structured payload:

```python
@dataclass
class Interruption:
    id: str
    source_agent_id: str
    team_color: str
    kind: str                           # One of the six classes above
    message: str
    linked_spec_ref: str | None         # Spec node this is about
    linked_semantic_refs: list[SemanticRef] | None
    urgency: str                        # "blocking" | "high" | "normal" | "low"
    suggested_actions: list[str] | None # e.g., ["Accept", "Reject", "Dismiss"]
    created_at: float
```

Interruptions are visible but bounded. The user can dismiss, snooze, or answer them. Rate-limiting or queuing prevents notification spam.

### 4.7 Agent Coordination

Spec locking:
- Root agent locks its assigned branch on start (`lockChanged` notification)
- Minions inherit parent's lock
- Other root agents cannot modify locked branches
- User always has priority over locks — user edits go through, agent is notified of conflict

Conflict resolution:
- Overlapping branch requests → Prime mediates
- Options: queue, merge into existing task list, or force-assign

Hierarchy rules:
1. Prime can launch and steer Root agents
2. Root agents can launch and steer Minions
3. Minions can spawn additional Minions only if depth and policy allow
4. Root agents are the only non-Prime agents allowed to interrupt the user directly
5. Prime sees summarized status from all Roots

Tool access stratification:
- Prime: no tools (pure reasoning)
- Root: spec-tree tools + read-only code tools
- Minion: full tool access

### 4.8 Agent Session Extensions

Each agent session tracks:

```python
# Extended fields on AgentRunner / agent_sessions table
role: str                    # "prime" | "root" | "minion"
team_color: str | None       # For roots; inherited channel for minions
parent_agent_id: str | None
hierarchy_depth: int
capability_profile: str      # "router" | "coordinator" | "full"
spec_scope: str | None       # spec_ref of owned branch
interruption_permissions: str # "all" | "escalation_only" | "none"
```

### 4.9 New RPC Methods

```
agent/spawnMinion
  params: { parent_agent_id: string, task: string, spec_ref?: string }
  returns: { minion_id: string, depth: int }

agent/configure
  params: { agent_id: string, color?: string, name?: string, max_minions?: int }
  returns: { agent: AgentInfo }

agent/getHierarchy
  params: {}
  returns: { prime: AgentInfo, roots: AgentInfo[], minions: { [root_id]: AgentInfo[] } }

agent/getTaskTree
  params: { spec_ref?: string, agent_id?: string }
  returns: { tasks: AgentTask[] }

agent/respondToInterruption
  params: { interruption_id: string, action: string, answer?: string }
  returns: { acknowledged: bool }
```

New notifications:

```
agent/minionCompleted
  params: { parent_agent_id, minion_id, task, result_summary, files_modified, duration_ms }

agent/tierInfo
  params: { agent_id, tier, color, depth, parent_agent_id }

agent/interruption
  params: Interruption payload (see 4.6)
```

---

## Phase 5: Convergence — Shared Interaction Model

The critical design requirement: manual editing and agent tasking must converge on the same spec-linked model of change.

### 5.1 Convergence Rule

The following six actions must produce compatible state transitions against the spec graph:

1. User edits a spec node by hand
2. User inserts a semantic ref with a slash command
3. User asks Prime to update a part of the project
4. Prime delegates to Root
5. Root delegates to Minions
6. Agents return diffs or questions

All materialize as updates or proposals against the spec graph and its attached references.

### 5.2 Diff Model

Prime presents agent work to the user through three linked diff types:

1. **Spec diffs** — changes to spec node content, status, or metadata
2. **Semantic ref changes** — new refs added, refs invalidated, ref diagnostics changed
3. **Linked code diffs** — code edits derived from or linked to the spec changes

The spec stays central. Even when code is edited, Prime shows the change through its spec linkage.

### 5.3 Proposal Model

Agents do not silently rewrite everything. In many cases they produce proposals linked to the affected node and semantic refs:

```python
@dataclass
class Proposal:
    id: str
    source_agent_id: str
    target_spec_ref: str
    linked_semantic_refs: list[SemanticRef]
    spec_patch: dict | None         # Proposed spec node changes
    code_edits: list[dict] | None   # Proposed code edits linked to variable refs
    status: str                     # "pending" | "accepted" | "rejected" | "modified"
```

The user can accept, modify, or reject proposals. Accepted proposals are applied atomically.

### 5.4 Shared Response Types

Backend responses from agent work are typed around spec-linked outcomes:

| Response Type | Content |
|--------------|---------|
| `proposed_spec_patch` | Spec node changes with rationale |
| `proposed_code_edit` | Code edit linked to a variable ref with before/after |
| `question_with_context` | Question with affected spec node and semantic refs |
| `warning_with_ref` | Warning about an unresolved or ambiguous semantic ref |

---

## Phase 6: UI Integration

### 6.1 Agent Color System in Tree

Tree rows within a root agent's spec branch show a colored dot:
- Assigned node: solid dot
- Descendant nodes: faded dot (same hue, lower opacity)
- Hover: tooltip with agent name, task summary, state
- Click: opens/focuses AgentDetailPanel for that agent

Minions not shown in tree directly — they appear only in AgentDetailPanel.

### 6.2 AgentDetailPanel Enhancements

- Header: agent name, color badge, tier badge (Prime/Root/Minion)
- Root agents: section showing active minions as indented sub-list with task, state, duration
- Prime: last activation time, pending suggestions, watched branches

### 6.3 Prime as Conversation Surface

Prime is the main conversation surface. Root and Minion activity usually appears as structured status under Prime. The user primarily talks to Prime.

Prime notification panel:
- Toast: "Prime: You changed the auth spec. Launch a root agent to update the implementation?"
- Actions: Accept (launches root agent), Dismiss, Configure
- Notification history accessible from bell icon

### 6.4 Agent Overview Panel

New `AgentOverviewPanel.svelte` showing full hierarchy:

```
Prime (dormant)
├── Red — specs/auth.md#login-flow (running, 2 minions)
│   ├── minion-1: "update password validation" (thinking)
│   └── minion-2: "add rate limiting tests" (done ✓)
├── Blue — specs/billing.md#stripe-integration (blocked, question pending)
└── Green — specs/ui.md#theme-system (idle, 1 queued task)
```

Click to focus/subscribe. Right-click for stop, steer, reassign. Visual state indicators.

### 6.5 Interruption UI

Interruptions from Root agents are prioritized and categorized:

| Priority | Category | UI Treatment |
|----------|----------|-------------|
| 1 | Blocking question | Modal overlay (existing QuestionOverlay) |
| 2 | High-risk warning | Prominent toast with action buttons |
| 3 | Proposal awaiting confirmation | Toast or inline indicator on affected spec node |
| 4 | Status escalation | Toast |
| 5 | Informational update | Subtle notification |

Each interruption links back to its spec node and semantic refs.

### 6.6 MessageBar Agent Integration

- Autocomplete after `/` includes active agent colors
- `/ask <team>` and `/delegate <team>` supported
- Task queue indicator per agent
- Shift+Enter: queue additional task to agent on current spec branch

### 6.7 Spec Node Extensions

Each spec node gains richer attached metadata visible in the UI:

- Semantic refs (rendered as pills)
- Editable ref descriptors (writable indicator)
- Ref diagnostics (warning/error indicators)
- Backlinks count or summary
- Active agent tasks (colored dot, task count)

---

## Safety and Policy

### V1 Safety Rules

1. Variable-ref editing is allowed only for targets with a declared safe edit strategy
2. Unresolved or ambiguous refs are read-only — no inline editing allowed
3. Agents must not claim success on unresolved refs
4. Minion spawn depth is bounded by `MAX_MINION_DEPTH`
5. User interruptions from Root agents are rate-limited or queued
6. Team colors are routing labels, not authorization boundaries

### Edit Strategy Enforcement

If the resolver cannot assign one of `replace_literal`, `replace_property`, or `replace_enum`, the ref remains read-only. The `refs/updateValue` RPC rejects edits to refs without a safe strategy.

---

## V1 Boundaries

Include in v1:
1. Semantic refs for symbols, files, and variables with four distinct ref kinds
2. Tree-sitter-backed resolution (LSP upgrade path for later)
3. Safe writable variable refs for literals and tokens
4. Prime, Root, and Minion roles with formal task model
5. Root interruptions with six classes and structured payloads
6. Team-color steering commands with Root-first routing

Exclude from v1:
1. Arbitrary AST rewriting through the spec editor
2. Unrestricted direct Minion interruptions to the user
3. Universal editability for all symbol kinds
4. Complex multi-user collaboration semantics
5. Full semantic refactoring guarantees
6. MCP tool integration, multi-project specs, external editor plugins

---

## Risks

### Risk 1: Overpromising Editability
If the product implies any code can be edited from the spec, users hit brittle cases. Mitigation: clearly distinguish writable refs from inspect-only refs with visual indicators and strict policy enforcement.

### Risk 2: Agent Message Flood
If color steering or Minion fan-out is too direct, the user gets flooded. Mitigation: Root aggregates Minion outputs. Direct fan-out to all Minions is opt-in, not default.

### Risk 3: Ref Drift
Code moves. Semantic refs become stale or ambiguous. Mitigation: diagnostic status tracking (5 states), reverse indexes, validation API, and visual warning indicators are required, not optional.

### Risk 4: Chat and Spec Divergence
If agents do substantial work without grounding it in spec nodes and semantic refs, the system splits into two inconsistent worlds. Mitigation: all agent tasks are attached to spec nodes via the Task model. The proposal model forces changes to be spec-linked.

---

## Incremental Delivery

### Phase 1: Semantic Reference Foundations
Deliver: reference taxonomy, canonical identity, resolver contract, tree-sitter indexer, reverse indexes, read-only resolution, diagnostic status tracking.
Success: a node can reference a symbol semantically, the UI can preview it, stale/unresolved states are visible.

### Phase 2: Spec Editor Affordances
Deliver: inline renderers (pills), code preview, backlinks, spec-centric navigation, bidirectional sync.
Success: user can see code through the spec and navigate between specs and code.

### Phase 3: Slash Commands and Writable Refs
Deliver: slash command infrastructure, `/ref: variable/symbol/file/spec`, dropdown search, insertion, safe editability detection, inline value editing controls, type-specific editors, confirmation for high-impact changes.
Success: user can insert semantic refs without manual typing, edit a background color or config value from the spec editor, underlying code changes correctly, unsafe refs are blocked.

### Phase 4: Prime, Root, Minion Roles
Deliver: tier metadata, task model, Root-owned team colors, Prime as router/synthesizer, delegation flow, interruption model.
Success: Prime delegates to Roots, Roots delegate to Minions, task ownership is visible and traceable.

### Phase 5: Convergence
Deliver: shared state model between edits and agent actions, diff model (spec + ref + code), proposal model with accept/reject, Prime presenting agent outputs as spec-linked diffs.
Success: user experiences one coherent system instead of separate spec and chat modes.

### Phase 6: UI Integration and Polish
Deliver: agent colors in tree, Prime conversation surface, agent overview panel, interruption UI with prioritization, MessageBar agent routing, spec node extensions.
Success: all agent and editing interactions are visually unified in the spec tree.

---

## Verification

### Spec System
1. Semantic refs round-trip through parse, storage, and markdown writeback
2. Reverse indexes remain consistent after edits
3. Stale and unresolved refs produce correct diagnostic status

### Resolver
1. Symbol search returns stable targets
2. Variable refs resolve to one safe span when editable
3. Ambiguous or computed targets fall back to read-only with fallback reason

### UI
1. Slash commands open the correct picker
2. Inserted refs render as the correct pill type
3. Editable variable refs can be changed inline with type-appropriate controls
4. Non-editable refs are clearly marked with lock icon and tooltip

### Agent
1. Prime can launch Root agents and present their outputs as spec diffs
2. Root can launch Minions and aggregate their outputs
3. `/red` and similar routing target the correct Root channel first
4. Root interruptions surface with spec-linked context and urgency
5. Agent outputs remain attached to tasks and spec nodes through the Task model

### Convergence
1. A manual spec edit and an agent-produced spec edit produce the same data model state
2. Proposals can be accepted, modified, or rejected
3. Prime shows spec diffs, semantic-ref changes, and linked code diffs as a unified view
