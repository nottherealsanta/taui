---
title: 0001 Minimal Frontmatter
last_updated: 2026-04-10
---

# 0001 Minimal Frontmatter

## Status

Active — implemented and in use.

## Context

The previous spec format pushed extensive structure into YAML frontmatter: `status`, `owners`, `refs`, `test_refs`, `depends_on`, `tags`, `code_refs`. This made the format rigid and opinionated. Every project had to conform to the same document structure regardless of domain.

Different teams need different document conventions — a game studio's tangles look different from a SaaS backend team's. Baking structure into frontmatter forces a one-size-fits-all approach.

Additionally, heavy frontmatter creates a maintenance burden: every structural change to the format requires updating the parser, the writer, the database schema, and the UI.

## Decision

Tangle frontmatter requires only two fields:

```yaml
---
title: User Registration
last_updated: 2026-04-07
---
```

Everything else — code references, dependencies, status, test refs, constraints — lives in the **body** as standard markdown content.

Document structure is controlled by the **tangle-making tool's system prompt**, not by the format specification. Users can edit this prompt in Settings -> Prompts -> Tangle Maker to change what sections agents produce.

The parser extracts structured data from body content using pattern matching:
- Code refs via arrow (`->`) and backtick notation
- Inter-tangle links via markdown links and bare paths
- Heading hierarchy for document structure

## Consequences

**Benefits:**
- Tangle format is maximally flexible — any markdown structure works.
- Different teams customize via prompt editing, not format changes.
- Parser is simpler — fewer frontmatter fields to validate and migrate.
- Writer is simpler — less structured data to serialize.
- No schema migrations when conventions change — just update the prompt.

**Trade-offs:**
- Less machine-readable structure out of the box — parser must infer from body patterns.
- Code refs extracted from body content are less precise than explicit frontmatter declarations.
- No built-in status field — status is body content, not queryable without parsing.
- New users may need guidance on what sections to include (mitigated by good default prompt).

**Mitigations:**
- Default `tangle_maker` prompt suggests standard sections (Behavior, Constraints, Dependencies, Code References, etc.)
- Parser uses well-defined regex patterns for code ref and link extraction
- UI renders code refs inline regardless of where they appear in the body

## Alternatives Considered

### 1. Rich frontmatter (previous approach)

```yaml
---
title: User Registration
status: active
owners: [alice, bob]
code_refs: [src/auth.py#register, src/models/user.py#User]
test_refs: [tests/test_auth.py#test_register]
depends_on: [specs/domains/data-layer.md]
tags: [auth, registration]
---
```

Rejected because: too rigid, too much maintenance overhead, forces all projects into the same structure.

### 2. No frontmatter at all

Rejected because: `title` and `last_updated` provide essential metadata that the UI and indexer need. Extracting title from the first heading is fragile. Having zero frontmatter would make it harder to distinguish tangle files from regular markdown.

### 3. Frontmatter with optional structured fields

```yaml
---
title: User Registration
last_updated: 2026-04-07
status: active       # optional
code_refs: [...]     # optional
---
```

Rejected because: "optional" frontmatter fields inevitably become expected. The parser still needs to handle them, migrations still need to support them, and teams argue about which optional fields to use.

## References

- [Tangle Standards](../standards.md) — full format specification
- [Tangle Module](../domains/tangle-module.md) — parser implementation
- [Tangle Parsing](../features/tangle-parsing.md) — parsing design and code refs
- [Editable Prompts](../features/editable-prompts.md) — how users customize structure
- `taui/tangle/parser.py:parse_tangle_document` — parser implementation
- `taui/tangle/refs.py:extract_tangle_refs` — code ref extraction
