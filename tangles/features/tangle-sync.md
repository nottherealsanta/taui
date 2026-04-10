---
title: Tangle Sync
last_updated: 2026-04-10
---

# Tangle Sync

Filesystem-to-database synchronization for tangle documents.

Depends on: [Tangle Module](../domains/tangle-module.md)

## Purpose

Keep the SQLite database in sync with the tangle markdown files on disk. Detects new, changed, and deleted files, parses them, and updates the database accordingly.

## User / Business Outcome

- Users edit tangle files in any editor — changes are automatically reflected in the taui UI.
- Taui starts up and indexes all existing tangle files without manual intervention.
- Deleted files are cleaned up from the database.
- The tangle tree in the UI always reflects the current filesystem state.

## Scope

In scope:
- Full filesystem scan of the tangles directory
- Detect new files, changed files (by content hash + mtime), and deleted files
- Parse each changed file into structured data (frontmatter, nodes, refs, links)
- Upsert file records, nodes, refs, and links into SQLite
- Delete stale file records for removed files
- Compute tree coordinates (depth + sort_order) from root entry point
- Populate both legacy tables and tangle-v2 tables (transitional dual-write)

Out of scope:
- Live filesystem watching (sync is triggered on startup and periodically, not via inotify)
- Conflict resolution for concurrent edits
- Write-back (sync is one-directional: disk -> DB; write-back is `writer.py`)

## Constraints

- Sync must handle both legacy list-based format and new heading-based tangle format.
- `index.md` is the root entry point for tree coordinate computation. Falls back to `main.md` / `_main.md` for legacy compat.
- File identity is tracked by `rel_path` (relative to project root).
- Content change detection uses `content_hash` (sha256 of file content) + `mtime_ns`.

## Design

### Sync Flow

1. Scan all `*.md` files under the tangles directory
2. For each file:
   a. Check if file is new or changed (hash/mtime comparison)
   b. If changed, parse into structured data -> `taui/tangle/sync.py:SpecSync.full_sync`
   c. Upsert file record into `tangle_files` table
   d. Replace nodes, refs, links for this file
3. Delete file records for files no longer on disk
4. Compute tree coordinates by DFS from root entry point
5. (Transitional) Also populate legacy `files`/`nodes`/`edges` tables

### Format Detection

-> `taui/tangle/sync.py:SpecSync._detect_format`

Checks if the first 5 lines contain `---` (YAML frontmatter marker). If yes -> standard (heading-based) format. If no -> legacy (list-based) format.

### Tree Coordinate Computation

-> `taui/tangle/sync.py:SpecSync._compute_tree_coordinates`

DFS traversal starting from the root entry point (`index.md`). Assigns `depth` and `sort_order` to each file for ordered display in the sidebar tree.

## Code References

- `taui/tangle/sync.py:SpecSync` — main sync class
- `taui/tangle/sync.py:SpecSync.full_sync` — complete sync operation
- `taui/tangle/sync.py:SpecSync._parse_nodes_standard` — heading-based parser
- `taui/tangle/sync.py:SpecSync._detect_format` — format detection
- `taui/tangle/sync.py:SpecSync._compute_tree_coordinates` — tree ordering
- `taui/tangle/sync.py:ParsedFile` — intermediate parse result
- `taui/tangle/sync.py:ParsedNode` — intermediate node result
- `taui/tangle/db.py:SpecDB.upsert_tangle_file` — file upsert
- `taui/tangle/db.py:SpecDB.replace_tangle_nodes` — node replacement
- `taui/tangle/db.py:SpecDB.delete_missing_tangle_files` — stale file cleanup

## Tests / Verification

- `tests/test_tangle_service.py` — Service-level sync tests (currently testing legacy format; needs porting to tangle format)
- `tests/test_tangle_db.py` — DB-level file upsert and tracking tests

```
pytest tests/test_tangle_service.py tests/test_tangle_db.py -q
```

## Open Questions

- When should the dual-write (legacy + tangle-v2) be collapsed to tangle-v2 only?
- Should sync support filesystem watching (inotify/FSEvents) for instant updates?
- The `_main.md` / `main.md` fallback in tree coordinate computation — when to remove?

## Related Decisions

No decisions recorded yet.
