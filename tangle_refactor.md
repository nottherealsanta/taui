# Tangle Refactor — Complete Plan

## Overview

Move all existing code to `archive/`, then port and clean every module into a new codebase. The central concept changes from **spec** to **tangle** — a literate-programming-style document where prose and code references are interwoven as the primary unit of work.

**Stack:** unchanged. Svelte 5 + Tauri + Python/FastAPI + WebSocket JSON-RPC + SQLite.

**UI:** visually the same. Obsidian-like three-column layout. Left nav, center editor, right agent pane. **Stateless** — all persistent state lives in the backend DB. UI is a renderer that survives page refresh.

**Approach:** port-and-clean. Copy from archive module by module, renaming and redesigning as we go. No greenfield mystery — the archive is the reference.

---

## Phase 0: Archive

Move everything into `archive/` at the repo root.

### What moves

```
app/              → archive/app/
taui/             → archive/taui/
tests/            → archive/tests/
notes/            → archive/notes/
.plans/           → archive/.plans/
pyproject.toml    → archive/pyproject.toml
```

### What stays at root

```
.git/
.gitignore
.vscode/
AGENTS.md
```

### Post-archive root structure

```
archive/              # frozen reference
app/                  # new frontend (created during Phase 2)
taui/                 # new backend (created during Phase 1)
pyproject.toml        # new project config
```

---

## Phase 1: New Python Backend — `taui/`

Port the Python backend module by module. Rename `spec` → `tangle` everywhere. Redesign the tangle data model.

### 1.1 Project Config

Create new `pyproject.toml` at root. Same dependencies, same entry point, same metadata. Just clean.

Reference: `archive/pyproject.toml`

### 1.2 Module Map (archive → new)

| Archive module | New module | Changes |
|---|---|---|
| `taui/__init__.py` | `taui/__init__.py` | Same |
| `taui/__main__.py` | `taui/__main__.py` | `SpecDB` → `TangleDB`, `specs` → `tangles` |
| `taui/log_config.py` | `taui/log_config.py` | Port as-is |
| `taui/auth/` | `taui/auth/` | Port as-is (pkce, copilot, gemini, antigravity, codex) |
| `taui/config/` | `taui/config/` | Port as-is (settings, policies, auth_config) |
| `taui/llm/` | `taui/llm/` | Port as-is (types) |
| `taui/llms/` | `taui/llms/` | Port as-is (base, copilot, gemini, antigravity, codex) |
| `taui/lsp/` | `taui/lsp/` | Port as-is (client, manager, types) |
| `taui/plugins/` | `taui/plugins/` | Port as-is (models, registry) |
| `taui/skills/` | `taui/skills/` | Port as-is (installer, loader, registry) |
| `taui/symbols/` | `taui/symbols/` | Port as-is (db, indexer, models, resolver) |
| `taui/history/` | **Removed** | Merged into project-local `.taui.db` — see §1.6 |
| `taui/commands/` | `taui/commands/` | Port as-is (builtins, registry) |
| `taui/server/` | `taui/server/` | Rename spec → tangle in handlers; add UI state RPC — see §1.4, §1.7 |
| `taui/agent/` | `taui/agent/` | Rename spec → tangle references |
| `taui/specs/` | **`taui/tangle/`** | **Full redesign** — see §1.3 |

### 1.3 The Tangle Module — `taui/tangle/`

This is the core redesign. The current `taui/specs/` has: `db.py` (1391 lines), `service.py` (610 lines), `sync.py` (611 lines), `writer.py` (252 lines), `markdown.py` (372 lines), `models.py` (110 lines), `errors.py`, `verification.py`, `taskgraph.py`.

#### 1.3.1 What Is a Tangle

A **tangle** is a markdown document in the literate programming tradition. It interweaves:

- **Prose** — natural language describing intent, behavior, constraints, rationale
- **Code references** — explicit links to source code (`file_path:function_name` or `file_path:line_range`)
- **Dependencies** — links to other tangles via standard markdown links (`[name](tangles/path.md)` or `tangles/path.md#anchor`)
- **Status** — lifecycle state of the document (`draft`, `ready`, `active`, `done`, `archived`)

A tangle is **not** a spec in the traditional requirements sense. It is a living document that evolves alongside the code it describes. The code is the derived artifact; the tangle is the source of truth.

#### 1.3.2 Tangle Document Format

Frontmatter is **minimal by design**. Only `title` and `last_updated` are required. Everything else — code refs, dependencies, test refs, status, sections — is body content. The tangle-making tool's system prompt guides the agent to produce well-structured body content, but the **format itself enforces almost nothing**.

```markdown
---
title: User Registration
last_updated: 2026-04-07
---

# User Registration

The registration flow accepts email and password, validates input,
hashes the password, and persists a new user record.

## Behavior

- Accept `POST /api/register` with `{email, password}`
- Validate email format per RFC 5322 → `src/utils/validation.py:validate_email`
- Enforce password strength: min 12 chars, 1 uppercase, 1 digit
- Hash with argon2id (cost factor 3) → `src/routes/auth.py:register_handler:45-52`
- Insert into `users` table → `src/models/user.py:User.create`
- Return `201` with `{id, email, created_at}`

## Constraints

- No external validation libraries — stdlib `re` only
- Must pass `tests/test_auth.py` → `tests/test_auth.py:test_register_success`

## Dependencies

- [Data Layer](tangles/domains/data-layer.md) — user model and database operations
- [Rate Limiting](tangles/features/rate-limiting.md) — TBD, blocked

## Open Questions

- Should rate limiting apply to registration?
```

**Why minimal frontmatter:**

The previous spec format pushed structure into YAML frontmatter (status, owners, refs, test_refs, depends_on, tags). This made the format rigid and opinionated. Instead:

- The **tangle-making tool's system prompt** defines what sections and references an agent should produce. This prompt is the default "template" for tangle structure.
- The **user can edit this prompt** to change what tangles look like in their project. A game studio might want different sections than a SaaS backend team.
- The **parser** extracts code refs and tangle links from the body using pattern matching (the `→` notation, standard markdown links, heading-level conventions). It doesn't require them to be in frontmatter.

#### 1.3.3 What the Parser Extracts from Body Content

The parser reads the markdown body and extracts structured data without requiring it in frontmatter:

| Pattern | What it extracts | Example |
|---|---|---|
| `` `file:symbol` `` or `→ file:symbol` | Code reference | `src/auth.py:register_handler` |
| `` `file:line-range` `` or `→ file:line-range` | Code reference (line range) | `src/auth.py:45-52` |
| `[name](tangles/path.md)` | Tangle link (markdown link) | `[Data Layer](tangles/domains/data-layer.md)` |
| `tangles/path.md` or `tangles/path.md#anchor` | Tangle link (bare path) | `tangles/domains/auth.md#behavior` |

All paths are **relative to the project root** — the directory where taui was started. If taui starts in `/home/user/myproject`, then `src/auth.py` means `/home/user/myproject/src/auth.py` and `tangles/auth.md` means `/home/user/myproject/tangles/auth.md`.

#### 1.3.4 Tangle Directory Convention

```
<project>/
├── tangles/                # created when taui starts, if not present
│   ├── index.md            # root tangle — project overview
│   ├── .taui.db            # project-local DB (gitignored)
│   ├── domains/
│   │   ├── auth.md
│   │   └── data-layer.md
│   ├── features/
│   │   ├── user-registration.md
│   │   └── login.md
│   └── decisions/
│       └── argon2-over-bcrypt.md
├── src/                    # actual source code
└── tests/
```

The `index.md` replaces `_main.md` / `main.md`. It is the entry point.

The directory structure inside `tangles/` is entirely user-defined. `domains/`, `features/`, `decisions/` are the default prompt's suggestion, not a requirement. Users can organize however they want.

#### 1.3.5 New Data Models — `taui/tangle/models.py`

```python
@dataclass(slots=True)
class TangleFile:
    id: int
    rel_path: str             # relative to project root (e.g. "tangles/auth.md")
    content_hash: str
    mtime_ns: int
    title: str                # from frontmatter
    last_updated: str         # from frontmatter (ISO date string)
    last_seen: float

@dataclass(slots=True)
class TangleRef:
    """A code reference found in a tangle document body."""
    file_path: str            # source file path (relative to project root)
    target: str               # function name, line range, or symbol
    context: str              # the prose sentence containing this ref
    line_in_tangle: int       # line number in the tangle .md file

@dataclass(slots=True)
class TangleLink:
    """A link between two tangle documents."""
    source_path: str          # the tangle containing the link
    target_path: str          # the tangle being linked to
    link_type: str            # "markdown_link" | "bare_path"

@dataclass(slots=True)
class TangleNode:
    """A section within a tangle document (heading-based)."""
    id: str                   # stable id
    tangle_path: str          # which tangle file (relative to project root)
    heading: str              # heading text
    depth: int                # heading level (1-6)
    anchor: str               # slugified heading
    body: str                 # content under this heading
    refs: list[TangleRef]     # code refs found in this section
    line_start: int
    line_end: int

@dataclass(slots=True)
class TangleDetail:
    """Full detail of a tangle document."""
    file: TangleFile
    nodes: list[TangleNode]
    refs: list[TangleRef]
    links: list[TangleLink]
    frontmatter: dict[str, Any]   # raw frontmatter (title + last_updated + anything user adds)
```

Compared to archive: `SpecNode` had `spec_ref`, `code_refs` as flat strings, `collapsed`, `status`, `verification`, `depends_on`, `related_to` baked into the model. The new model is leaner — `TangleFile` only has `title` and `last_updated` from frontmatter. Everything else is extracted from body content into `TangleRef` and `TangleLink`.

#### 1.3.6 Module Files — `taui/tangle/`

| File | Purpose | Archive reference |
|---|---|---|
| `models.py` | Data models (above) | `archive/taui/specs/models.py` |
| `db.py` | SQLite operations (all tables in one DB) | `archive/taui/specs/db.py` — simplified schema |
| `parser.py` | Parse tangle markdown → models, extract refs/links from body | `archive/taui/specs/markdown.py` + `sync.py` |
| `writer.py` | Write models → tangle markdown | `archive/taui/specs/writer.py` |
| `service.py` | High-level API (CRUD, sync, search) | `archive/taui/specs/service.py` |
| `sync.py` | Filesystem ↔ DB sync | `archive/taui/specs/sync.py` — simplified |
| `refs.py` | Code reference extraction and resolution | New — pattern matching for `file:symbol` and `file:line_range` |
| `errors.py` | Error types | `archive/taui/specs/errors.py` |
| `verification.py` | Tangle compliance checking | `archive/taui/specs/verification.py` |

**Dropped:** `taskgraph.py` moves to `taui/agent/planner.py` where it belongs.

#### 1.3.7 Database Schema — `taui/tangle/db.py`

Single database file: `<project>/tangles/.taui.db` (gitignored).

This DB holds **runtime and derived data**: tangle index, agent sessions, message history, tool call logs. No more `~/.local/share/taui/` for project data. The `~/.taui/` directory is only for global config (auth tokens, provider credentials).

UI settings and prompts live in `<project>/.taui/settings.json` — a human-readable file the user can optionally git-track.

```sql
-- Tangle tables
CREATE TABLE tangle_files (
    id INTEGER PRIMARY KEY,
    rel_path TEXT UNIQUE NOT NULL,       -- relative to project root
    content_hash TEXT NOT NULL,
    mtime_ns INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',       -- from frontmatter
    last_updated TEXT NOT NULL DEFAULT '',-- from frontmatter
    last_seen REAL NOT NULL
);

CREATE TABLE tangle_nodes (
    id TEXT PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES tangle_files(id),
    heading TEXT NOT NULL,
    depth INTEGER NOT NULL,
    anchor TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    line_start INTEGER,
    line_end INTEGER
);

CREATE TABLE tangle_refs (
    id INTEGER PRIMARY KEY,
    node_id TEXT NOT NULL REFERENCES tangle_nodes(id),
    file_path TEXT NOT NULL,
    target TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT '',
    line_in_tangle INTEGER
);

CREATE TABLE tangle_links (
    id INTEGER PRIMARY KEY,
    source_path TEXT NOT NULL,
    target_path TEXT NOT NULL,
    link_type TEXT NOT NULL DEFAULT 'markdown_link'
);

-- Agent tables (ported from archive)
CREATE TABLE sessions (...);
CREATE TABLE messages (...);
CREATE TABLE tool_calls (...);
CREATE TABLE tool_results (...);
CREATE TABLE questions (...);
CREATE TABLE agent_sessions (...);
CREATE TABLE agent_events (...);
CREATE TABLE branch_locks (...);
CREATE TABLE agent_task_queue (...);
```

No `ui_state` table — UI settings live in `settings.json` (see §1.6).

### 1.4 Server — `taui/server/`

Port from `archive/taui/server/`. Changes:

| File | Changes |
|---|---|
| `app.py` | `specs` → `tangles` in service init, lifespan, flush |
| `handlers.py` | RPC methods renamed `spec.*` → `tangle.*`. New `ui.*` methods for stateless UI — see §1.7 |
| `protocol.py` | No changes (generic JSON-RPC) |
| `state.py` | `specs_path` → `tangles_path`, `SpecService` → `TangleService` |
| `server.py` | Minimal naming changes |

### 1.5 Agent — `taui/agent/`

Port from `archive/taui/agent/`. Changes:

| File | Changes |
|---|---|
| `prime.py` | `spec_ref` → `tangle_ref` in prompt templates. System prompt is now user-editable — loaded from `settings.json`, not hardcoded. See §1.8 |
| `runner.py` | `spec` → `tangle` in tool dispatches and context loading |
| `manager.py` | `spec` → `tangle` in session management |
| `session.py` | Minimal naming |
| `box.py` | `spec_compliance` → `tangle_compliance`, `SpecVerification` → `TangleVerification` |
| `agents.py` | Port as-is |
| `cost_tracker.py` | Port as-is |
| `naming.py` | Port as-is |
| `system_prompt_loader.py` | **Rewrite** — loads prompts from `settings.json` with fallback to built-in defaults. See §1.8 |

### 1.6 Storage

**Old model:** `~/.local/share/taui/sessions.db` for history, cache DB derived from workspace path for tangle index.

**New model:** Two project-local stores, each with a clear responsibility:

#### `<project>/tangles/.taui.db` — Runtime & Derived Data (gitignored)

SQLite database. Contains data that is computed, transient, or too large for a flat file:

- Tangle file index and parsed nodes/refs/links
- Agent sessions and message history
- Tool call logs

This is a cache/runtime store. Deleting it means taui re-indexes tangles on next start and agent history is lost, but the project is otherwise unaffected.

#### `<project>/.taui/settings.json` — User Settings (optionally git-tracked)

Human-readable JSON file. Contains everything the user might want to version-control, share with the team, or hand-edit:

```json
{
  "tabs": {
    "open": ["tangles/index.md", "tangles/domains/auth.md"],
    "active": "tangles/domains/auth.md"
  },
  "layout": {
    "sidebarCollapsed": false,
    "splitSizes": [20, 50, 30]
  },
  "theme": "dark",
  "prompts": {
    "prime_system": {
      "content": "You are the prime agent...",
      "is_default": true,
      "last_updated": "2026-04-07"
    },
    "root_agent_system": { "content": "...", "is_default": true, "last_updated": "2026-04-07" },
    "sub_agent_system": { "content": "...", "is_default": true, "last_updated": "2026-04-07" },
    "tangle_maker": { "content": "...", "is_default": true, "last_updated": "2026-04-07" },
    "tangle_reviewer": { "content": "...", "is_default": true, "last_updated": "2026-04-07" }
  }
}
```

On first run, taui creates this file with defaults. When a user edits a prompt, `is_default` flips to `false`. If taui ships an updated default, it only overwrites prompts where `is_default` is `true`.

The backend reads/writes this file for all `ui.*` and `prompts.*` RPC methods. No DB table for UI state or prompts.

#### `~/.taui/` — Global Config

- Auth tokens (copilot, gemini, antigravity, codex)
- Global config (default model, default prompts if no project override)

#### Gitignore

When taui creates the `tangles/` directory, it also creates/appends `tangles/.taui.db` to the project's `.gitignore`. The `.taui/` directory is **not** gitignored by default — teams can choose to track `settings.json`.

### 1.7 Stateless UI Architecture

The UI holds **no authoritative state**. All persistent state lives in the backend DB. The UI is a pure renderer.

#### What lives in the backend

| State | Backend location | Previously |
|---|---|---|
| Open tabs + active tab | `settings.json` → `tabs` | localStorage in browser |
| Sidebar collapsed state | `settings.json` → `layout` | localStorage in browser |
| Split pane sizes | `settings.json` → `layout` | localStorage in browser |
| Theme preference | `settings.json` → `theme` | localStorage / Svelte store |
| System prompts | `settings.json` → `prompts` | Hardcoded in Python |
| Agent conversation messages | `.taui.db` → `messages` table | Svelte store (partially persisted) |
| Agent streaming status | `.taui.db` → `agent_sessions` table | Svelte store (lost on refresh) |
| Tangle tree | `.taui.db` → `tangle_files` + `tangle_nodes` tables | Fetched on connect, lost on refresh |

#### What stays ephemeral in UI

- Toast notifications (transient by nature)
- Hover states, animations, focus tracking
- In-flight keystroke debouncing
- Modal open/close (command palette, settings)

#### Reconnection Protocol

```
1. UI opens WebSocket → sends "state.snapshot" RPC
2. Backend reads settings.json + queries DB, returns full snapshot:
   {
     tabs: [...],                    // from settings.json
     activeTabId: "...",             // from settings.json
     layout: { sidebarCollapsed, splitSizes, ... },  // from settings.json
     theme: "dark",                  // from settings.json
     tangleTree: [...],              // from DB
     agentSessions: [               // from DB
       { id, status: "streaming" | "idle" | "done", lastMessageId },
       ...
     ]
   }
3. UI renders from snapshot — identical to state before disconnect
4. For each agentSession with status "streaming":
   - UI sends "agent.subscribe" RPC with session ID
   - Backend replays any messages written to DB since lastMessageId
   - Backend continues pushing new events as they stream from LLM
5. User actions go through backend:
   - User opens tab → UI sends "ui.openTab" RPC → backend updates settings.json → pushes state update
   - User toggles sidebar → UI sends "ui.updateLayout" RPC → backend updates settings.json → pushes state update
```

#### Key Principle

The UI never computes authoritative state. It receives state from backend and renders it. User interactions are **intents** sent to backend. Backend is the single source of truth.

This means:
- Page refresh = reconnect + snapshot. No data loss.
- Agent mid-reply = agent writes to DB as it streams. On reconnect, catch up from DB, re-subscribe to live stream.
- Multiple windows (future) = each window connects independently, receives same state.
- Backend crash = on restart, reads DB, resumes from last persisted state. In-flight LLM streams are lost but conversation history is preserved.

#### New RPC Methods

```
ui.snapshot          → returns full UI state
ui.openTab           → open a tangle in a tab
ui.closeTab          → close a tab
ui.setActiveTab      → switch active tab
ui.updateLayout      → update sidebar/split state
ui.setTheme          → change theme
ui.saveTab           → save tab content

agent.subscribe      → subscribe to a streaming agent session
agent.unsubscribe    → stop receiving events for a session
```

#### Impact on Frontend Stores

Svelte stores become **thin wrappers over backend state**, not independent state containers:

```typescript
// OLD: store owns state, persists to localStorage
class TabStore {
  tabs = $state<Tab[]>([])
  openTab(path: string) {
    this.tabs.push(newTab)
    localStorage.setItem('tabs', JSON.stringify(this.tabs))
  }
}

// NEW: store mirrors backend state, sends intents
class TabStore {
  tabs = $state<Tab[]>([])            // populated from snapshot
  async openTab(path: string) {
    await rpc('ui.openTab', { path })  // backend updates DB, pushes new state
  }
  applySnapshot(snapshot: TabSnapshot) {
    this.tabs = snapshot.tabs           // called on connect + on push
  }
}
```

### 1.8 User-Editable System Prompts

System prompts for agents and tools are **not hardcoded**. They have defaults that ship with taui, but users can view and edit them.

#### Prompt Types

| Prompt | What it controls | Default ships with |
|---|---|---|
| `prime_system` | Prime agent behavior, personality, instructions | Yes |
| `root_agent_system` | Root agent (long task) behavior | Yes |
| `sub_agent_system` | Sub-agent behavior, scoping rules | Yes |
| `tangle_maker` | How agents write/structure tangle documents | Yes — defines default sections, code ref conventions, etc. |
| `tangle_reviewer` | How agents review/update existing tangles | Yes |

#### Storage

Prompts are stored in `<project>/.taui/settings.json` under the `prompts` key (see §1.6 for the full file structure):

```json
{
  "prompts": {
    "prime_system": {
      "content": "You are the prime agent...",
      "is_default": true,
      "last_updated": "2026-04-07"
    },
    "tangle_maker": {
      "content": "When writing a tangle, include...",
      "is_default": true,
      "last_updated": "2026-04-07"
    }
  }
}
```

On first run, default prompts are seeded into the file. When a user edits a prompt, `is_default` flips to `false`. If taui ships an updated default, it only overwrites prompts where `is_default` is `true`.

#### Access

- **Settings page** — a "Prompts" or "Introspection" section where users see and edit each prompt.
- **RPC methods:** `prompts.list`, `prompts.get`, `prompts.update`, `prompts.reset` (revert to default).

#### How This Replaces Frontmatter Structure

The old plan put `refs`, `test_refs`, `depends_on`, `tags`, `status`, `owners` in frontmatter — enforcing a rigid document structure. Now:

- The `tangle_maker` prompt says: *"When writing a tangle, include a Dependencies section with markdown links to related tangles. Include code references inline using backtick notation. Add a Constraints section if there are implementation constraints..."*
- The user can edit this prompt to say: *"Skip the Dependencies section. Always include a Testing Strategy section instead."*
- The tangle format only requires `title` and `last_updated` in frontmatter. Everything else is free-form body content, shaped by the prompt.

---

## Phase 2: New Frontend — `app/`

Port the Svelte frontend. Same tech (Svelte 5, Tauri, TailwindCSS 4, Vite). Same visual design. Rename spec → tangle. Refactor stores for stateless architecture.

### 2.1 Config Files

Port as-is from archive:

- `package.json` — same deps, same scripts
- `vite.config.ts` — same aliases, same config
- `svelte.config.js` — same
- `tsconfig.json` — same
- `index.html` — same
- `src-tauri/` — same (Cargo.toml, tauri.conf.json, lib.rs, main.rs)

### 2.2 Component Rename Map

| Archive component | New component | Changes |
|---|---|---|
| `SpecEditorPane.svelte` | `TangleEditorPane.svelte` | Class names, empty state text |
| `SpecNavItem.svelte` | `TangleNavItem.svelte` | Prop/type names |
| `SpecNavSidebar.svelte` | `TangleNavSidebar.svelte` | RPC calls, type refs |
| `SpecTreePane.svelte` | `TangleTreePane.svelte` | Tree rendering |
| `SettingsModal.svelte` | `SettingsModal.svelte` | Add "Prompts" / "Introspection" tab for editing system prompts |
| All other components | Same names | Port as-is |

### 2.3 Type Rename Map

| Archive file | New file | Changes |
|---|---|---|
| `types/spec-nav.ts` | `types/tangle-nav.ts` | `SpecNav*` → `TangleNav*` |
| `types/index.ts` | `types/index.ts` | Any `Spec` types → `Tangle` types |
| `utils/specs.ts` | `utils/tangles.ts` | `specRefToFilePath` → `tangleRefToFilePath`, `deriveSpecTitle` → `deriveTangleTitle` |

### 2.4 Store Changes — Stateless Refactor

All stores become thin mirrors of backend state:

| Store | Changes |
|---|---|
| `app-state.svelte.ts` | `specs` → `tangles`. Add `applySnapshot()`. Remove localStorage persistence. State comes from backend on connect. |
| `tabs.svelte.ts` | Remove localStorage save/restore. `openTab`/`closeTab`/`setActive` become async RPC calls. `applySnapshot()` for state from backend. |
| `file-tree.svelte.ts` | Sidebar collapsed state sent to backend via `ui.updateLayout`. |
| `theme.svelte.ts` | Theme preference stored in backend. `toggle()` sends RPC, applies on push-back. |
| `toasts.svelte.ts` | **No change** — toasts are ephemeral, stay in UI. |
| `actions.ts` | `spec` → `tangle` in action names. |

### 2.5 Service Changes

| Archive file | Changes |
|---|---|
| `services/backend-client.ts` | RPC method names: `spec.*` → `tangle.*`. Add `ui.*` and `prompts.*` methods. Add `agent.subscribe`/`agent.unsubscribe`. |
| `services/connection.ts` | On connect: call `ui.snapshot`, populate all stores. On reconnect: same. Handle agent session re-subscription. |
| `services/fold-state.ts` | Port as-is |
| `services/monaco-theme.ts` | Port as-is |
| `services/notifications.ts` | Port as-is |

### 2.6 CSS

Port `app.css` as-is. Class names that use `spec-` prefix change to `tangle-` prefix in the renamed components.

### 2.7 App.svelte

Port as-is with one import change: `SpecNavSidebar` → `TangleNavSidebar`.

---

## Phase 3: New Tests — `tests/`

### 3.1 Test File Map

| Archive test | New test | Changes |
|---|---|---|
| `test_specs_service.py` | `test_tangle_service.py` | `SpecService` → `TangleService`, new tangle format fixtures |
| `test_specs_db.py` | `test_tangle_db.py` | New schema, new table names |
| `test_server_app.py` | `test_server_app.py` | RPC method names, response shapes, ui.snapshot |
| `test_agent.py` | `test_agent.py` | Minimal spec→tangle renames |
| `test_agent_rpc.py` | `test_agent_rpc.py` | Same |
| `test_phase3.py` | `test_tools.py` | Rename for clarity |
| `test_phase3_rpc.py` | `test_tools_rpc.py` | Rename for clarity |
| `test_server_startup.py` | `test_server_startup.py` | Port, rename refs |
| `test_phase6.py` | `test_tangle_writer.py` | Rename, new format |

### 3.2 Test Fixtures

Create `tests/example_project/tangles/` (replacing `tests/example_project/specs/`):

```
tests/example_project/tangles/
├── index.md
├── domains/
│   ├── task-management.md
│   ├── authentication.md
│   └── data-layer.md
└── features/
    ├── create-task.md
    ├── edit-task.md
    └── delete-task.md
```

All fixtures use the new tangle format (minimal frontmatter + body content). No legacy format support.

### 3.3 New Tests

- `test_tangle_parser.py` — frontmatter parsing, heading extraction, code ref extraction from body, markdown link resolution
- `test_tangle_refs.py` — code reference pattern matching (`file:function`, `file:line_range`)
- `test_settings.py` — `settings.json` read/write, snapshot construction from settings + DB, tab state persistence, layout state, theme
- `test_prompts.py` — default prompt seeding in `settings.json`, user edits, reset to default, upgrade behavior for `is_default` prompts

---

## Phase 4: Tangle Standards

The tangle standards document is itself a tangle. It defines the **default** conventions. Users can deviate — the format only requires `title` and `last_updated` in frontmatter.

### 4.1 Tangle Standards Content

```markdown
---
title: Tangle Standards
last_updated: 2026-04-07
---

# Tangle Standards

A tangle is a literate document. Prose and code are interwoven.
The tangle is the source of truth; the code is the derived artifact.

## Document Format

Every tangle is a markdown file with minimal YAML frontmatter.

### Required Frontmatter

- `title` — human-readable name
- `last_updated` — ISO date of last modification

That's it. Everything else goes in the body.

### Body Content

The body is standard markdown. Headings create navigable sections.
What sections you include is up to you — the tangle-making tool's
prompt suggests defaults, but you can change the prompt.

### Code References

Code references appear inline in prose:

- Arrow notation: `→ src/auth.py:register_handler`
- Backtick notation: `src/auth.py:register_handler`
- Line ranges: `src/auth.py:45-52`

All paths are relative to the project root.

### Linking Other Tangles

- Markdown links: `[Data Layer](tangles/domains/data-layer.md)`
- With anchors: `[Behavior](tangles/domains/data-layer.md#behavior)`
- Bare paths: `tangles/domains/data-layer.md`

All tangle paths are relative to the project root. This is core markdown only — no custom syntax.

## File Organization

The default prompt suggests this structure:

tangles/
├── index.md          # project overview (always required)
├── standards.md      # this document
├── domains/          # bounded contexts
├── features/         # user-facing capabilities
└── decisions/        # architectural decision records

You can organize however you want. The only requirement
is `index.md` as the entry point.

## Customization

The structure of tangle documents is controlled by the
tangle-making tool's system prompt, not by the format itself.

To change what sections tangles include, edit the prompt in
Settings → Prompts → Tangle Maker.

Same goes for agent behavior — prime, root, and sub-agent
prompts are all editable in Settings → Prompts.
```

---

## Execution Order

### Step 1: Archive (Phase 0)

1. Create `archive/` directory
2. `git mv app/ archive/app/`
3. `git mv taui/ archive/taui/`
4. `git mv tests/ archive/tests/`
5. `git mv notes/ archive/notes/`
6. `git mv .plans/ archive/.plans/`
7. `git mv pyproject.toml archive/pyproject.toml`
8. Commit: `"archive: move all existing code to archive/"`

### Step 2: Scaffold (Phase 1.1 + 1.2)

1. New `pyproject.toml` at root
2. New `taui/__init__.py`, `taui/__main__.py`
3. Port unchanged modules: `auth/`, `config/`, `llm/`, `llms/`, `lsp/`, `plugins/`, `skills/`, `symbols/`, `commands/`, `log_config.py`
4. Commit: `"scaffold: port unchanged backend modules from archive"`

### Step 3: Tangle Module (Phase 1.3)

1. Create `taui/tangle/` with new models, db, parser, writer, service, sync, refs, errors
2. DB schema includes tangle + agent tables in `.taui.db`. Settings live in `.taui/settings.json` (see §1.6)
3. Commit: `"tangle: implement new tangle module replacing specs"`

### Step 4: Server + Agent + Prompts (Phase 1.4 + 1.5 + 1.8)

1. Port `taui/server/` with spec→tangle renames + new `ui.*` and `prompts.*` RPC methods (reading/writing `settings.json`)
2. Port `taui/agent/` with spec→tangle renames + prompt loading from `settings.json`
3. Commit: `"server+agent: port with tangle renames, stateless UI, editable prompts"`

### Step 5: Frontend (Phase 2)

1. Port `app/` config files
2. Port all components, renaming Spec→Tangle where needed
3. Refactor stores to stateless model (snapshot-based, RPC-driven)
4. Add prompts UI to SettingsModal
5. Commit: `"app: port frontend with tangle renames and stateless architecture"`

### Step 6: Tests (Phase 3)

1. Create new test fixtures in tangle format
2. Port and rename test files
3. Add new tests for parser, refs, ui state, prompts
4. Commit: `"tests: port and update test suite for tangles"`

### Step 7: Standards (Phase 4)

1. Create `tangles/standards.md`
2. Create `tangles/index.md` for the taui project itself
3. Commit: `"tangles: add tangle standards and project index"`

---

## Risk Assessment

### Low risk (port as-is)

- Auth, config, LLM, LSP, plugins, skills, symbols, commands — isolated modules with no spec/tangle coupling.

### Medium risk (rename + adapt)

- Server handlers — RPC method renames + new ui/prompts methods.
- Agent module — `spec_ref` → `tangle_ref` in prompts and task graphs.
- Frontend components — four renames, type renames, util renames.

### High risk (redesign)

- **Tangle module** — new data model, parser extracts refs/links from body instead of frontmatter.
- **Stateless UI** — fundamental shift in how stores work. Every store needs refactoring from "owns state + localStorage" to "mirrors backend + sends intents". Connection logic gets more complex (snapshot on connect, re-subscribe to streams).
- **Editable prompts** — new subsystem (`settings.json` storage, RPC methods, settings UI). Must handle default seeding, user overrides, and version upgrades cleanly.

### Mitigation

- Archive is always there for reference.
- Port unchanged modules first to establish a working import graph.
- Build tangle module with tests before wiring it into server/agent.
- Build stateless UI incrementally: start with snapshot on connect, then migrate stores one by one.
- Frontend and backend RPC renames happen in one step to avoid protocol mismatch.

---

## Naming Glossary

| Old term | New term | Context |
|---|---|---|
| spec | tangle | Document type |
| spec_ref | tangle_ref | Reference identifier (`tangles/auth.md#behavior`) |
| specs/ | tangles/ | Directory name |
| spec standards | tangle standards | Meta-document defining format |
| SpecDB | TangleDB | Database class |
| SpecService | TangleService | Service class |
| SpecSync | TangleSync | Sync class |
| SpecNode | TangleNode | Data model |
| SpecFile | TangleFile | Data model |
| SpecNavItem | TangleNavItem | UI component/type |
| SpecEditorPane | TangleEditorPane | UI component |
| SpecNavSidebar | TangleNavSidebar | UI component |
| SpecTreePane | TangleTreePane | UI component |
| `spec.getTree` | `tangle.getTree` | RPC method |
| `spec.getNode` | `tangle.getNode` | RPC method |
| `_main.md` | `index.md` | Root document |
| `~/.local/share/taui/` | `<project>/tangles/.taui.db` + `<project>/.taui/settings.json` | Project-local storage |
| `~/.taui/` | `~/.taui/` | Global auth/config only |
| `{{code_ref:}}` | inline `→` notation in body | Code reference |
| `{{status:}}` | body content (not enforced) | Status |
| `{{depends_on:}}` | markdown links or bare paths in body | Dependencies |
| hardcoded system prompts | user-editable prompts in `settings.json` | Agent behavior |

---

## Key Architecture Decisions

### 1. Minimal frontmatter — `title` + `last_updated` only

Structure is prompt-driven, not format-driven. The tangle-making tool's system prompt defines what sections agents produce. Users edit the prompt, not the format spec.

### 2. All paths relative to project root

`src/auth.py:func` means `<project>/src/auth.py`. `tangles/auth.md` means `<project>/tangles/auth.md`. No ambiguity about what "root" means.

### 3. Project-local storage

Two project-local stores: `tangles/.taui.db` (gitignored) for runtime/derived data (tangle index, agent history), and `.taui/settings.json` (optionally git-tracked) for user settings (tabs, layout, theme, prompts). `~/.taui/` is only for global auth tokens.

### 4. Stateless UI

Backend is the single source of truth. UI gets state from snapshot on connect (backend reads `settings.json` + DB), receives pushes during operation, sends intents on user action. Page refresh = reconnect + snapshot. Agent mid-stream survives refresh.

### 5. User-editable system prompts

Prime, root agent, sub-agent, tangle-maker, and tangle-reviewer prompts are stored in `settings.json` with defaults. Users view/edit in Settings. This replaces rigid frontmatter structure with flexible, user-controlled document conventions.
