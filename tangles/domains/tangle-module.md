---
title: Tangle Module
last_updated: 2026-04-10
---

# Tangle Module

The core tangle subsystem: parsing, storage, sync, code reference extraction, and the data model for literate-programming documents.

Depends on: [Backend](backend.md)

## Responsibility

Owns the tangle document lifecycle — from markdown files on disk to structured data in SQLite and back. This is the heart of taui's literate programming model.

Specifically:

- Parse tangle markdown into structured models (frontmatter, heading tree, code refs, tangle links)
- Store parsed tangle data in SQLite (`tangle_files`, `tangle_nodes`, `tangle_refs`, `tangle_links` tables)
- Sync filesystem changes to the database (detect new/changed/deleted files)
- Extract code references from body content using arrow (`->`) and backtick notation
- Extract inter-tangle links from markdown links and bare paths
- Write tangle models back to markdown files on disk
- CRUD operations on tangle nodes (create, read, update, indent, outdent)

Does **not** own:

- Agent sessions or message history (owned by `taui/agent/` via `agent_db.py`)
- UI state or settings (owned by server via `settings.json`)
- LLM communication (owned by `taui/llms/`)

## Invariants

- A tangle file requires only `title` and `last_updated` in frontmatter. All other structure is body content.
- All file paths are relative to the project root.
- Code references use two patterns: arrow notation (`-> file:symbol`) and backtick notation (`` `file:symbol` ``).
- Tangle links use standard markdown links (`[Name](tangles/path.md)`) or bare paths (`tangles/path.md`).
- The parser extracts refs and links from body content, not from frontmatter.
- `index.md` is the root entry point (replaces legacy `_main.md` / `main.md`).

## Interfaces

- `taui/tangle/service.py:TangleService` — high-level API for all tangle operations
- `taui/tangle/parser.py:parse_tangle_document` — parse markdown string into `TangleDetail`
- `taui/tangle/refs.py:extract_tangle_refs` — extract code refs from body lines
- `taui/tangle/db.py:SpecDB` (alias `TangleDB`) — SQLite database operations
- `taui/tangle/sync.py:TangleSync` — filesystem-to-DB sync
- `taui/tangle/writer.py:TangleMarkdownWriter` — write models back to disk

## Key Components

- **Models** (`taui/tangle/models.py`) — `TangleFileMeta`, `TangleNode`, `TangleDetail`, `TangleRef`, `TangleLink` plus legacy `Spec*` aliases -> `taui/tangle/models.py:TangleFileMeta`
- **Database** (`taui/tangle/db.py`) — In-memory SQLite with disk snapshot, both legacy and tangle-v2 tables (1140 lines) -> `taui/tangle/db.py:SpecDB`
- **Parser** (`taui/tangle/parser.py`) — Frontmatter + heading tree + ref/link extraction -> `taui/tangle/parser.py:parse_tangle_document`
- **Refs** (`taui/tangle/refs.py`) — Arrow and backtick code reference extraction -> `taui/tangle/refs.py:extract_tangle_refs`
- **Writer** (`taui/tangle/writer.py`) — Debounced async markdown writeback -> `taui/tangle/writer.py:SpecMarkdownWriter`
- **Service** (`taui/tangle/service.py`) — High-level CRUD, init, sync orchestration -> `taui/tangle/service.py:SpecService`
- **Sync** (`taui/tangle/sync.py`) — Full filesystem scan, parse, upsert, stale deletion -> `taui/tangle/sync.py:SpecSync`
- **Markdown Utils** (`taui/tangle/markdown.py`) — Slugify, frontmatter parsing, heading tree, list parsing -> `taui/tangle/markdown.py:parse_yaml_frontmatter`
- **Errors** (`taui/tangle/errors.py`) — `TangleServiceError`, `TangleNotFoundError`, `TangleValidationError` -> `taui/tangle/errors.py:TangleServiceError`
- **Verification** (`taui/tangle/verification.py`) — Directive-based compliance checking -> `taui/tangle/verification.py:SpecVerifier`

### Migration Artifacts (to be cleaned up)

- `agent_db.py` — Agent history DB, belongs in `taui/agent/` not `taui/tangle/`
- `history_store.py` — Facade over `AgentHistoryDB`, belongs in `taui/agent/`
- Legacy `Spec*` aliases throughout — backward compat shims for the `spec -> tangle` rename
- Dual-write in `sync.py` — populates both legacy tables and tangle-v2 tables
- `_main.md` / `main.md` fallback in sync — should prefer `index.md` only

## Code References

- `taui/tangle/__init__.py`
- `taui/tangle/models.py`
- `taui/tangle/db.py`
- `taui/tangle/parser.py`
- `taui/tangle/refs.py`
- `taui/tangle/writer.py`
- `taui/tangle/service.py`
- `taui/tangle/sync.py`
- `taui/tangle/markdown.py`
- `taui/tangle/errors.py`
- `taui/tangle/verification.py`
- `taui/tangle/agent_db.py`
- `taui/tangle/history_store.py`

## Verification

- `tests/test_tangle_parser.py` — 13 tests: frontmatter, headings, code refs, links, node IDs, depths, line numbers
- `tests/test_tangle_refs.py` — 11 tests: arrow, backtick, line ranges, multi-ref, context, URL filtering
- `tests/test_tangle_db.py` — DB lifecycle, file upsert/tracking (legacy schema only; tangle-v2 tables not yet tested)
- `tests/test_tangle_service.py` — Service CRUD (still tests old `SpecService` with list-based format; not yet ported to tangle format)
- `tests/test_tangle_writer.py` — Markdown writeback (still tests legacy writer; not yet ported)
- `tests/test_markdown_frontmatter.py` — Frontmatter parsing edge cases

```
pytest tests/test_tangle_parser.py tests/test_tangle_refs.py tests/test_tangle_db.py tests/test_tangle_service.py -q
```

## Open Questions

- Should `agent_db.py` and `history_store.py` move to `taui/agent/` or a new `taui/storage/` module?
- When should the legacy `Spec*` aliases be removed? (requires updating all call sites in server + agent)
- Should the dual-write sync be collapsed to tangle-v2 only?
- `SpecVerifier` in `verification.py` is not exported from `__init__.py` and not renamed to `TangleVerifier` — fix?

## Related Features

- [Tangle Parsing](../features/tangle-parsing.md)
- [Tangle Sync](../features/tangle-sync.md)

## Related Decisions

- [Minimal Frontmatter](../decisions/0001-minimal-frontmatter.md)
