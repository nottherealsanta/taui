---
title: Tangle Sync
last_updated: 2026-04-11
---

# Tangle Sync

Filesystem-to-database synchronization for tangle documents.

Depends on: [Tangle Module](../domains/tangle-module.md)

## Purpose

- Keep the SQLite database in sync with the tangle markdown files on disk.
- Detects new, changed, and deleted files, parses them, and updates the database accordingly.

## User / Business Outcome

- Users edit tangle files in any editor — changes are automatically reflected in the taui UI.
  - Taui starts up and indexes all existing tangle files without manual intervention.
  - Deleted files are cleaned up from the database.
- The tangle tree in the UI always reflects the current filesystem state.

## Scope

- **In scope**
  - Full filesystem scan of the tangles directory
  - Detect new files, changed files (by content hash + mtime), and deleted files
  - Parse each changed file into structured data (frontmatter, nodes, refs, links) via `taui/tangle/parser.py:parse_tangle_document`
  - Upsert file records, nodes, refs, and links into SQLite
    - `taui/tangle/db.py:SpecDB.upsert_tangle_file` — file upserts
    - `taui/tangle/db.py:SpecDB.replace_tangle_nodes` — node replacement
  - Delete stale file records for removed files via `taui/tangle/db.py:SpecDB.delete_missing_tangle_files`
  - Compute tree coordinates (depth + sort_order) from root entry point via `taui/tangle/sync.py:SpecSync._compute_tree_coordinates`
  - Transitional dual-write: populate both legacy tables and tangle-v2 tables
- **Out of scope**
  - Live filesystem watching (sync is triggered on startup and periodically, not via inotify/FSEvents)
  - Conflict resolution for concurrent edits
  - Write-back (sync is one-directional: disk → DB; write-back is `writer.py`)

## Constraints

- Sync must handle both legacy list-based format and new heading-based tangle format.
  - `taui/tangle/sync.py:SpecSync._detect_format` — checks first 5 lines for `---` YAML marker; yes → standard format, no → legacy format
- `index.md` is the root entry point for tree coordinate computation; falls back to `main.md` / `_main.md` for legacy compatibility.
- File identity is tracked by `rel_path` (relative to project root).
- Content change detection uses `content_hash` (SHA-256 of file content) + `mtime_ns`.

## Design

- **Sync flow** — `taui/tangle/sync.py:SpecSync.full_sync`
  1. Scan all `*.md` files under the tangles directory
  2. For each file, check if new or changed (hash/mtime comparison)
     - If changed: detect format → parse → upsert
     - `taui/tangle/sync.py:SpecSync._parse_nodes_standard` — builds `ParsedNode` entries for heading-based files
     - `taui/tangle/sync.py:ParsedFile` and `taui/tangle/sync.py:ParsedNode` — intermediate parse results
  3. Delete file records for files no longer on disk
     - `taui/tangle/db.py:SpecDB.delete_missing_tangle_files`
  4. Compute tree coordinates by DFS from root entry point
     - `taui/tangle/sync.py:SpecSync._compute_tree_coordinates` — assigns `depth` and `sort_order` to each file
     - `taui/tangle/db.py:SpecDB.get_tangle_tree` — reads current link graph for DFS traversal
     - `taui/tangle/db.py:SpecDB.update_tangle_coordinates` — persists depth/sort_order after DFS
  5. (Transitional) Also populate legacy `files`/`nodes`/`edges` tables
- **Format detection** — `taui/tangle/sync.py:SpecSync._detect_format`
  - Checks if first 5 lines contain `---` (YAML frontmatter marker)
  - Yes → standard (heading-based) format; No → legacy (list-based) format
- **Tree coordinate computation** — `taui/tangle/sync.py:SpecSync._compute_tree_coordinates`
  - DFS traversal starting from `index.md`
  - Assigns `depth` and `sort_order` for ordered display in the sidebar tree
- **Main sync class** — `taui/tangle/sync.py:SpecSync`

## Tests / Verification

- `tests/test_tangle_service.py` — service-level sync tests (currently testing legacy format; needs porting to tangle format)
- `tests/test_tangle_db.py` — DB-level file upsert and tracking tests
- Run: `pytest tests/test_tangle_service.py tests/test_tangle_db.py -q`

## Open Questions

- When should the dual-write (legacy + tangle-v2) be collapsed to tangle-v2 only?
- Should sync support filesystem watching (inotify/FSEvents) for instant updates?
- When should the `_main.md` / `main.md` fallback in tree coordinate computation be removed?

## Related Decisions

No decisions recorded yet.
