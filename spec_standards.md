# Project Specs Standards

## Purpose

This document defines the standard for creating, maintaining, and navigating a `specs/` directory in a software project. The `specs/` directory is the shared project knowledge surface for both humans and AI agents. It exists to keep intent, architecture, constraints, decisions, implementation context, and verification closely linked without duplicating the source code repository.

The standards in this document are designed to make a project understandable, navigable, and editable at scale. They optimize for three goals:

1. **Shared understanding** — humans and agents should work from the same project context.
2. **Scoped context** — any local task should inherit the right amount of global and domain-specific context.
3. **Linked execution** — specs should remain tied to code, tests, and decisions so they stay operational rather than becoming passive documentation.

---

## Core Principles

### 1. The specs/ directory is the project knowledge interface

The `specs/` directory is the primary place to understand how the project is intended to work. It is not a replacement for code, tests, or operational systems. Instead, it provides the structure and narrative that connects them.

The `specs/` directory should answer:

- what the project is trying to achieve,
- how the project is organized,
- what constraints must always hold,
- why major decisions were made,
- where relevant code lives,
- how correctness is verified.

### 2. Specs must be readable by humans and parseable by agents

All spec files must be easy for engineers to read directly. At the same time, they must have enough structural consistency that an agent can navigate them reliably.

This means:

- predictable file locations,
- predictable headings,
- lightweight frontmatter (only title, status, last_updated),
- explicit links to related specs, code, tests, and decisions in the body,
- stable section anchors for important sections.

### 3. Specs should describe intent and constraints, grounded in code references

Specs must not become a second copy of the codebase. Instead, they should reference code densely.

Specs should primarily contain:

- purpose,
- user or business outcomes,
- constraints,
- architecture and design context,
- decisions,
- **dense references to implementation code** (classes, functions, methods, line ranges),
- references to verification.

Implementation details should live in code. Specs should refer to code rather than reproduce it. Every class, function, or method that is relevant to a spec should be referenced — both in frontmatter `code_refs` and inline throughout the document body. When a spec references code, the UI renders the referenced code inline, so readers can see the actual implementation without leaving the spec. This makes code references the primary bridge between intent and implementation.

### 4. Hierarchy is for context inheritance, not ontology purity

The structure of `specs/` is hierarchical so that context can be inherited progressively.

For example:

- `main.md` defines project-wide context,
- domain files inherit project-wide context,
- feature files inherit project-wide and domain context,
- decisions may be linked across multiple domains and features.

This hierarchy exists to help humans and agents load the right slice of context. It must not force every project concept into a rigid tree.

### 5. Every important spec must link outward to reality through code

A spec is only useful if it is grounded in the actual project. Code references are the most important type of link because they are rendered inline in the UI — readers see the actual source code directly within the spec.

Important spec files should link to:

- **relevant code — as many references as needed** (classes, functions, methods, constants),
- relevant tests,
- relevant decisions,
- related specs,
- operational or verification evidence when appropriate.

A well-written spec should reference every significant function, class, or method involved in the feature or domain it describes. The goal is that a reader can understand the full implementation landscape by reading the spec alone, with code rendered inline.

---

## Standard Directory Structure

At minimum, every project using this standard should contain:

```
specs/
  main.md
  standards.md
  architecture.md
  domains/
  features/
  decisions/
```

A fuller layout may look like:

```
specs/
  main.md
  standards.md
  architecture.md
  glossary.md
  domains/
    auth.md
    billing.md
    onboarding.md
  features/
    login-flow.md
    invoice-retries.md
  decisions/
    0001-auth-strategy.md
    0002-billing-ledger.md
  workflows/
    release.md
    incident-response.md
  templates/
    domain-template.md
    feature-template.md
    decision-template.md
```

### Required files

**`specs/main.md`**
The project entry point. This file provides the global project brief and the table of contents for the `specs/` directory.

**`specs/standards.md`**
This standards document. It defines the rules agents and humans must follow when creating and maintaining the `specs/` directory.

**`specs/architecture.md`**
A project-wide architecture overview describing major components, boundaries, and system shape.

**`specs/domains/*.md`**
Domain-level documents describing major product or technical areas.

**`specs/features/*.md`**
Feature-level documents describing specific user-facing or system-facing capabilities.

**`specs/decisions/*.md`**
Decision records documenting important architectural or product choices.

---

## File Roles

### main.md

`main.md` is the inheritance root for the entire `specs/` directory. It should remain short, clear, and highly curated.

It must contain:

- project purpose,
- how to use the `specs/` directory,
- global constraints,
- major domains,
- links to architecture, key features, and key decisions,
- guidance for agents working in the project.

### Domain files

A domain file describes a major project area such as auth, billing, onboarding, infrastructure, or analytics.

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
- related specs and code.

---

## Required Frontmatter

Every file in `specs/` except templates must begin with YAML frontmatter.

The minimum frontmatter is:

```yaml
---
title: Login Flow
status: active
last_updated: 2026-03-20T14:30:00
---
```

### Required frontmatter fields

- **title**: human-readable title
- **status**: one of `draft`, `active`, `verified`, `deprecated`
- **last_updated**: datetime of last meaningful update (ISO 8601 with time, e.g. `2026-03-20T14:30:00`)

Frontmatter must remain lightweight. Only metadata that applies to the entire file belongs here. Do not turn it into a complex database schema. The body of the document is the primary source of meaning.

### Fields that belong in the body, not frontmatter

The following fields must be written as sections or inline references in the note body rather than as frontmatter properties:

- **domain** — state as prose or a heading in the body (e.g. `Domain: auth`)
- **depends_on** — list dependencies in a `## Dependencies` section or inline
- **code_refs** — reference code inline throughout the body using `file.py#symbol` syntax; the UI renders them as viewable code
- **test_refs** — list test references in a `## Tests / Verification` section
- **decision_refs** — link decisions inline or in a `## Related Decisions` section

Code refs should be **dense** — reference every class, function, and method that participates in the feature. Each code ref is rendered inline in the UI, so the reader sees the actual implementation code directly within the spec view.

---

## Standard Headings

To keep files predictable for both humans and agents, use standard section headings whenever possible.

### Required headings for main.md

- `# Project Spec`
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
- `## Important Code References`
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

## Stable References and Anchors

Agents must be able to refer to specific parts of a file reliably. For that reason, important sections should include stable anchors.

Accepted patterns include:

```markdown
## Constraints {#login-flow-constraints}
```

or:

```markdown
## Constraints
<!-- spec:id=login-flow.constraints -->
```

### When anchors are required

Use explicit anchors for:

- constraints,
- design sections,
- verification sections,
- decision statements,
- any section likely to be updated or cited independently.

Anchors should be:

- stable over time,
- descriptive,
- unique within the repo,
- based on file purpose rather than current line numbers.

---

## Linking Standards

Every important spec file must link to related materials in a predictable way.

### Required relationship categories

Most files should include a Related area or equivalent references distributed through the file.

These relationship types are recommended:

- related specs,
- decision refs,
- code refs,
- test refs,
- workflow refs,
- evidence refs when relevant.

### Markdown links for spec-to-spec references

Use normal relative markdown links for spec files.

Example:

```markdown
- [Auth Domain](../domains/auth.md)
- [0001 Auth Strategy](../decisions/0001-auth-strategy.md)
```

### Code reference format

Code references are rendered inline in the UI. When a spec includes a code ref, the referenced code is fetched and displayed directly in the spec view. This makes code refs the most powerful tool for grounding specs in reality.

Prefer file path plus symbol reference rather than line numbers.

Recommended formats:

- `app/auth/routes.py#login_handler`
- `app/auth/service.py#AuthService`
- `app/auth/service.py#authenticate_user`
- `tests/auth/test_login.py#test_successful_login`

If a more explicit syntax is supported by tooling, use:

- `file:app/auth/routes.py#symbol=login_handler`

Line ranges may be used as an alternative:

- `app/auth/routes.py#L120-L180`

Symbol-based references are preferred because they survive refactoring, but line ranges are acceptable.

### How many code refs to include

Include **all** classes, functions, and methods that are relevant to the spec. A feature spec should reference:

- the main entry point function or method,
- all helper functions called by the entry point,
- data models and types involved,
- validation functions,
- error handling,
- related test functions.

A domain spec should reference:

- all public-facing classes and their key methods,
- data models owned by the domain,
- important internal helpers,
- test files and key test functions.

Do not hold back on code refs. More is better. Each ref renders as viewable code in the UI, giving the reader a complete picture of the implementation.

---

## Writing Standards

### Write for local usefulness first

Each spec file should be useful on its own to someone actively working in that area. Files should not assume that the reader has loaded the entire project context.

### Keep files medium-sized

Do not create giant monolithic docs. A file should be long enough to explain one area well and short enough to act as an effective context packet.

As a guideline:

- `main.md` should be short,
- domain files should be medium-sized,
- feature files should be medium-sized and task-oriented,
- decision files should be concise and durable.

### Favor explicit constraints

Important rules should be stated directly rather than implied through prose.

Good:

- Do not reveal whether an email exists during login.
- API responses for v1 clients must remain backward compatible.

Less good:

- The system should probably continue behaving roughly as before in most cases.

### Separate fact from inference

When documenting the current project, distinguish between:

- what is known,
- what is intended,
- what is inferred,
- what remains unresolved.

Open questions should be placed in an Open Questions section rather than embedded ambiguously in the design.

### Avoid stale duplication

Do not duplicate code, API schemas, or test content unless the duplication serves a very specific explanatory purpose. Prefer references to canonical artifacts.

---

## Agent Navigation Rules

Agents must navigate the `specs/` directory using inherited context.

### Required reading order for major work

Before making a significant change, an agent should read, in order:

1. `specs/main.md`
2. the relevant domain spec,
3. the relevant feature spec if one exists,
4. linked decision files,
5. linked code and test references.

This sequence ensures that local edits remain grounded in project-wide intent and constraints.

### For small local changes

For narrowly scoped edits, an agent may start from the nearest feature or domain file, but it must still account for inherited global constraints from `main.md`.

### When no matching spec exists

If an agent cannot find an appropriate feature or domain spec, it should:

- check `main.md` and `architecture.md`,
- infer the most relevant domain,
- create a new spec file only if the work introduces new durable project knowledge,
- avoid creating fragmented or redundant specs for one-off ephemeral tasks.

---

## Agent Authoring Rules

Agents must treat the `specs/` directory as a living operational workspace.

### When agents must update specs

An agent must update related specs when it changes any of the following:

- user-visible behavior,
- domain constraints,
- architecture boundaries,
- implementation ownership assumptions,
- important code references,
- verification requirements,
- major design decisions.

### When agents must create a decision record

Create a new file in `specs/decisions/` when a change:

- introduces a new architectural pattern,
- changes a long-lived interface contract,
- changes an important tradeoff,
- formalizes a significant product or system decision,
- would be difficult to understand later without rationale.

### When agents should not create new spec files

Do not create a new spec file for:

- trivial implementation cleanup,
- purely local refactors with no change in system behavior or meaning,
- temporary debugging notes,
- information better represented as code comments or tests.

### Required agent behaviors

Agents should:

- prefer editing existing specs over creating redundant ones,
- preserve stable anchors when editing files,
- maintain consistent headings and frontmatter,
- add links rather than duplicate content,
- update `last_updated` when making meaningful changes,
- keep wording clear and direct,
- keep specs synchronized with behavior-changing code updates.

---

## Human Navigation Guidance

Humans should be able to use the `specs/` directory as a progressive map of the project.

Recommended navigation pattern:

- start at `main.md` for project-wide context,
- move to a domain file for bounded area context,
- move to a feature file for task-level context,
- follow links to decisions, code, and tests as needed.

The `specs/` directory should support both zooming out and zooming in.

---

## Verification Standards

Specs should not only describe behavior; they should also indicate how behavior is verified.

Every important feature or domain file should include verification references such as:

- automated tests,
- integration tests,
- benchmark suites,
- manual checks,
- operational validations,
- linked evidence.

Verification sections should answer:

- how to tell whether this area still works,
- which checks matter most,
- what must be revalidated after change.

When possible, verification should be linked rather than restated.

---

## Freshness and Maintenance

A spec that is stale is often worse than a spec that does not exist.

### Minimum maintenance rules

- Update `last_updated` when meaningfully changing a file.
- Remove or revise stale references.
- Prefer updating existing docs to adding parallel documents.
- Mark deprecated files as `status: deprecated` rather than silently abandoning them.

### Signals that a spec needs review

A spec likely needs review if:

- linked code has moved or changed substantially,
- behavior has changed but the feature file has not,
- a decision file no longer reflects current architecture,
- verification references are broken or outdated,
- a file has grown too broad and should be split.

---

## Naming Conventions

Use kebab-case for filenames.

Examples:

- `main.md`
- `architecture.md`
- `domains/auth.md`
- `features/login-flow.md`
- `decisions/0001-auth-strategy.md`

Decision files should be numbered and stable. Avoid renumbering existing decision records.

---

## Anti-Patterns

The following anti-patterns must be avoided:

### 1. Specs as a second codebase

Do not mirror the implementation line by line in markdown. Instead, use dense code references — the UI renders referenced code inline, so there is no need to copy code into the spec body.

### 2. Giant top-heavy documents

Do not put all project knowledge into `main.md` or a single architecture file.

### 3. Orphaned feature specs

Do not create feature files that are not linked from a domain or from `main.md` when they matter to the project.

### 4. Unstructured freeform notes

Do not rely on ad hoc notes without headings, references, or ownership.

### 5. Ambiguous references

Do not write phrases like "the auth code" when an exact file or symbol can be named. Always use a code ref (`file.py#ClassName` or `file.py#function_name`) so the UI can render the actual code inline.

### 6. Silent divergence

Do not change important behavior in code without updating the related spec context.

---

## Minimal Example

```
specs/
  main.md
  standards.md
  architecture.md
  domains/
    auth.md
  features/
    login-flow.md
  decisions/
    0001-auth-strategy.md
```

This minimal structure is enough to support:

- project-wide context,
- domain-level context,
- feature-level context,
- durable decision memory,
- linked code and verification.

---

## Standard Operating Rule

A software project should be understandable by starting from `specs/main.md`, moving into the relevant domain and feature files, and then following links into code, tests, and decisions. Agents and humans should work from the same knowledge surface, with local work inheriting the right context from the broader project.

The purpose of this standard is not to impose documentation overhead. Its purpose is to ensure that project knowledge remains structured, navigable, and operational as the system grows.
