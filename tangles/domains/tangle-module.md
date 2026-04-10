---
title: Tangle Module
last_updated: 2026-04-10
---

# Tangle Module

The core tangle subsystem: parsing, storage, sync, code reference extraction, and the data model for literate-programming documents.

Depends on: [Backend](backend.md)

## Responsibility

Owns the tangle document lifecycle — from markdown files on disk to structured data in SQLite and back. This is the heart of taui's literate programming model.

The entry point for most operations is `taui/tangle/service.py:SpecService`, which orchestrates the database layer (`taui/tangle/db.py:SpecDB`), the filesystem sync (`taui/tangle/sync.py:SpecSync`), and the markdown writer (`taui/tangle/writer.py:SpecMarkdownWriter`). Parsing is handled by `taui/tangle/parser.py:parse_tangle_document`, which returns a `taui/tangle/models.py:TangleDetail` aggregate containing the file metadata, node tree, refs, links, and frontmatter.

Specifically:

- Parse tangle markdown into structured models (`taui/tangle/models.py:TangleFileMeta`, `taui/tangle/models.py:TangleNode`, `taui/tangle/models.py:TangleRef`, `taui/tangle/models.py:TangleLink`) via `taui/tangle/parser.py:parse_tangle_document`
- Store parsed tangle data in SQLite (`tangle_files`, `tangle_nodes`, `tangle_refs`, `tangle_links` tables) via `taui/tangle/db.py:SpecDB` methods `upsert_tangle_file`, `replace_tangle_nodes`, and `delete_missing_tangle_files`
- Sync filesystem changes to the database (detect new/changed/deleted files) using `taui/tangle/sync.py:SpecSync.full_sync`
- Extract code references from body content using arrow (`->`) and backtick notation via `taui/tangle/refs.py:extract_tangle_refs`, driven by `taui/tangle/refs.py:ARROW_RE` and `taui/tangle/refs.py:BACKTICK_RE`
- Extract inter-tangle links from markdown links and bare paths via `taui/tangle/parser.py:_extract_links`, using `taui/tangle/parser.py:MD_LINK_RE` and `taui/tangle/parser.py:BARE_LINK_RE`
- Write tangle models back to markdown files on disk via `taui/tangle/writer.py:SpecMarkdownWriter.write_file`, which debounces writes through `taui/tangle/writer.py:SpecMarkdownWriter._debounced_write`
- CRUD operations on tangle nodes (create, read, update, indent, outdent) via `taui/tangle/service.py:SpecService.update_node`, `create_sibling_node`, `indent_node`, and `outdent_node`
- Tree coordinate management (sort order, depth) via `taui/tangle/db.py:SpecDB.update_tangle_coordinates` and `taui/tangle/sync.py:SpecSync._compute_tree_coordinates`
- Directive-based compliance checking via `taui/tangle/verification.py:SpecVerifier.verify_node` and `taui/tangle/verification.py:SpecVerifier._check_directive`

Does **not** own:

- Agent sessions or message history (owned by `taui/agent/` via `agent_db.py`)
- UI state or settings (owned by server via `settings.json`)
- LLM communication (owned by `taui/llms/`)

## Invariants

- A tangle file requires only `title` and `last_updated` in frontmatter. All other structure is body content. Frontmatter is parsed by `taui/tangle/markdown.py:parse_yaml_frontmatter`.
- All file paths stored in `taui/tangle/models.py:TangleFileMeta` (`rel_path` field) are relative to the project root.
- `taui/tangle/models.py:TangleFileMeta` tracks `content_hash` and `mtime_ns` so that `taui/tangle/sync.py:SpecSync.full_sync` can skip unchanged files without re-parsing.
- Code references use two patterns: arrow notation (`-> file:symbol`) matched by `taui/tangle/refs.py:ARROW_RE`, and backtick notation (`` `file:symbol` ``) matched by `taui/tangle/refs.py:BACKTICK_RE`. Both are extracted by `taui/tangle/refs.py:extract_tangle_refs`.
- Tangle links use standard markdown links (`[Name](tangles/path.md)`) matched by `taui/tangle/parser.py:MD_LINK_RE`, or bare paths (`tangles/path.md`) matched by `taui/tangle/parser.py:BARE_LINK_RE`. Both are extracted by `taui/tangle/parser.py:_extract_links` with deduplication.
- The parser (`taui/tangle/parser.py:parse_tangle_document`) extracts refs and links from body content only — never from frontmatter.
- `taui/tangle/models.py:TangleNode` records `start_line` and `end_line` so that inline code references in specs can point to exact line ranges.
- `index.md` is the root entry point (replaces legacy `_main.md` / `main.md`). The `taui/tangle/sync.py:SpecSync._detect_format` method identifies whether a file uses the standard heading-tree format.
- Node tree ordering is maintained by `sort_order` and `depth` fields on `taui/tangle/models.py:TangleNode`, computed by `taui/tangle/sync.py:SpecSync._compute_tree_coordinates` and persisted by `taui/tangle/db.py:SpecDB.update_tangle_coordinates`.
- Validation failures surface as typed errors from `taui/tangle/errors.py`: `TangleServiceError` (base), `TangleNotFoundError` (missing node/file), `TangleValidationError` (bad input).

## Interfaces

- `taui/tangle/service.py:SpecService` — high-level API for all tangle operations; methods include `get_tree` (returns flat node list), `get_node` (single node lookup), `update_node` (body/heading patch), `create_sibling_node` (insert after a node), `indent_node` / `outdent_node` (tree restructure), and `init` (startup sync)
- `taui/tangle/parser.py:parse_tangle_document` — parse a markdown string into a `taui/tangle/models.py:TangleDetail` containing file metadata, nodes, refs, and links; used by both `SpecSync` and tests directly
- `taui/tangle/refs.py:extract_tangle_refs` — extract `taui/tangle/models.py:TangleRef` records from body text lines; called by `parse_tangle_document` per node
- `taui/tangle/db.py:SpecDB` (alias `TangleDB`) — SQLite database operations; primary tangle-v2 write path is `upsert_tangle_file` → `replace_tangle_nodes` → `update_tangle_coordinates`; read path is `get_tangle_tree` and `get_tangle_detail`
- `taui/tangle/sync.py:SpecSync` — filesystem-to-DB sync; `full_sync` walks the tangle directory, calls `parse_tangle_document` per file, upserts via `SpecDB`, then calls `delete_missing_tangle_files` to prune stale records
- `taui/tangle/writer.py:SpecMarkdownWriter` — write `taui/tangle/models.py:TangleNode` trees back to disk via `write_file`, which dispatches to `_write_file_standard` and debounces through `_debounced_write`

## Key Components

- **Models** (`taui/tangle/models.py`) — Core data types used across all layers:
  - `taui/tangle/models.py:TangleFileMeta` (lines 113–121) — file-level record with `file_id`, `rel_path`, `title`, `content_hash`, `mtime_ns`, `depth`, `sort_order`, `last_seen`
  - `taui/tangle/models.py:TangleNode` (lines 139–149) — heading section with `node_id`, `file_id`, `heading`, `depth`, `body`, `sort_order`, `start_line`, `end_line`
  - `taui/tangle/models.py:TangleRef` (lines 124–129) — extracted code reference with `ref_id`, `file_id`, `node_id`, `target`, `kind`, `context`, `line_number`
  - `taui/tangle/models.py:TangleLink` (lines 132–136) — inter-tangle link with `link_id`, `file_id`, `source_node_id`, `target_path`, `anchor`, `display_text`
  - `taui/tangle/models.py:TangleDetail` (lines 152–158) — aggregate returned by `parse_tangle_document`: `file`, `nodes`, `refs`, `links`, `frontmatter`
  - Legacy aliases: `taui/tangle/models.py:SpecFile` (lines 10–17), `taui/tangle/models.py:SpecNode` (lines 20–49), `taui/tangle/models.py:SpecNodeDetail` (lines 52–65), `taui/tangle/models.py:SpecNodePatch` (lines 82–110) — backward compat shims for the `spec → tangle` rename

- **Database** (`taui/tangle/db.py`) — In-memory SQLite with disk snapshot; 1140 lines; the `taui/tangle/db.py:SpecDB` class (lines 101–1137) owns both legacy and tangle-v2 tables:
  - `taui/tangle/db.py:SpecDB.upsert_tangle_file` (lines 539–566) — insert or update a `TangleFileMeta` row
  - `taui/tangle/db.py:SpecDB.replace_tangle_nodes` (lines 568–622) — atomically replace all nodes for a file
  - `taui/tangle/db.py:SpecDB.get_tangle_tree` (lines 635–645) — return flat ordered node list for the tree view
  - `taui/tangle/db.py:SpecDB.get_tangle_detail` (lines 647–703) — return full `TangleDetail` for a single file including nodes, refs, and links
  - `taui/tangle/db.py:SpecDB.delete_missing_tangle_files` (lines 705–720) — prune files not seen in the last sync pass
  - `taui/tangle/db.py:SpecDB.update_tangle_coordinates` (lines 722–740) — write computed `sort_order` and `depth` back to the DB
  - Legacy methods still active: `taui/tangle/db.py:SpecDB.upsert_file` (lines 154–184), `taui/tangle/db.py:SpecDB.get_tree` (lines 223–254), `taui/tangle/db.py:SpecDB.get_node` (lines 267–292)

- **Parser** (`taui/tangle/parser.py`) — Stateless markdown parser; 112 lines:
  - `taui/tangle/parser.py:parse_tangle_document` (lines 15–84) — main entry point; parses frontmatter via `taui/tangle/markdown.py:parse_yaml_frontmatter`, builds heading tree via `taui/tangle/markdown.py:parse_heading_tree`, and calls `extract_tangle_refs` per node body
  - `taui/tangle/parser.py:_extract_links` (lines 87–112) — scans body text for markdown and bare-path links, deduplicates by `(target_path, anchor)`, returns `TangleLink` list
  - `taui/tangle/parser.py:MD_LINK_RE` (line 11) — regex matching `[text](path)` links
  - `taui/tangle/parser.py:BARE_LINK_RE` (line 12) — regex matching bare `tangles/…` paths

- **Refs** (`taui/tangle/refs.py`) — Code reference extractor; 25 lines:
  - `taui/tangle/refs.py:extract_tangle_refs` (lines 12–25) — scans body lines and returns `TangleRef` records for each matched pattern
  - `taui/tangle/refs.py:ARROW_RE` (line 8) — matches `-> file:symbol` or `-> file:line` notation
  - `taui/tangle/refs.py:BACKTICK_RE` (line 9) — matches `` `file:symbol` `` notation

- **Writer** (`taui/tangle/writer.py`) — Async debounced markdown writeback; 262 lines:
  - `taui/tangle/writer.py:SpecMarkdownWriter` (lines 14–259) — serializes a node tree back to disk
  - `taui/tangle/writer.py:SpecMarkdownWriter.write_file` (lines 47–122) — public API; validates and routes to format-specific writer
  - `taui/tangle/writer.py:SpecMarkdownWriter._write_file_standard` (lines 150–208) — renders heading-tree format to markdown string
  - `taui/tangle/writer.py:SpecMarkdownWriter._debounced_write` (lines 126–148) — coalesces rapid successive writes to avoid thrashing the filesystem

- **Service** (`taui/tangle/service.py`) — High-level CRUD and orchestration; 675 lines:
  - `taui/tangle/service.py:SpecService` (lines 21–672) — the primary API surface consumed by the server routes
  - `taui/tangle/service.py:SpecService.init` (lines 46–143) — startup: runs `SpecSync.full_sync`, initialises `SpecMarkdownWriter`
  - `taui/tangle/service.py:SpecService.get_tree` (lines 145–168) — delegates to `SpecDB.get_tangle_tree`; returns ordered node list
  - `taui/tangle/service.py:SpecService.get_node` (lines 170–177) — single node fetch via `SpecDB.get_tangle_detail`
  - `taui/tangle/service.py:SpecService.update_node` (lines 191–262) — patch heading/body, re-parse refs, persist, and trigger writer
  - `taui/tangle/service.py:SpecService.create_sibling_node` (lines 339–448) — insert a new node after a given sibling, recompute coordinates
  - `taui/tangle/service.py:SpecService.indent_node` (lines 450–553) — increase node depth within the tree, recompute coordinates
  - `taui/tangle/service.py:SpecService.outdent_node` (lines 555–671) — decrease node depth, recompute coordinates

- **Sync** (`taui/tangle/sync.py`) — Filesystem scanner; 695 lines:
  - `taui/tangle/sync.py:SpecSync` (lines 65–691) — drives the full sync pipeline
  - `taui/tangle/sync.py:SpecSync.full_sync` (lines 71–277) — walks the tangle directory; for each file calls `parse_tangle_document`, upserts via `SpecDB.upsert_tangle_file` + `replace_tangle_nodes`, then calls `delete_missing_tangle_files`
  - `taui/tangle/sync.py:SpecSync._compute_tree_coordinates` (lines 282–346) — assigns `sort_order` and `depth` values across the full file tree; called after all files are parsed
  - `taui/tangle/sync.py:SpecSync._detect_format` (lines 348–353) — heuristic to distinguish standard heading-tree files from legacy list-based files
  - `taui/tangle/sync.py:SpecSync._parse_nodes_standard` (lines 355–460) — extracts `ParsedNode` records from a heading-tree file
  - `taui/tangle/sync.py:ParsedFile` dataclass (lines 25–37) — intermediate representation of a parsed file before DB write
  - `taui/tangle/sync.py:ParsedNode` dataclass (lines 40–55) — intermediate representation of a parsed node before DB write

- **Markdown Utils** (`taui/tangle/markdown.py`) — Low-level markdown primitives; 372 lines:
  - `taui/tangle/markdown.py:parse_yaml_frontmatter` (lines 150–197) — splits `---` delimited frontmatter from body, returns `(dict, str)`
  - `taui/tangle/markdown.py:parse_heading_tree` (lines 200–250) — converts flat heading list into a depth-annotated tree structure
  - `taui/tangle/markdown.py:extract_headings` (lines 134–147) — scans markdown lines for ATX headings, returns `(level, text, line_number)` tuples
  - `taui/tangle/markdown.py:slugify` (lines 37–49) — normalises a heading string to a URL-safe slug used for node IDs and anchors

- **Errors** (`taui/tangle/errors.py`) — Typed exception hierarchy; 21 lines:
  - `taui/tangle/errors.py:TangleServiceError` (line 7) — base exception for all tangle service failures
  - `taui/tangle/errors.py:TangleNotFoundError` (line 11) — raised when a node or file cannot be found by ID or path
  - `taui/tangle/errors.py:TangleValidationError` (line 15) — raised on invalid input (bad heading, empty body, etc.)

- **Verification** (`taui/tangle/verification.py`) — Directive-based compliance checking; 253 lines:
  - `taui/tangle/verification.py:SpecVerifier` (lines 87–253) — checks that code matches directives embedded in tangle nodes
  - `taui/tangle/verification.py:SpecVerifier.verify_node` (lines 113–156) — entry point; reads directives from a node's body and dispatches to `_check_directive`
  - `taui/tangle/verification.py:SpecVerifier._check_directive` (lines 158–253) — evaluates a single directive against the live codebase
  - `taui/tangle/verification.py:VerificationResult` (lines 20–36) — result record with `passed`, `message`, `directive`, and `node_id`
  - `taui/tangle/verification.py:DirectiveType` enum (lines 39–55) — enumerates supported directive kinds (e.g. `exists`, `contains`, `matches`)

### Migration Artifacts (to be cleaned up)

- `agent_db.py` — Agent history DB, belongs in `taui/agent/` not `taui/tangle/`
- `history_store.py` — Facade over `AgentHistoryDB`, belongs in `taui/agent/`
- Legacy `taui/tangle/models.py:SpecFile`, `taui/tangle/models.py:SpecNode`, `taui/tangle/models.py:SpecNodeDetail`, `taui/tangle/models.py:SpecNodePatch` aliases throughout — backward compat shims for the `spec → tangle` rename; all call sites in server + agent must be migrated before removal
- Dual-write in `taui/tangle/sync.py:SpecSync.full_sync` — populates both legacy tables (via `taui/tangle/db.py:SpecDB.upsert_file`) and tangle-v2 tables (via `taui/tangle/db.py:SpecDB.upsert_tangle_file`); should collapse to tangle-v2 only
- `_main.md` / `main.md` fallback in `taui/tangle/sync.py:SpecSync._detect_format` — should prefer `index.md` exclusively
- `taui/tangle/verification.py:SpecVerifier` is not exported from `taui/tangle/__init__.py` and not yet renamed to `TangleVerifier`

## Code References

### Models (`taui/tangle/models.py`)

- `taui/tangle/models.py:TangleFileMeta` — file-level metadata record (lines 113–121): `file_id`, `rel_path`, `title`, `content_hash`, `mtime_ns`, `depth`, `sort_order`, `last_seen`
- `taui/tangle/models.py:TangleNode` — heading section node (lines 139–149): `node_id`, `file_id`, `heading`, `depth`, `body`, `sort_order`, `start_line`, `end_line`
- `taui/tangle/models.py:TangleRef` — extracted code reference (lines 124–129): `ref_id`, `file_id`, `node_id`, `target`, `kind`, `context`, `line_number`
- `taui/tangle/models.py:TangleLink` — inter-tangle link (lines 132–136): `link_id`, `file_id`, `source_node_id`, `target_path`, `anchor`, `display_text`
- `taui/tangle/models.py:TangleDetail` — parser output aggregate (lines 152–158): `file`, `nodes`, `refs`, `links`, `frontmatter`
- `taui/tangle/models.py:SpecFile` — legacy alias for `TangleFileMeta` (lines 10–17)
- `taui/tangle/models.py:SpecNode` — legacy alias for `TangleNode` (lines 20–49)
- `taui/tangle/models.py:SpecNodeDetail` — legacy alias for `TangleDetail` (lines 52–65)
- `taui/tangle/models.py:SpecNodePatch` — legacy patch request type (lines 82–110)

### Database (`taui/tangle/db.py`)

- `taui/tangle/db.py:SpecDB` — primary database class (lines 101–1137)
- `taui/tangle/db.py:SpecDB.upsert_tangle_file` — insert/update file record (lines 539–566)
- `taui/tangle/db.py:SpecDB.replace_tangle_nodes` — atomic node replacement for a file (lines 568–622)
- `taui/tangle/db.py:SpecDB.get_tangle_tree` — ordered node list for tree view (lines 635–645)
- `taui/tangle/db.py:SpecDB.get_tangle_detail` — full detail including refs and links (lines 647–703)
- `taui/tangle/db.py:SpecDB.delete_missing_tangle_files` — prune stale file records (lines 705–720)
- `taui/tangle/db.py:SpecDB.update_tangle_coordinates` — persist computed sort_order/depth (lines 722–740)
- `taui/tangle/db.py:SpecDB.upsert_file` — legacy file upsert (lines 154–184)
- `taui/tangle/db.py:SpecDB.get_tree` — legacy tree fetch (lines 223–254)
- `taui/tangle/db.py:SpecDB.get_node` — legacy single node fetch (lines 267–292)

### Parser (`taui/tangle/parser.py`)

- `taui/tangle/parser.py:parse_tangle_document` — main parser entry point (lines 15–84)
- `taui/tangle/parser.py:_extract_links` — link extraction with deduplication (lines 87–112)
- `taui/tangle/parser.py:MD_LINK_RE` — markdown link regex (line 11)
- `taui/tangle/parser.py:BARE_LINK_RE` — bare path regex (line 12)

### Refs (`taui/tangle/refs.py`)

- `taui/tangle/refs.py:extract_tangle_refs` — extracts code refs from body text (lines 12–25)
- `taui/tangle/refs.py:ARROW_RE` — arrow notation regex (line 8)
- `taui/tangle/refs.py:BACKTICK_RE` — backtick notation regex (line 9)

### Service (`taui/tangle/service.py`)

- `taui/tangle/service.py:SpecService` — high-level service class (lines 21–672)
- `taui/tangle/service.py:SpecService.init` — startup sync and writer init (lines 46–143)
- `taui/tangle/service.py:SpecService.get_tree` — ordered node list (lines 145–168)
- `taui/tangle/service.py:SpecService.get_node` — single node fetch (lines 170–177)
- `taui/tangle/service.py:SpecService.update_node` — heading/body patch (lines 191–262)
- `taui/tangle/service.py:SpecService.create_sibling_node` — insert after sibling (lines 339–448)
- `taui/tangle/service.py:SpecService.indent_node` — increase node depth (lines 450–553)
- `taui/tangle/service.py:SpecService.outdent_node` — decrease node depth (lines 555–671)

### Sync (`taui/tangle/sync.py`)

- `taui/tangle/sync.py:SpecSync` — filesystem sync class (lines 65–691)
- `taui/tangle/sync.py:SpecSync.full_sync` — full directory scan and upsert (lines 71–277)
- `taui/tangle/sync.py:SpecSync._compute_tree_coordinates` — sort_order/depth assignment (lines 282–346)
- `taui/tangle/sync.py:SpecSync._detect_format` — standard vs. legacy format heuristic (lines 348–353)
- `taui/tangle/sync.py:SpecSync._parse_nodes_standard` — heading-tree node extraction (lines 355–460)
- `taui/tangle/sync.py:ParsedFile` — intermediate file dataclass (lines 25–37)
- `taui/tangle/sync.py:ParsedNode` — intermediate node dataclass (lines 40–55)

### Writer (`taui/tangle/writer.py`)

- `taui/tangle/writer.py:SpecMarkdownWriter` — markdown writer class (lines 14–259)
- `taui/tangle/writer.py:SpecMarkdownWriter.write_file` — public write entry point (lines 47–122)
- `taui/tangle/writer.py:SpecMarkdownWriter._write_file_standard` — standard format renderer (lines 150–208)
- `taui/tangle/writer.py:SpecMarkdownWriter._debounced_write` — coalesced async write (lines 126–148)

### Markdown Utils (`taui/tangle/markdown.py`)

- `taui/tangle/markdown.py:parse_yaml_frontmatter` — frontmatter split and parse (lines 150–197)
- `taui/tangle/markdown.py:parse_heading_tree` — heading list to depth-annotated tree (lines 200–250)
- `taui/tangle/markdown.py:extract_headings` — ATX heading scanner (lines 134–147)
- `taui/tangle/markdown.py:slugify` — heading-to-slug normaliser (lines 37–49)

### Errors (`taui/tangle/errors.py`)

- `taui/tangle/errors.py:TangleServiceError` — base exception (line 7)
- `taui/tangle/errors.py:TangleNotFoundError` — missing node/file (line 11)
- `taui/tangle/errors.py:TangleValidationError` — bad input (line 15)

### Verification (`taui/tangle/verification.py`)

- `taui/tangle/verification.py:SpecVerifier` — compliance checker class (lines 87–253)
- `taui/tangle/verification.py:SpecVerifier.verify_node` — node-level verification entry point (lines 113–156)
- `taui/tangle/verification.py:SpecVerifier._check_directive` — single directive evaluator (lines 158–253)
- `taui/tangle/verification.py:VerificationResult` — result record (lines 20–36)
- `taui/tangle/verification.py:DirectiveType` — supported directive kinds enum (lines 39–55)

### Supporting Files

- `taui/tangle/__init__.py` — module exports (note: `SpecVerifier` not yet exported)
- `taui/tangle/agent_db.py` — agent history DB (migration artifact; belongs in `taui/agent/`)
- `taui/tangle/history_store.py` — facade over `AgentHistoryDB` (migration artifact; belongs in `taui/agent/`)

## Verification

- `tests/test_tangle_parser.py` — 13 tests: frontmatter, headings, code refs, links, node IDs, depths, line numbers; exercises `taui/tangle/parser.py:parse_tangle_document` directly
- `tests/test_tangle_refs.py` — 11 tests: arrow, backtick, line ranges, multi-ref, context, URL filtering; exercises `taui/tangle/refs.py:extract_tangle_refs` with `ARROW_RE` and `BACKTICK_RE`
- `tests/test_tangle_db.py` — DB lifecycle, file upsert/tracking via `taui/tangle/db.py:SpecDB` (legacy schema only; tangle-v2 tables not yet tested)
- `tests/test_tangle_service.py` — Service CRUD via `taui/tangle/service.py:SpecService` (still tests old list-based format; not yet ported to tangle format)
- `tests/test_tangle_writer.py` — Markdown writeback via `taui/tangle/writer.py:SpecMarkdownWriter` (still tests legacy writer; not yet ported)
- `tests/test_markdown_frontmatter.py` — Frontmatter parsing edge cases via `taui/tangle/markdown.py:parse_yaml_frontmatter`

```
pytest tests/test_tangle_parser.py tests/test_tangle_refs.py tests/test_tangle_db.py tests/test_tangle_service.py -q
```

## Open Questions

- Should `agent_db.py` and `history_store.py` move to `taui/agent/` or a new `taui/storage/` module?
- When should the legacy `taui/tangle/models.py:SpecFile`, `SpecNode`, `SpecNodeDetail`, `SpecNodePatch` aliases be removed? (requires updating all call sites in server + agent)
- Should the dual-write in `taui/tangle/sync.py:SpecSync.full_sync` (both `upsert_file` and `upsert_tangle_file`) be collapsed to tangle-v2 only?
- `taui/tangle/verification.py:SpecVerifier` is not exported from `taui/tangle/__init__.py` and not renamed to `TangleVerifier` — fix?

## Related Features

- [Tangle Parsing](../features/tangle-parsing.md)
- [Tangle Sync](../features/tangle-sync.md)

## Related Decisions

- [Minimal Frontmatter](../decisions/0001-minimal-frontmatter.md)
