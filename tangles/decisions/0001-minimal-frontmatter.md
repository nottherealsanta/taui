---
title: 0001 Minimal Frontmatter
last_updated: 2026-04-11
---

# 0001 Minimal Frontmatter

## Status

Active — implemented and in use.

## Context

- The previous format pushed extensive structure into YAML frontmatter
  - Fields: `status`, `owners`, `refs`, `test_refs`, `depends_on`, `tags`, `code_refs`
  - Made the format rigid and opinionated — every project had to conform to the same structure
- Different teams need different document conventions
  - A game studio's tangles look different from a SaaS backend team's
  - Baking structure into frontmatter forces a one-size-fits-all approach
- Heavy frontmatter creates a maintenance burden
  - Every structural change requires updating the parser, writer, database schema, and UI

## Decision

Tangle frontmatter requires only two fields:

```yaml
---
title: User Registration
last_updated: 2026-04-07
---
```

- Everything else — code references, dependencies, status, test refs, constraints — lives in the **body** as standard markdown content
- Document structure is controlled by the **tangle-making tool's system prompt**, not by the format specification
  - Users can edit this prompt in Settings → Prompts → Tangle Maker
- The parser extracts structured data from body content using pattern matching
  - Code refs via arrow (`->`) and backtick notation
  - Inter-tangle links via markdown links and bare paths
  - Heading hierarchy for document structure

## Consequences

**Benefits:**
- Tangle format is maximally flexible — any markdown structure works
- Different teams customize via prompt editing, not format changes
- Parser is simpler — fewer frontmatter fields to validate and migrate
- Writer is simpler — less structured data to serialize
- No schema migrations when conventions change — just update the prompt

**Trade-offs:**
- Less machine-readable structure out of the box — parser must infer from body patterns
- Code refs extracted from body content are less precise than explicit frontmatter declarations
- No built-in status field — status is body content, not queryable without parsing
- New users may need guidance on what sections to include (mitigated by good default prompt)

**Mitigations:**
- Default `tangle_maker` prompt suggests standard sections (Behavior, Constraints, Dependencies, Tests) and inline code references nested under the ideas they ground
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

- Rejected: too rigid, too much maintenance overhead, forces all projects into the same structure

### 2. No frontmatter at all

- Rejected: `title` and `last_updated` provide essential metadata the UI and indexer need
  - Extracting title from the first heading is fragile
  - Zero frontmatter makes it harder to distinguish tangle files from regular markdown

### 3. Frontmatter with optional structured fields

```yaml
---
title: User Registration
last_updated: 2026-04-07
status: active       # optional
code_refs: [...]     # optional
---
```

- Rejected: "optional" fields inevitably become expected
  - Parser still needs to handle them; migrations still need to support them
  - Teams argue about which optional fields to use

## References

- [Tangle Standards](../standards.md) — full format specification
- [Tangle Module](../domains/tangle-module.md) — parser implementation
- [Tangle Parsing](../features/tangle-parsing.md) — parsing design and code refs
- [Editable Prompts](../features/editable-prompts.md) — how users customize structure
- `taui/tangle/parser.py:parse_tangle_document` — parser implementation
- `taui/tangle/refs.py:extract_tangle_refs` — code ref extraction
