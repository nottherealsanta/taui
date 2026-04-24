---
title: Tangle Parsing
last_updated: 2026-04-11
---

# Tangle Parsing

Parse tangle markdown documents into structured data — frontmatter, heading tree, code references, and inter-tangle links.

Depends on: [Tangle Module](../domains/tangle-module.md)

## Purpose

- Transform raw markdown tangle files into structured `TangleDetail` objects that the rest of the system can query, index, and display.
- Acts as the bridge between human-authored prose and machine-readable structure.

## User / Business Outcome

- Tangle files are standard markdown — no custom syntax, no learning curve.
  - Code references are automatically extracted and rendered inline in the UI.
  - Inter-tangle links are automatically discovered for navigation and dependency tracking.
- The heading tree provides a navigable document outline.

## Scope

- **In scope**
  - YAML frontmatter extraction (`title`, `last_updated`, plus any user-added fields)
  - Heading tree parsing (h1–h6 hierarchy with stable anchors)
  - Code reference extraction from body content (arrow and backtick notation)
  - Inter-tangle link extraction (markdown links to `tangles/` paths and bare paths)
  - Node ID generation (deterministic from file path + heading)
  - Line number tracking for each section
- **Out of scope**
  - Code reference resolution (verifying referenced files/symbols exist) — that is LSP's job
  - Tangle validation/verification — that is `taui/tangle/verification.py`
  - Writing tangles back to disk — that is `taui/tangle/writer.py`

## Constraints

- Only `title` and `last_updated` are expected in frontmatter; parser must handle any additional fields gracefully.
- Code ref patterns supported:
  - Arrow notation: `-> file:symbol` or `→ file:symbol`
  - Backtick notation: `` `file:symbol` `` or `` `file:line-range` ``
  - `taui/tangle/refs.py:ARROW_RE` and `taui/tangle/refs.py:BACKTICK_RE` — compiled regexes for each notation
- Tangle link patterns supported:
  - Markdown links: `[Name](tangles/path.md)`
  - Bare paths: `tangles/path.md` or `tangles/path.md#anchor`
- All paths are relative to project root.
- Parser must not fail on malformed documents — degrade gracefully.

## Design

- **Entry point** — `taui/tangle/parser.py:parse_tangle_document`
  - Inputs: `rel_path`, `content` (raw markdown string), `file_id`, `content_hash`, `mtime_ns`, `last_seen`
  - Returns a `TangleDetail` with:
    - `file: TangleFileMeta` — file metadata with title from frontmatter
    - `nodes: list[TangleNode]` — heading-based sections with body text and refs
    - `refs: list[TangleRef]` — all code references found in body
    - `links: list[TangleLink]` — all inter-tangle links found in body
    - `frontmatter: dict` — raw frontmatter key-value pairs
  - Output models: `taui/tangle/models.py:TangleDetail`, `taui/tangle/models.py:TangleNode`, `taui/tangle/models.py:TangleRef`, `taui/tangle/models.py:TangleLink`
- **Extraction pipeline**
  1. Split content into lines
  2. Parse YAML frontmatter → `taui/tangle/markdown.py:parse_yaml_frontmatter`
  3. Parse heading tree → `taui/tangle/markdown.py:parse_heading_tree`
     - Anchor generation: `taui/tangle/markdown.py:slugify`
  4. For each section, extract code refs → `taui/tangle/refs.py:extract_tangle_refs`
  5. Extract links from full document → `taui/tangle/parser.py:_extract_links` (with deduplication)
  6. Assemble into `TangleDetail`
- **Code reference regex patterns** (in `taui/tangle/refs.py`)
  - Arrow: `(?:->|→)\s*(\S+?:\S+)` — `taui/tangle/refs.py:ARROW_RE`
  - Backtick: `` `(\S+?:\S+?)` `` — `taui/tangle/refs.py:BACKTICK_RE`
- **Link regex patterns** (in `taui/tangle/parser.py:_extract_links`)
  - Markdown links: `\[([^\]]+)\]\((tangles/[^)]+)\)`
  - Bare paths: `(?<!\()(tangles/[\w./-]+\.md(?:#[\w-]+)?)`

## Tests / Verification

- `tests/test_tangle_parser.py` — 13 tests covering:
  - Frontmatter extraction, heading tree, code refs (arrow/backtick), markdown links, bare paths
  - Node IDs, depths, line numbers, empty docs, custom frontmatter fields
- `tests/test_tangle_refs.py` — 11 tests covering:
  - Arrow notation, unicode arrow, backtick notation, line ranges, multi-ref-per-line
  - Empty input, context capture, line number accuracy, nested paths, URL non-matching
- `tests/test_markdown_frontmatter.py` — frontmatter parsing edge cases
- Run: `pytest tests/test_tangle_parser.py tests/test_tangle_refs.py tests/test_markdown_frontmatter.py -q`

## Open Questions

- Should the parser extract code refs found inside fenced code blocks, or skip them?
- Should bare tangle paths inside fenced code blocks be excluded from link extraction?

## Related Decisions

- [Minimal Frontmatter](../decisions/0001-minimal-frontmatter.md)
