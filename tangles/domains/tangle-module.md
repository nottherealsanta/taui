---
title: Tangle Module
last_updated: 2026-04-11
---

# Tangle Module

The core tangle subsystem: parsing, storage, sync, code reference extraction, and the data model for literate-programming documents.

Depends on: [Backend](backend.md)

## Responsibility

Owns the tangle document lifecycle — from markdown files on disk to structured data in SQLite and back. This is the heart of taui's literate programming model.

- **Entry point** — `taui/tangle/service.py:SpecService` orchestrates all subsystems
  - Database layer: `taui/tangle/db.py:SpecDB`
  - Filesystem sync: `taui/tangle/sync.py:SpecSync`
  - Markdown writer: `taui/tangle/writer.py:SpecMarkdownWriter`
- **Parsing** — `taui/tangle/parser.py:parse_tangle_document` returns a `taui/tangle/models.py:TangleDetail` aggregate (file metadata, node tree, refs, links, frontmatter)
- **Storage** — SQLite tables `tangle_files`, `tangle_nodes`, `tangle_refs`, `tangle_links` via `taui/tangle/db.py:SpecDB`
  - Write path: `upsert_tangle_file` → `replace_tangle_nodes` → `update_tangle_coordinates`
- **Sync** — filesystem-to-DB sync via `taui/tangle/sync.py:SpecSync.full_sync`
  - Detects new/changed/deleted files using `content_hash` and `mtime_ns`
- **Code reference extraction** — arrow (`->`) and backtick notation via `taui/tangle/refs.py:extract_tangle_refs`
- **Inter-tangle link extraction** — markdown links and bare paths via `taui/tangle/parser.py:_extract_links`
- **Writeback** — node trees serialised back to markdown via `taui/tangle/writer.py:SpecMarkdownWriter.write_file` with debouncing
- **CRUD operations** — create, read, update, indent, outdent via `taui/tangle/service.py:SpecService`
- **Verification** — directive-based compliance checking via `taui/tangle/verification.py:SpecVerifier.verify_node`

Does **not** own:
- Agent sessions or message history (owned by `taui/agent/` via `agent_db.py`)
- UI state or settings (owned by server via `settings.json`)
- LLM communication (owned by `taui/llms/`)

## Invariants

- A tangle file requires only `title` and `last_updated` in frontmatter
  - Frontmatter parsed by `taui/tangle/markdown.py:parse_yaml_frontmatter`
- All file paths in `taui/tangle/models.py:TangleFileMeta` (`rel_path` field) are relative to the project root
- `taui/tangle/models.py:TangleFileMeta` tracks `content_hash` and `mtime_ns` so `SpecSync.full_sync` can skip unchanged files
- Code references use two patterns, both extracted by `taui/tangle/refs.py:extract_tangle_refs`
  - Arrow notation (`-> file:symbol`) matched by `taui/tangle/refs.py:ARROW_RE`
  - Backtick notation (`` `file:symbol` ``) matched by `taui/tangle/refs.py:BACKTICK_RE`
- Tangle links use two patterns, both extracted by `taui/tangle/parser.py:_extract_links` with deduplication
  - Standard markdown links (`[Name](tangles/path.md)`) matched by `taui/tangle/parser.py:MD_LINK_RE`
  - Bare paths (`tangles/path.md`) matched by `taui/tangle/parser.py:BARE_LINK_RE`
- The parser extracts refs and links from body content only — never from frontmatter
- `taui/tangle/models.py:TangleNode` records `start_line` and `end_line` for inline code references pointing to exact line ranges
- `index.md` is the root entry point (replaces legacy `_main.md` / `main.md`); format identified by `taui/tangle/sync.py:SpecSync._detect_format`
- Node tree ordering maintained by `sort_order` and `depth` on `taui/tangle/models.py:TangleNode`
  - Computed by `taui/tangle/sync.py:SpecSync._compute_tree_coordinates`, persisted by `taui/tangle/db.py:SpecDB.update_tangle_coordinates`
- Validation failures surface as typed errors from `taui/tangle/errors.py`: `TangleServiceError` (base), `TangleNotFoundError`, `TangleValidationError`

## Interfaces

- `taui/tangle/service.py:SpecService` — high-level API for all tangle operations
  - `get_tree` — flat ordered node list; `get_node` — single node lookup
  - `update_node` — body/heading patch; `create_sibling_node` — insert after a node
  - `indent_node` / `outdent_node` — tree restructure; `init` — startup sync
- `taui/tangle/parser.py:parse_tangle_document` — parses a markdown string into a `taui/tangle/models.py:TangleDetail`; used by `SpecSync` and tests directly
- `taui/tangle/refs.py:extract_tangle_refs` — extracts `taui/tangle/models.py:TangleRef` records from body text lines; called per node by `parse_tangle_document`
- `taui/tangle/db.py:SpecDB` (alias `TangleDB`) — SQLite operations; read path is `get_tangle_tree` and `get_tangle_detail`
- `taui/tangle/sync.py:SpecSync` — filesystem-to-DB sync; `full_sync` walks the tangle directory and calls `delete_missing_tangle_files` to prune stale records
- `taui/tangle/writer.py:SpecMarkdownWriter` — writes `TangleNode` trees back to disk via `write_file`

## Key Components

- **Models** (`taui/tangle/models.py`) — core data types across all layers
  - `taui/tangle/models.py:TangleFileMeta` (lines 113–121) — file-level record: `file_id`, `rel_path`, `title`, `content_hash`, `mtime_ns`, `depth`, `sort_order`, `last_seen`
  - `taui/tangle/models.py:TangleNode` (lines 139–149) — heading section: `node_id`, `file_id`, `heading`, `depth`, `body`, `sort_order`, `start_line`, `end_line`
  - `taui/tangle/models.py:TangleRef` (lines 124–129) — extracted code ref: `ref_id`, `file_id`, `node_id`, `target`, `kind`, `context`, `line_number`
  - `taui/tangle/models.py:TangleLink` (lines 132–136) — inter-tangle link: `link_id`, `file_id`, `source_node_id`, `target_path`, `anchor`, `display_text`
  - `taui/tangle/models.py:TangleDetail` (lines 152–158) — parser output aggregate: `file`, `nodes`, `refs`, `links`, `frontmatter`
  - Legacy backward-compat aliases: `SpecFile` (lines 10–17), `SpecNode` (lines 20–49), `SpecNodeDetail` (lines 52–65), `SpecNodePatch` (lines 82–110)

- **Database** (`taui/tangle/db.py`) — in-memory SQLite with disk snapshot; `taui/tangle/db.py:SpecDB` (lines 101–1137)
  - Tangle-v2 write path: `upsert_tangle_file` (539–566) → `replace_tangle_nodes` (568–622) → `update_tangle_coordinates` (722–740)
  - Read path: `get_tangle_tree` (635–645) — flat ordered list; `get_tangle_detail` (647–703) — full detail with refs and links
  - Pruning: `delete_missing_tangle_files` (705–720)
  - Legacy methods still active: `upsert_file` (154–184), `get_tree` (223–254), `get_node` (267–292)

- **Parser** (`taui/tangle/parser.py`) — stateless markdown parser; 112 lines
  - `taui/tangle/parser.py:parse_tangle_document` (lines 15–84) — parses frontmatter via `taui/tangle/markdown.py:parse_yaml_frontmatter`, builds heading tree via `parse_heading_tree`, calls `extract_tangle_refs` per node body
  - `taui/tangle/parser.py:_extract_links` (lines 87–112) — scans body for markdown and bare-path links, deduplicates by `(target_path, anchor)`
  - `taui/tangle/parser.py:MD_LINK_RE` (line 11), `taui/tangle/parser.py:BARE_LINK_RE` (line 12)

- **Refs** (`taui/tangle/refs.py`) — code reference extractor; 25 lines
  - `taui/tangle/refs.py:extract_tangle_refs` (lines 12–25) — scans body lines and returns `TangleRef` records
  - `taui/tangle/refs.py:ARROW_RE` (line 8) — matches `-> file:symbol` or `-> file:line`
  - `taui/tangle/refs.py:BACKTICK_RE` (line 9) — matches `` `file:symbol` ``

- **Writer** (`taui/tangle/writer.py`) — async debounced markdown writeback; 262 lines
  - `taui/tangle/writer.py:SpecMarkdownWriter` (lines 14–259) — serialises a node tree back to disk
  - `write_file` (lines 47–122) — validates and routes to format-specific writer
  - `_write_file_standard` (lines 150–208) — renders heading-tree format to markdown string
  - `_debounced_write` (lines 126–148) — coalesces rapid successive writes to avoid thrashing the filesystem

- **Service** (`taui/tangle/service.py`) — high-level CRUD and orchestration; 675 lines
  - `taui/tangle/service.py:SpecService` (lines 21–672) — primary API surface consumed by server routes
  - `init` (46–143) — startup: runs `SpecSync.full_sync`, initialises `SpecMarkdownWriter`
  - `get_tree` (145–168), `get_node` (170–177)
  - `update_node` (191–262) — patches heading/body, re-parses refs, persists, triggers writer
  - `create_sibling_node` (339–448), `indent_node` (450–553), `outdent_node` (555–671)

- **Sync** (`taui/tangle/sync.py`) — filesystem scanner; 695 lines
  - `taui/tangle/sync.py:SpecSync` (lines 65–691)
  - `full_sync` (71–277) — walks the tangle directory; per file: `parse_tangle_document` → `upsert_tangle_file` + `replace_tangle_nodes` → `delete_missing_tangle_files`
  - `_compute_tree_coordinates` (282–346) — assigns `sort_order` and `depth` across the full file tree
  - `_detect_format` (348–353) — heuristic distinguishing standard heading-tree from legacy list-based files
  - `_parse_nodes_standard` (355–460) — extracts `ParsedNode` records from a heading-tree file
  - `taui/tangle/sync.py:ParsedFile` (lines 25–37), `taui/tangle/sync.py:ParsedNode` (lines 40–55) — intermediate representations before DB write

- **Markdown Utils** (`taui/tangle/markdown.py`) — low-level markdown primitives; 372 lines
  - `taui/tangle/markdown.py:parse_yaml_frontmatter` (lines 150–197) — splits `---` delimited frontmatter from body, returns `(dict, str)`
  - `taui/tangle/markdown.py:parse_heading_tree` (lines 200–250) — flat heading list to depth-annotated tree
  - `taui/tangle/markdown.py:extract_headings` (lines 134–147) — ATX heading scanner returning `(level, text, line_number)` tuples
  - `taui/tangle/markdown.py:slugify` (lines 37–49) — normalises heading to URL-safe slug for node IDs and anchors

- **Errors** (`taui/tangle/errors.py`) — typed exception hierarchy; 21 lines
  - `taui/tangle/errors.py:TangleServiceError` (line 7) — base exception
  - `taui/tangle/errors.py:TangleNotFoundError` (line 11) — missing node or file
  - `taui/tangle/errors.py:TangleValidationError` (line 15) — bad input (empty body, invalid heading, etc.)

- **Verification** (`taui/tangle/verification.py`) — directive-based compliance checking; 253 lines
  - `taui/tangle/verification.py:SpecVerifier` (lines 87–253) — checks that code matches directives embedded in tangle nodes
  - `verify_node` (lines 113–156) — entry point; reads directives from a node's body and dispatches to `_check_directive`
  - `_check_directive` (lines 158–253) — evaluates a single directive against the live codebase
  - `taui/tangle/verification.py:VerificationResult` (lines 20–36) — result record: `passed`, `message`, `directive`, `node_id`
  - `taui/tangle/verification.py:DirectiveType` enum (lines 39–55) — supported directive kinds (e.g. `exists`, `contains`, `matches`)

### Migration Artifacts (to be cleaned up)

- `agent_db.py` — agent history DB; belongs in `taui/agent/` not `taui/tangle/`
- `history_store.py` — facade over `AgentHistoryDB`; belongs in `taui/agent/`
- Legacy `SpecFile`, `SpecNode`, `SpecNodeDetail`, `SpecNodePatch` aliases in `taui/tangle/models.py` — backward-compat shims; all call sites in server + agent must be migrated before removal
- Dual-write in `taui/tangle/sync.py:SpecSync.full_sync` — populates both legacy tables (`upsert_file`) and tangle-v2 tables (`upsert_tangle_file`); should collapse to tangle-v2 only
- `_main.md` / `main.md` fallback in `SpecSync._detect_format` — should prefer `index.md` exclusively
- `taui/tangle/verification.py:SpecVerifier` not exported from `taui/tangle/__init__.py` and not yet renamed to `TangleVerifier`

## Verification

- `tests/test_tangle_parser.py` — 13 tests: frontmatter, headings, code refs, links, node IDs, depths, line numbers
  - Exercises `taui/tangle/parser.py:parse_tangle_document` directly
- `tests/test_tangle_refs.py` — 11 tests: arrow, backtick, line ranges, multi-ref, context, URL filtering
  - Exercises `taui/tangle/refs.py:extract_tangle_refs` with `ARROW_RE` and `BACKTICK_RE`
- `tests/test_tangle_db.py` — DB lifecycle, file upsert/tracking via `taui/tangle/db.py:SpecDB` (legacy schema only; tangle-v2 tables not yet tested)
- `tests/test_tangle_service.py` — service CRUD via `taui/tangle/service.py:SpecService` (still tests old list-based format; not yet ported)
- `tests/test_tangle_writer.py` — markdown writeback via `taui/tangle/writer.py:SpecMarkdownWriter` (still tests legacy writer)
- `tests/test_markdown_frontmatter.py` — frontmatter parsing edge cases via `taui/tangle/markdown.py:parse_yaml_frontmatter`

```
pytest tests/test_tangle_parser.py tests/test_tangle_refs.py tests/test_tangle_db.py tests/test_tangle_service.py -q
```

## Open Questions

- Should `agent_db.py` and `history_store.py` move to `taui/agent/` or a new `taui/storage/` module?
- When should the legacy `SpecFile`, `SpecNode`, `SpecNodeDetail`, `SpecNodePatch` aliases be removed? (requires updating all call sites in server + agent)
- Should the dual-write in `taui/tangle/sync.py:SpecSync.full_sync` be collapsed to tangle-v2 only?
- `taui/tangle/verification.py:SpecVerifier` is not exported from `taui/tangle/__init__.py` and not renamed to `TangleVerifier` — fix?

## Related Features

- [Tangle Parsing](../features/tangle-parsing.md)
- [Tangle Sync](../features/tangle-sync.md)

## Related Decisions

- [Minimal Frontmatter](../decisions/0001-minimal-frontmatter.md)
