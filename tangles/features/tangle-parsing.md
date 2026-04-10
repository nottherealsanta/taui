---
title: Tangle Parsing
last_updated: 2026-04-10
---

# Tangle Parsing

Parse tangle markdown documents into structured data — frontmatter, heading tree, code references, and inter-tangle links.

Depends on: [Tangle Module](../domains/tangle-module.md)

## Purpose

Transform raw markdown tangle files into structured `TangleDetail` objects that the rest of the system can query, index, and display. This is the bridge between human-authored prose and machine-readable structure.

## User / Business Outcome

- Tangle files are standard markdown — no custom syntax, no learning curve.
- Code references are automatically extracted and rendered inline in the UI.
- Inter-tangle links are automatically discovered for navigation and dependency tracking.
- The heading tree provides a navigable document outline.

## Scope

In scope:
- YAML frontmatter extraction (`title`, `last_updated`, plus any user-added fields)
- Heading tree parsing (h1-h6 hierarchy with stable anchors)
- Code reference extraction from body content (arrow and backtick notation)
- Inter-tangle link extraction (markdown links to `tangles/` paths and bare paths)
- Node ID generation (deterministic from file path + heading)
- Line number tracking for each section

Out of scope:
- Code reference resolution (verifying that referenced files/symbols exist) — that's LSP's job
- Tangle validation/verification — that's `taui/tangle/verification.py`
- Writing tangles back to disk — that's `taui/tangle/writer.py`

## Constraints

- Only `title` and `last_updated` are expected in frontmatter. Parser must handle any additional fields gracefully.
- Code ref patterns: `-> file:symbol`, `` `file:symbol` ``, `-> file:line-range`, `` `file:line-range` ``
- Tangle link patterns: `[Name](tangles/path.md)`, `tangles/path.md`, `tangles/path.md#anchor`
- All paths are relative to project root.
- Parser must not fail on malformed documents — degrade gracefully.

## Design

### Entry Point

`taui/tangle/parser.py:parse_tangle_document` takes:
- `rel_path` — relative path of the tangle file
- `content` — raw markdown string
- `file_id`, `content_hash`, `mtime_ns`, `last_seen` — file tracking metadata

Returns a `TangleDetail` with:
- `file: TangleFileMeta` — file metadata with title from frontmatter
- `nodes: list[TangleNode]` — heading-based sections with body text and refs
- `refs: list[TangleRef]` — all code references found in body
- `links: list[TangleLink]` — all inter-tangle links found in body
- `frontmatter: dict` — raw frontmatter key-value pairs

### Extraction Pipeline

1. Split content into lines
2. Parse YAML frontmatter -> `taui/tangle/markdown.py:parse_yaml_frontmatter`
3. Parse heading tree -> `taui/tangle/markdown.py:parse_heading_tree`
4. For each section, extract code refs -> `taui/tangle/refs.py:extract_tangle_refs`
5. Extract links from full document -> `taui/tangle/parser.py:_extract_links`
6. Assemble into `TangleDetail`

### Code Reference Patterns

```python
# Arrow notation: -> or → followed by file:symbol
ARROW_RE = re.compile(r'(?:->|→)\s*(\S+?:\S+)')

# Backtick notation: `file:symbol`
BACKTICK_RE = re.compile(r'`(\S+?:\S+?)`')
```

### Link Patterns

```python
# Markdown links: [text](tangles/...)
MD_LINK_RE = re.compile(r'\[([^\]]+)\]\((tangles/[^)]+)\)')

# Bare paths: tangles/path.md or tangles/path.md#anchor
BARE_LINK_RE = re.compile(r'(?<!\()(tangles/[\w./-]+\.md(?:#[\w-]+)?)')
```

## Code References

- `taui/tangle/parser.py:parse_tangle_document` — main entry point
- `taui/tangle/parser.py:_extract_links` — link extraction with deduplication
- `taui/tangle/refs.py:extract_tangle_refs` — code ref extraction
- `taui/tangle/refs.py:ARROW_RE` — arrow notation regex
- `taui/tangle/refs.py:BACKTICK_RE` — backtick notation regex
- `taui/tangle/markdown.py:parse_yaml_frontmatter` — frontmatter parser
- `taui/tangle/markdown.py:parse_heading_tree` — heading hierarchy builder
- `taui/tangle/markdown.py:slugify` — anchor generation
- `taui/tangle/models.py:TangleDetail` — output model
- `taui/tangle/models.py:TangleNode` — section model
- `taui/tangle/models.py:TangleRef` — code ref model
- `taui/tangle/models.py:TangleLink` — link model

## Tests / Verification

- `tests/test_tangle_parser.py` — 13 tests covering frontmatter, headings, code refs (arrow/backtick), markdown links, bare paths, node IDs, depths, line numbers, empty docs, custom frontmatter
- `tests/test_tangle_refs.py` — 11 tests covering arrow, unicode arrow, backtick, line ranges, multi-ref-per-line, empty input, context capture, line number accuracy, nested paths, URL non-matching
- `tests/test_markdown_frontmatter.py` — frontmatter parsing edge cases

```
pytest tests/test_tangle_parser.py tests/test_tangle_refs.py tests/test_markdown_frontmatter.py -q
```

## Open Questions

- Should the parser support code refs in fenced code blocks (currently it would extract them — should it skip them)?
- Should bare tangle paths inside fenced code blocks be excluded from link extraction?

## Related Decisions

- [Minimal Frontmatter](../decisions/0001-minimal-frontmatter.md)
