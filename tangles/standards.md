---
title: Tangle Standards
last_updated: 2026-04-10
---

# Tangle Standards

A tangle is a literate document. Prose and code are interwoven. The tangle is the source of truth; the code is the derived artifact.

## Purpose

This document defines the standard for creating, maintaining, and navigating a `tangles/` directory in a software project. The `tangles/` directory is the shared project knowledge surface for both humans and AI agents. It exists to keep intent, architecture, constraints, decisions, implementation context, and verification closely linked without duplicating the source code repository.

The standards optimize for three goals:

1. **Shared understanding** — humans and agents work from the same project context.
2. **Scoped context** — any local task inherits the right amount of global and domain-specific context.
3. **Linked execution** — tangles remain tied to code, tests, and decisions so they stay operational rather than becoming passive documentation.

---

## Core Principles

### 1. The tangles/ directory is the project knowledge interface

The `tangles/` directory is the primary place to understand how the project is intended to work. It is not a replacement for code, tests, or operational systems. It provides the structure and narrative that connects them.

The `tangles/` directory should answer:

- what the project is trying to achieve,
- how the project is organized,
- what constraints must always hold,
- why major decisions were made,
- where relevant code lives,
- how correctness is verified.

### 2. Tangles must be readable by humans and parseable by agents

All tangle files must be easy for engineers to read directly. At the same time, they must have enough structural consistency that an agent can navigate them reliably.

This means:

- predictable file locations,
- predictable headings,
- lightweight frontmatter (only `title` and `last_updated`),
- explicit links to related tangles, code, tests, and decisions in the body,
- stable section anchors for important sections.

### 3. Tangles describe intent and constraints, grounded in code references

Tangles must not become a second copy of the codebase. Instead, they should reference code densely.

Tangles should primarily contain:

- purpose,
- user or business outcomes,
- constraints,
- architecture and design context,
- decisions,
- **dense references to implementation code** (classes, functions, methods, line ranges),
- references to verification.

Implementation details should live in code. Tangles should refer to code rather than reproduce it. When a tangle references code, the UI renders the referenced code inline, so readers can see the actual implementation without leaving the tangle.

### 4. Hierarchy is for context inheritance, not ontology purity

The structure of `tangles/` is hierarchical so that context can be inherited progressively:

- `index.md` defines project-wide context,
- domain files inherit project-wide context,
- feature files inherit project-wide and domain context,
- decisions may be linked across multiple domains and features.

This hierarchy helps humans and agents load the right slice of context. It must not force every project concept into a rigid tree.

### 5. Every important tangle must link outward to reality through code

A tangle is only useful if it is grounded in the actual project. Code references are the most important type of link because they are rendered inline in the UI.

Important tangle files should link to:

- **relevant code — as many references as needed** (classes, functions, methods, constants),
- relevant tests,
- relevant decisions,
- related tangles,
- operational or verification evidence when appropriate.

---

## Document Format

Every tangle is a markdown file with minimal YAML frontmatter.

### Required Frontmatter

- `title` — human-readable name
- `last_updated` — ISO date of last modification

That's it. Everything else goes in the body.

### Body Content

The body is standard markdown. Headings create navigable sections. What sections you include is up to you — the tangle-making tool's prompt suggests defaults, but you can change the prompt.

### Code References

Code references appear inline in prose:

- Arrow notation: `-> src/auth.py:register_handler`
- Backtick notation: `` `src/auth.py:register_handler` ``
- Line ranges: `` `src/auth.py:45-52` ``

All paths are relative to the project root.

### Linking Other Tangles

- Markdown links: `[Data Layer](tangles/domains/data-layer.md)`
- With anchors: `[Behavior](tangles/domains/data-layer.md#behavior)`
- Bare paths: `tangles/domains/data-layer.md`

All tangle paths are relative to the project root. This is core markdown only — no custom syntax.

---

## Standard Directory Structure

At minimum, every project using this standard should contain:

```
tangles/
  index.md
  standards.md
  domains/
  features/
  decisions/
```

A fuller layout may look like:

```
tangles/
  index.md
  standards.md
  domains/
    auth.md
    billing.md
    data-layer.md
  features/
    login-flow.md
    invoice-retries.md
  decisions/
    0001-auth-strategy.md
    0002-billing-ledger.md
```

### Required files

**`tangles/index.md`**
The project entry point. This file provides the global project brief and the table of contents for the `tangles/` directory.

**`tangles/standards.md`**
This standards document. It defines the rules agents and humans must follow when creating and maintaining the `tangles/` directory.

**`tangles/domains/*.md`**
Domain-level documents describing major product or technical areas.

**`tangles/features/*.md`**
Feature-level documents describing specific user-facing or system-facing capabilities.

**`tangles/decisions/*.md`**
Decision records documenting important architectural or product choices.

---

## File Roles

### index.md

`index.md` is the inheritance root for the entire `tangles/` directory. It should remain short, clear, and highly curated.

It must contain:

- project purpose,
- how to use the `tangles/` directory,
- global constraints,
- major domains,
- links to key features and key decisions,
- guidance for agents working in the project.

### Domain files

A domain file describes a major project area such as auth, billing, infrastructure, or frontend.

A domain file should explain:

- what the domain owns,
- what it does not own,
- invariants that must always hold,
- important interfaces,
- major code locations,
- critical tests,
- major related features and decisions.

### Feature files

A feature file describes a concrete unit of work or capability. It should be scoped tightly enough that an agent or engineer can use it as a working context packet.

A feature file should explain:

- what problem the feature solves,
- expected user or business outcomes,
- scope and non-scope,
- design and edge cases,
- implementation references,
- verification requirements,
- open questions or follow-up items.

### Decision files

Decision files capture why an important choice was made. They provide durable memory so that future humans and agents do not repeatedly undo deliberate tradeoffs.

A decision file should explain:

- context,
- the decision,
- alternatives considered,
- consequences and tradeoffs,
- related tangles and code.

---

## Standard Headings

To keep files predictable for both humans and agents, use standard section headings whenever possible.

### Required headings for index.md

- `# <Project Name>`
- `## Purpose`
- `## How to Use This Directory`
- `## Global Constraints`
- `## Domains`
- `## Core Architecture`
- `## Active Features`
- `## Key Decisions`
- `## Agent Working Rules`

### Required headings for domain files

- `# <Domain Name>`
- `## Responsibility`
- `## Invariants`
- `## Interfaces`
- `## Key Components`
- `## Code References`
- `## Verification`
- `## Related Features`
- `## Related Decisions`

### Required headings for feature files

- `# <Feature Name>`
- `## Purpose`
- `## User / Business Outcome`
- `## Scope`
- `## Constraints`
- `## Design`
- `## Code References`
- `## Tests / Verification`
- `## Open Questions`
- `## Related Decisions`

### Required headings for decision files

- `# <Decision ID and Title>`
- `## Status`
- `## Context`
- `## Decision`
- `## Consequences`
- `## Alternatives Considered`
- `## References`

Files may include additional sections when needed, but the standard headings should remain present and recognizable.

---

## Writing Standards

### Write for local usefulness first

Each tangle file should be useful on its own to someone actively working in that area. Files should not assume that the reader has loaded the entire project context.

### Keep files medium-sized

Do not create giant monolithic docs. A file should be long enough to explain one area well and short enough to act as an effective context packet.

### Favor explicit constraints

Important rules should be stated directly rather than implied through prose.

Good:
- Do not reveal whether an email exists during login.
- API responses for v1 clients must remain backward compatible.

Less good:
- The system should probably continue behaving roughly as before in most cases.

### Separate fact from inference

Distinguish between what is known, what is intended, what is inferred, and what remains unresolved. Open questions belong in an Open Questions section.

### Avoid stale duplication

Do not duplicate code, API schemas, or test content unless the duplication serves a specific explanatory purpose. Prefer code references to canonical artifacts.

---

## Customization

The structure of tangle documents is controlled by the tangle-making tool's system prompt, not by the format itself.

To change what sections tangles include, edit the prompt in Settings -> Prompts -> Tangle Maker.

Same goes for agent behavior — prime, root, and sub-agent prompts are all editable in Settings -> Prompts.

---

## Agent Navigation Rules

Agents must navigate the `tangles/` directory using inherited context.

### Required reading order for major work

Before making a significant change, an agent should read, in order:

1. `tangles/index.md`
2. the relevant domain tangle,
3. the relevant feature tangle if one exists,
4. linked decision files,
5. linked code and test references.

### For small local changes

For narrowly scoped edits, an agent may start from the nearest feature or domain file, but it must still account for inherited global constraints from `index.md`.

### When no matching tangle exists

If an agent cannot find an appropriate feature or domain tangle, it should:

- check `index.md`,
- infer the most relevant domain,
- create a new tangle file only if the work introduces new durable project knowledge,
- avoid creating fragmented or redundant tangles for one-off ephemeral tasks.

---

## Agent Authoring Rules

Agents must treat the `tangles/` directory as a living operational workspace.

### When agents must update tangles

An agent must update related tangles when it changes any of the following:

- user-visible behavior,
- domain constraints,
- architecture boundaries,
- implementation ownership assumptions,
- important code references,
- verification requirements,
- major design decisions.

### When agents must create a decision record

Create a new file in `tangles/decisions/` when a change:

- introduces a new architectural pattern,
- changes a long-lived interface contract,
- changes an important tradeoff,
- formalizes a significant product or system decision,
- would be difficult to understand later without rationale.

### When agents should not create new tangle files

Do not create a new tangle file for:

- trivial implementation cleanup,
- purely local refactors with no change in system behavior or meaning,
- temporary debugging notes,
- information better represented as code comments or tests.

### Required agent behaviors

Agents should:

- prefer editing existing tangles over creating redundant ones,
- preserve stable anchors when editing files,
- maintain consistent headings and frontmatter,
- add links rather than duplicate content,
- update `last_updated` when making meaningful changes,
- keep wording clear and direct,
- keep tangles synchronized with behavior-changing code updates.

---

## Anti-Patterns

### 1. Tangles as a second codebase

Do not mirror the implementation line by line in markdown. Use dense code references — the UI renders referenced code inline.

### 2. Giant top-heavy documents

Do not put all project knowledge into `index.md` or a single file.

### 3. Orphaned feature tangles

Do not create feature files that are not linked from a domain or from `index.md`.

### 4. Unstructured freeform notes

Do not rely on ad hoc notes without headings, references, or ownership.

### 5. Ambiguous references

Do not write phrases like "the auth code" when an exact file or symbol can be named. Always use a code ref so the UI can render the actual code inline.

### 6. Silent divergence

Do not change important behavior in code without updating the related tangle.

---

## Standard Operating Rule

A software project should be understandable by starting from `tangles/index.md`, moving into the relevant domain and feature files, and then following links into code, tests, and decisions. Agents and humans should work from the same knowledge surface, with local work inheriting the right context from the broader project.

The purpose of this standard is not to impose documentation overhead. Its purpose is to ensure that project knowledge remains structured, navigable, and operational as the system grows.
