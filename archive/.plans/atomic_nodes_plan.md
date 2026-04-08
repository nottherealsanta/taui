# Atomic Nodes Plan

## Overview

The node is the fundamental unit in Taui's spec system. Each node is a Python dataclass backed by SQLite. Nodes are also serialized as markdown files (using list-of-list format per [spec_standards.md](../spec_standards.md)) for standalone readability and version control.

This plan defines the data model for nodes, how metadata is stored, and the changes needed across the Python backend, Rust UI, spec standards, and example project.

---

## Node Data Model

### Core fields (on `nodes` table)

| Field | Type | Description |
|---|---|---|
| `id` | TEXT PK | UUID, stable across renames |
| `file_id` | INTEGER FK | References `files.id` |
| `spec_ref` | TEXT UNIQUE | `file_path#anchor` |
| `anchor` | TEXT | Slug derived from title (metadata stripped) |
| `depth` | INTEGER | Tree depth |
| `heading_level` | INTEGER | Heading prefix level |
| `line_start` | INTEGER | Source line start (1-indexed) |
| `line_end` | INTEGER | Source line end |
| `markdown` | TEXT | Node content with metadata **stripped** |
| `sort_order` | INTEGER | Global ordering |
| `status` | TEXT | Nullable. One of: `draft`, `ready`, `in_progress`, `to_review`, `done`, `blocked` |
| `code_refs` | TEXT | Nullable. JSON array of code reference strings, e.g. `["src/server.py#L10-L20", "src/utils.py"]` |
| `verification` | TEXT | Nullable. Verification command string |
| `collapsed` | BOOLEAN | Default 0. UI-only state — **not** written to markdown |
| `created_at` | REAL | Timestamp |
| `updated_at` | REAL | Timestamp |

### Relationship fields (in `node_refs` table)

| Field | Type | Description |
|---|---|---|
| `from_node` | TEXT FK | Source node ID |
| `to_node` | TEXT FK | Target node ID (nullable if unresolvable) |
| `kind` | TEXT | `depends_on` or `related_to` |

- `depends_on` — directional. Node A depends on node B.
- `related_to` — symmetric. Query both directions: `WHERE from_node = ? OR to_node = ?`.
- Generic markdown links (`[text](file.md#anchor)`) are **not** stored in `node_refs`.

### Removed tables

- `node_metadata` — replaced by typed columns on `nodes` and `node_refs.kind`.

---

## Status Model

Canonical values (underscore convention):

- `draft`
- `ready`
- `in_progress`
- `to_review`
- `done`
- `blocked`

Transitions:

1. `draft` -> `ready`
2. `ready` -> `in_progress`
3. `in_progress` -> `done`
4. `in_progress` -> `blocked`
5. `in_progress` -> `to_review`
6. `to_review` -> `done`
7. `to_review` -> `in_progress`
8. `blocked` -> `in_progress`

Legacy `in-progress` (hyphen) is accepted on parse and normalized to `in_progress`.

---

## Markdown Serialization Format

The markdown format is unchanged from the existing convention — files are standalone-readable with clickable links and visible code paths.

### Status — child metadata item

```md
- Feature A
    Feature description here.
    - {{status: draft}}
```

### Code references — child list items

```md
- Feature A
    Feature description here.
    - {{status: done}}
    - {{code_ref: `src/server.py#L10-L20`}}
    - {{code_ref: `src/utils.py`}}
```

### Dependencies and relations — child list items with markdown links

```md
- Feature B
    - {{status: in_progress}}
    - {{depends_on: [Auth model](server.md#auth-model)}}
    - {{related_to: [Background jobs](jobs.md#background-jobs)}}
```

Links use relative paths from the current file. The link target (`file.md#anchor`) resolves to a node via file path + anchor during sync. The link text is the human-readable label.

### Verification — child list item

```md
- Feature A
    - {{status: done}}
    - {{verification: pytest tests/test_feature.py -q}}
```

### Collapsed — **not** in markdown

`collapsed` is purely UI state stored in the `nodes.collapsed` DB column. It is never written to or read from markdown files.

---

## Parser Behavior (sync.py)

During `full_sync()`, the parser:

1. **Parses list items** into tree nodes as before.
2. **Extracts status metadata** from child list items: `{{status: value}}` -> parent `status` column.
   - Inline status on title line remains accepted for backward compatibility and is normalized into the same `status` field.
   - If both inline and child status are present, child status wins.
3. **Identifies metadata child list items** — items whose title matches `{{key: value}}`:
   - `{{code_ref: ...}}` -> appended to `code_refs` JSON array on the **parent** node.
   - `{{verification: ...}}` -> set as `verification` on the parent node.
   - `{{depends_on: [Text](target)}}` -> resolve link target to a node ID, insert into `node_refs(kind='depends_on')`. Allow dangling (unresolvable targets are skipped in `node_refs` but not an error).
   - `{{related_to: [Text](target)}}` -> resolve link target to a node ID, insert into `node_refs(kind='related_to')`.
   - `{{collapsed: ...}}` -> set `collapsed` column on parent node.
4. **Metadata child items are NOT tree nodes** — they do not get a node ID, anchor, spec_ref, or edges. They are consumed by the parent.
5. **The `markdown` field** stores only the human-written content with all `{{...}}` patterns removed.

---

## Writer Behavior (writer.py)

When serializing a node back to markdown:

1. **Title line**: node's first markdown line only (status is serialized as child metadata).
2. **Content lines**: remaining lines of `markdown` field.
3. **Child metadata items** (as indented `- {{key: value}}` list items):
   - `{{status: value}}` from `status` column.
   - `{{code_ref: `path`}}` for each entry in `code_refs` JSON array.
   - `{{verification: command}}` from `verification` column.
   - `{{depends_on: [Text](file.md#anchor)}}` — reverse-resolve node IDs from `node_refs(kind='depends_on')`:
     - Look up target node -> get `spec_ref` (e.g. `specs/server.md#auth-model`).
     - Compute relative path from current file to target file.
     - Use target node's anchor text as link label.
   - `{{related_to: [Text](file.md#anchor)}}` — same reverse-resolution.
4. **`collapsed` is NOT written** to markdown.

---

## Changes Required

### Phase 1: `spec_standards.md`

- Change all status values to underscores: `in_progress` (not `in-progress`).
- Add `to_review` to the status list and transition diagram.
- Note that legacy `in-progress` is accepted on parse.
- Clarify that `{{key: value}}` child list items are metadata belonging to the parent node, not tree nodes.
- Document that `collapsed` is UI-only state, not written to markdown.

### Phase 2: Python backend — DB schema (`taui/specs/db.py`)

**Add columns to `nodes` table:**
- `status TEXT`
- `code_refs TEXT` (JSON array)
- `verification TEXT`
- `collapsed INTEGER NOT NULL DEFAULT 0`

**Add `kind` column to `node_refs` table:**
- `kind TEXT NOT NULL DEFAULT 'ref'`
- Update `UNIQUE` constraint to `UNIQUE(from_node, to_node, kind)`

**Remove:**
- `CREATE TABLE node_metadata` and its indexes.
- `replace_node_metadata()` method.
- `get_node_metadata()` method.

**Add migration logic:**
- Use `PRAGMA table_info(nodes)` pattern (same as existing `markdown` migration) to add new columns.
- Migrate existing `node_metadata` rows into new typed columns before dropping the table.

**Update `NodeUpsert` dataclass:**
- Add `status`, `code_refs`, `verification`, `collapsed` fields.
- Update INSERT query in `replace_nodes_for_file()`.

**Update `replace_node_refs()`:**
- Change signature to `list[tuple[str, str, str]]` -> `(from_node, to_node, kind)`.
- Insert `kind` column.

**Add new query methods:**
- `get_depends_on(node_id) -> list[SpecNode]` — `WHERE from_node = ? AND kind = 'depends_on'`
- `get_related_to(node_id) -> list[SpecNode]` — `WHERE (from_node = ? OR to_node = ?) AND kind = 'related_to'`

**Update `_row_to_node` / `_row_to_detail`:**
- Include `status`, `code_refs`, `verification`, `collapsed` from the row.

### Phase 3: Python backend — Models (`taui/specs/models.py`)

**Update `SpecNode` dataclass:**
- Add fields: `status: str | None = None`, `code_refs: list[str] | None = None`, `verification: str | None = None`, `collapsed: bool = False`.
- Update `to_dict()` to include new fields.

**Update `SpecNodeDetail`:**
- Inherits new fields from `SpecNode`.

**Update `NodeUpsert`:**
- Add matching fields.

**Add constants:**
```python
VALID_STATUSES = {"draft", "ready", "in_progress", "to_review", "done", "blocked"}
```

**Remove:**
- `extract_status()`, `extract_status_from_block()` from `markdown.py` (defined but never called).
- `STATUS_RE` from `markdown.py` (no longer needed).

### Phase 4: Python backend — Sync (`taui/specs/sync.py`)

**Update `_parse_nodes()`:**
- When a list item's title matches `{{key: value}}` (metadata-only), do NOT create a `ParsedNode`. Instead, attach the extracted metadata to the parent node.
- Track accumulated `code_refs`, `verification`, `status`, `collapsed` per parent node.
- After processing all items, set the typed fields on each `ParsedNode`.

**Update `full_sync()`:**
- Remove the metadata collection loop (lines 134-138) and `replace_node_metadata()` call (line 194).
- For `depends_on` / `related_to` metadata items: parse the markdown link from the value, resolve to a node ID using `by_ref` / `first_node_by_file`, add to `refs` list with the appropriate `kind`.
- Generic markdown links in node content -> **no longer** added to `node_refs`. Remove the link-scanning loop (lines 140-167) or limit it to metadata items only.
- Strip `{{...}}` patterns from node `markdown` before storing.

**Update `ParsedNode` dataclass:**
- Add `status`, `code_refs`, `verification`, `collapsed` fields.

### Phase 5: Python backend — Writer (`taui/specs/writer.py`)

**Update `write_file()`:**
- Serialize `{{status: value}}` as a child metadata list item.
- Append `{{code_ref: ...}}`, `{{verification: ...}}` as child list items.
- Reverse-resolve `depends_on` / `related_to` from `node_refs`:
  - Look up target node by ID -> get `spec_ref` -> split into `file_path` + `anchor`.
  - Compute relative path from current file to target file.
  - Derive link text from anchor (un-slugify or use a stored label).
  - Emit `- {{depends_on: [Label](relative_path#anchor)}}`.
- Do NOT write `{{collapsed: ...}}`.

**New helper:**
- `_reverse_resolve_node_ref(from_file_path, target_node) -> str` — produces `[Label](relative_path#anchor)`.

### Phase 6: Python backend — Handlers (`taui/server/handlers.py`)

**Update `_handle_spec_get_node_code_refs`:**
- Read `code_refs` JSON column from the node instead of regex-scanning `markdown`.
- The `_resolve_code_reference()` logic stays — it resolves paths and returns file content previews.

**Add RPC method `spec/setNodeCollapsed`:**
- Params: `{ spec_ref: string, collapsed: boolean }`
- Updates the `collapsed` column on the node.
- Does NOT trigger markdown writeback.

**Update `spec/getNode` and `spec/getTree` responses:**
- Include `status`, `code_refs`, `verification`, `collapsed` in the node payload.

### Phase 7: Rust UI (`ui/src/app/state.rs`)

**Remove:**
- `parse_collapsed_metadata()` function.
- `update_collapsed_metadata()` function.
- All tests for these functions.

**Update collapsed handling:**
- Read `collapsed` from the `BackendNode` payload (new field).
- Toggle collapse via `spec/setNodeCollapsed` RPC call instead of mutating markdown.

**Update `BackendNode`:**
- Add `status: Option<String>`, `collapsed: bool` fields.
- Parse them from the JSON-RPC response.

### Phase 8: Example project (`tests/example_project/specs/`)

**Update all spec files to use underscore statuses:**
- `in-progress` -> `in_progress`
- All three files: `_main.md`, `database_schema.md`, `task_board.md`.

### Phase 9: Tests

**Update `tests/test_specs_service.py`:**
- `test_metadata_only_list_item_creates_node` -> rewrite: metadata items should NOT create nodes. Assert the parent node has `status`, `verification` fields populated instead.
- `test_metadata_only_siblings_use_unique_anchors` -> remove or rewrite (metadata items no longer have anchors).
- `test_dev_mode_still_builds_db_from_markdown` -> update assertion: `core_node.markdown` should not contain `{{status: ready}}` (it's been stripped to the `status` column).

**Update `tests/test_server_app.py`:**
- Code ref tests: update to use `code_refs` column instead of `{{code_ref: ...}}` in markdown.

**Update `ui/src/app/state.rs` tests:**
- Remove `test_parse_collapsed_metadata` and `test_update_collapsed_metadata`.
- Add tests for reading `collapsed` from `BackendNode`.

**Add new tests:**
- `test_status_extracted_to_column` — child `{{status: draft}}` -> `node.status == "draft"`, not in `node.markdown`.
- `test_legacy_inline_status_still_parses` — inline `{{status: draft}}` still parses into `node.status` for backward compatibility.
- `test_code_refs_extracted_to_column` — child `{{code_ref: ...}}` items -> `node.code_refs == ["src/file.py"]`, not tree nodes.
- `test_depends_on_resolved_to_node_refs` — `{{depends_on: [X](file.md#x)}}` -> `node_refs` row with `kind='depends_on'`, target resolved to node ID.
- `test_related_to_symmetric_query` — `related_to` queryable from both directions.
- `test_unresolvable_depends_on_allowed` — dangling link target -> no `node_refs` row, no error.
- `test_legacy_in_hyphen_progress_normalized` — `in-progress` -> stored as `in_progress`.
- `test_collapsed_not_in_markdown` — `collapsed` set in DB -> not serialized to `.md` file.
- `test_writer_round_trip` — parse -> write -> re-parse produces identical typed columns.

### Phase 10: Documentation

**Update `.plans/spec_db.md`:**
- Replace `node_metadata` table documentation with typed columns on `nodes`.
- Update `node_refs` documentation to include `kind` column.
- Update writer description to cover metadata re-serialization.

**Update `notes/python_backend_spec.md`:**
- Remove references to `node_metadata` table.
- Document typed columns and `node_refs.kind`.

---

## What does NOT change

| Component | Status |
|---|---|
| `edges` table | Unchanged |
| `files` table | Unchanged |
| `{{tree: [Title](./path.md)}}` expansion (replaces `[[...]]` wiki-link) | Updated — parser detects `{{tree: ...}}` metadata items; writer emits `{{tree: [Title](./path.md)}}` for cross-file edges |
| `sessions`, `messages`, `tool_calls`, `tool_results`, `questions`, `subagent_spawns` tables | Unchanged |
| `SpecDB` connection/snapshot logic | Unchanged |
| Node ID generation (UUID) | Unchanged |
| Anchor derivation (slugify title with metadata stripped) | Unchanged |
| `parse_list_items()` in `markdown.py` | Unchanged — still parses all list items; metadata filtering happens in `sync.py` |

---

## Execution Order

1. `spec_standards.md` — update conventions first so everything aligns
2. DB schema migration (`db.py`) — add columns, add `kind` to `node_refs`
3. Models (`models.py`) — add typed fields
4. Sync (`sync.py`) — metadata extraction + stripping
5. Writer (`writer.py`) — re-serialization
6. Handlers (`handlers.py`) — update RPC responses, add `setNodeCollapsed`
7. Rust UI (`state.rs`) — collapsed via RPC, read typed fields from payload
8. Example project — update status values
9. Tests — rewrite affected tests, add new ones
10. Documentation — update plans and notes
