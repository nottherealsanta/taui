# Variable Bindings — Live Spec-to-Code Editing

## Overview

Spec nodes can expose **variables** — named values that map to specific expressions in source code. Users edit variable values directly in the spec tree UI (e.g., change a website's background color), and the system resolves the binding to the exact source location and applies the edit. Agents also read and write through the same bindings.

This eliminates the need to navigate to code for common configuration-style changes while keeping source files as the single source of truth.

---

## 1. Core Concept

A **var binding** connects a human-friendly name in a spec node to a concrete symbol (or expression) in a source file.

```
Spec Node: "Website Theme"
  ├── {{var: bg_color = "#ff0000" -> src/theme.py::BACKGROUND_COLOR}}
  ├── {{var: font_size = "16px" -> src/styles.css::--font-size}}
  └── {{var: app_name = "My App" -> src/config.ts::APP_NAME}}
```

The spec node displays these as editable fields. When a user changes a value:

1. **Resolve** — find the current byte range of the symbol's value in the source file
2. **Edit** — replace the old value with the new one
3. **Sync** — update the spec metadata to reflect the new value and line numbers

The source file is always the source of truth. The spec caches the last-known value for display, but reads from source on focus/open.

---

## 2. Metadata Format

### Spec-side syntax

```markdown
- Website Theme
    - {{var: <name> = <display_value> -> <file_path>::<symbol>}}
```

Fields:
| Field | Description |
|-------|-------------|
| `name` | Human-readable variable name shown in the UI |
| `display_value` | Cached last-known value (for display before resolution) |
| `file_path` | Relative path to the source file |
| `symbol` | The symbol name in source (variable, property, CSS custom property, etc.) |

### Backend model

```python
@dataclass(slots=True)
class VarBinding:
    name: str              # "bg_color"
    display_value: str     # "#ff0000"
    file_path: str         # "src/theme.py"
    symbol: str            # "BACKGROUND_COLOR"
    language: str          # inferred from file extension
    resolved_range: tuple[int, int] | None = None  # (start_byte, end_byte) from last resolution
```

Stored in the `node_vars` table (new):

```sql
CREATE TABLE node_vars (
    id INTEGER PRIMARY KEY,
    node_id TEXT NOT NULL REFERENCES nodes(id),
    name TEXT NOT NULL,
    display_value TEXT NOT NULL,
    file_path TEXT NOT NULL,
    symbol TEXT NOT NULL,
    language TEXT NOT NULL,
    UNIQUE(node_id, name)
);
```

---

## 3. Resolution Strategy

### Primary: Tree-sitter

Tree-sitter is the primary mechanism for resolving a symbol to its value range in source code. It provides precise AST-level queries without needing a running language server.

**Why Tree-sitter over LSP:**
- No server lifecycle to manage — parse on demand
- Returns exact value ranges (not just symbol ranges)
- Works offline and for any language with a grammar
- Sub-millisecond for single-file queries

**Resolution flow:**

```
file_path + symbol
    ↓
read source file
    ↓
parse with tree-sitter (language grammar from file extension)
    ↓
run structural query to find assignment where LHS = symbol
    ↓
extract RHS (value) node range
    ↓
return (start_byte, end_byte, current_value_text)
```

**Example tree-sitter queries per language:**

Python assignment:
```scheme
(assignment
  left: (identifier) @name
  (#eq? @name "BACKGROUND_COLOR")
  right: (_) @value)
```

CSS custom property:
```scheme
(declaration
  (property_name) @name
  (#eq? @name "--font-size")
  (plain_value) @value)
```

TypeScript/JavaScript const:
```scheme
(variable_declarator
  name: (identifier) @name
  (#eq? @name "APP_NAME")
  value: (_) @value)
```

JSON key-value:
```scheme
(pair
  key: (string) @name
  (#eq? @name "\"appName\"")
  value: (_) @value)
```

### Fallback: Regex

For languages without a tree-sitter grammar or when resolution fails, fall back to regex-based pattern matching anchored by the `code_ref` line hint:

```python
# Python: SYMBOL = <value>
r'^{symbol}\s*=\s*(.+)$'

# CSS: --symbol: <value>;
r'{symbol}\s*:\s*([^;]+)'

# JSON: "symbol": <value>
r'"{symbol}"\s*:\s*(.+)'
```

### Optional: LSP as secondary resolver

If a language server is already running (e.g., spawned for agent use), use `textDocument/documentSymbol` to cross-check the symbol location. This helps when:
- The symbol is re-exported or aliased
- The file has been heavily edited and line hints are stale
- Cross-file resolution is needed (imports, re-exports)

LSP is never required — it's an enhancement when available.

---

## 4. Edit Flow

### User edits a variable in the UI

```
User changes bg_color from "#ff0000" to "#00ff00"
    ↓
Frontend sends: var/update {spec_ref, var_name: "bg_color", new_value: "#00ff00"}
    ↓
Backend resolves current range via tree-sitter
    ↓
Backend applies edit to source file (direct write)
    ↓
Backend updates display_value in node_vars table
    ↓
Backend sends notification: var/changed {spec_ref, var_name, old_value, new_value}
    ↓
Frontend updates the variable field in the spec node
```

### Agent edits a variable

Agents use the same mechanism via a tool:

```
spec_set_var(spec_ref, var_name, new_value)
```

This goes through the same resolve → edit → sync pipeline, ensuring agents and humans use an identical code path.

### Conflict handling

- Before writing, always re-read the source file and re-resolve the range
- If the symbol can't be found (e.g., someone renamed it), return an error — don't guess
- If the current value in the file differs from `display_value`, warn the user (the value was changed outside Taui)

---

## 5. Sync: Keeping Bindings Fresh

### On spec sync (`full_sync`)

When the spec tree is synced from markdown:
1. Parse `{{var: ...}}` metadata items from node content
2. For each binding, resolve the current value via tree-sitter
3. If the resolved value differs from `display_value`, update `display_value` in the DB
4. If the symbol can't be found, mark the binding as `stale` (surfaced in UI with a warning)

### On file change (file watcher)

When a source file is modified (by agent, user, or external editor):
1. Find all var bindings that reference that file
2. Re-resolve each binding
3. Push `var/changed` notifications for any values that changed

This ensures the spec UI always reflects actual source values, even when code is edited outside Taui.

---

## 6. RPC Methods

### Client → Server

| Method | Params | Returns | Description |
|--------|--------|---------|-------------|
| `var/get` | `{spec_ref}` | `{vars: VarBinding[]}` | Get all var bindings for a node |
| `var/resolve` | `{spec_ref, var_name}` | `{value, range, stale}` | Resolve current value from source |
| `var/update` | `{spec_ref, var_name, new_value}` | `{ok, old_value, new_value}` | Edit variable value in source |
| `var/create` | `{spec_ref, name, file_path, symbol}` | `{binding: VarBinding}` | Create a new var binding on a node |
| `var/delete` | `{spec_ref, var_name}` | `{ok}` | Remove a var binding |

### Server → Client Notifications

| Notification | Params | Description |
|-------------|--------|-------------|
| `var/changed` | `{spec_ref, var_name, old_value, new_value, source}` | Variable value changed (`source`: "user", "agent", "external") |
| `var/stale` | `{spec_ref, var_name, reason}` | Binding can't be resolved (symbol missing, file deleted, etc.) |

---

## 7. UI Presentation

Each spec node with var bindings shows a **variables section** below the node content:

```
┌─────────────────────────────────────┐
│ # Website Theme                     │
│ Base visual styling for the app     │
│                                     │
│ Variables                           │
│ ┌─────────────┬───────────────────┐ │
│ │ bg_color    │ #ff0000  [🎨]    │ │
│ │ font_size   │ 16px             │ │
│ │ app_name    │ My App           │ │
│ └─────────────┴───────────────────┘ │
│                                     │
│ → src/theme.py::BACKGROUND_COLOR    │
│ → src/styles.css::--font-size       │
│ → src/config.ts::APP_NAME           │
└─────────────────────────────────────┘
```

- Values are inline-editable (click to edit, Enter to commit)
- Color values get a color picker affordance
- Stale bindings show a warning icon with tooltip
- The source file path is shown as a subtle annotation (clickable to navigate)
- Agents can see and edit these same fields via `spec_set_var`

---

## 8. Implementation Phases

### Phase 1: Backend model + resolution
- [ ] Add `VarBinding` dataclass to `taui/specs/models.py`
- [ ] Add `node_vars` table to `taui/specs/db.py`
- [ ] Parse `{{var: ...}}` metadata in `taui/specs/sync.py`
- [ ] Implement tree-sitter resolution module (`taui/specs/var_resolver.py`)
  - Python grammar first, then CSS, JS/TS, JSON
  - Regex fallback for unsupported languages
- [ ] Add `var/get`, `var/resolve`, `var/update`, `var/create`, `var/delete` RPC handlers

### Phase 2: File watching + sync
- [ ] On `full_sync`, resolve all bindings and update stale status
- [ ] Add file watcher integration for source files referenced by bindings
- [ ] Push `var/changed` and `var/stale` notifications

### Phase 3: UI
- [ ] Parse var bindings from node data in Rust frontend
- [ ] Render variables section in spec node detail view
- [ ] Inline editing of variable values
- [ ] Color picker for color-type values
- [ ] Stale binding warning indicators
- [ ] Wire `var/update` RPC call on commit

### Phase 4: Agent integration
- [ ] Add `spec_set_var` and `spec_get_vars` to agent tool set
- [ ] Agents can create new var bindings via `var/create`
- [ ] Surface var bindings in agent context when reading a spec node

---

## 9. Dependencies

- **tree-sitter Python bindings**: `tree-sitter` + language grammars (`tree-sitter-python`, `tree-sitter-css`, `tree-sitter-javascript`, `tree-sitter-typescript`, `tree-sitter-json`)
- **File watcher**: `watchfiles` (already likely in use or easy to add)
- **Existing infrastructure**: spec sync, RPC handlers, notification dispatch

---

## 10. Design Decisions

**Tree-sitter over LSP as primary resolver** — LSP gives symbol-level resolution but not value-level. Tree-sitter gives exact AST node ranges for the value expression, which is what we need for surgical edits. LSP remains available as a secondary resolver for cross-file scenarios.

**Source file as source of truth** — The spec caches `display_value` for fast rendering, but always re-reads from source before applying edits. This avoids stale-write bugs where the cached value doesn't match reality.

**Same code path for humans and agents** — Both go through `var/update` → resolve → edit → sync. No separate "agent edit" vs "human edit" paths. The `source` field in `var/changed` notifications distinguishes who made the change.

**No custom tree-sitter queries in metadata** — The resolution module uses built-in per-language query templates. Users specify only `file_path::symbol`. Custom queries could be added later as an escape hatch for unusual patterns, but we start simple.
