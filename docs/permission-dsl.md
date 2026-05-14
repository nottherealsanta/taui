# Permission DSL

**Section 10.4** | See also: [Agent Variants](agents.md), `taui/permissions.py`

## Overview

The permission DSL is a ruleset that controls whether a tool invocation is
auto-approved, presented to the user for confirmation, or rejected outright. Rules are
written as ordered lists of glob patterns mapped to actions.

---

## Pattern Syntax

Patterns use Python `fnmatch` glob syntax:

| Wildcard | Matches |
| --- | --- |
| `*` | Any sequence of characters within a path segment (or the whole subject string) |
| `?` | Any single character |
| `[seq]` | Any character in `seq` |
| `[!seq]` | Any character not in `seq` |

Because the underlying match is `fnmatch.fnmatch`, `*` does cross directory separator
boundaries in subject strings. Use explicit path prefixes (e.g. `src/*`) to scope rules
to a subtree.

---

## Configuration in `pyproject.toml`

Project-level rules live under `[tool.taui.permission]`. Each key is a tool category;
the value is an inline table of `pattern = action` entries.

```toml
[tool.taui.permission]
read  = { "*" = "allow", "*.env" = "ask", ".env.example" = "allow" }
bash  = { "git status" = "allow", "git push" = "ask", "*" = "ask" }
edit  = { "src/**" = "allow", "*" = "ask" }
```

The global equivalent lives at `~/.taui/config.toml` under the same `[permission]` key.

---

## Actions

| Action | Effect |
| --- | --- |
| `allow` | Tool call proceeds automatically without prompting the user |
| `ask` | An approval prompt is shown in the TUI; the user must confirm or cancel |
| `deny` | Tool call is rejected immediately; the agent receives a failure result |

---

## Evaluation Order

Within a single ruleset table, patterns are evaluated from most specific to least
specific. Specificity is determined by the length of the longest non-wildcard prefix of
each pattern.

For example, given:

```toml
bash = { "git status" = "allow", "git *" = "ask", "*" = "deny" }
```

- `"git status"` has the longest literal prefix and is tried first.
- `"git *"` is tried second.
- `"*"` is the fallback.

A literal pattern (`"git status"`) with no wildcards always beats a pattern with
wildcards when both could match the same subject.

If no pattern matches, the default action is `ask`.

---

## Layer Cascade

Rules are resolved through three layers. The first match across all layers wins:

1. **Agent layer** — permissions defined in the active `AgentVariant` (highest priority)
2. **Project layer** — `[tool.taui.permission]` in `pyproject.toml` or `.taui/config.toml`
3. **Global layer** — `[permission]` in `~/.taui/config.toml` (lowest priority)

Within each layer the most-specific-pattern-first ordering described above applies.
Once a layer yields a match, the remaining layers are not consulted.

---

## Subject Extraction

Before pattern matching, the tool invocation is reduced to a single subject string.
Each tool category uses a different argument as the subject:

| Tool category | Subject argument |
| --- | --- |
| `bash` | `command` |
| `read` | `file_path`, `filePath`, or `path` (first present) |
| `write` | `file_path`, `filePath`, or `path` |
| `edit` | `file_path`, `filePath`, or `path` |
| `glob` | `pattern` |
| `grep` | `pattern` |

Tools that do not map cleanly to one of these categories fall through to the default
action (`ask`) unless a matching rule is found under their registered category name.

---

## Per-Agent Overrides

An `AgentVariant` can carry its own `permission` table that sits above the project layer
in the cascade. See [Agent Variants](agents.md) for the variant definition format.

Example: a read-only review variant that blocks all shell access except git inspection
commands:

```toml
# .taui/agents/review.toml
name = "review"
read_only = true

[permission]
bash = { "git log *" = "allow", "git diff *" = "allow", "*" = "deny" }
read = { "*" = "allow" }
```

The agent-layer `bash` rules are evaluated before any project or global bash rules.

---

## Common Recipes

### Allow git read operations, ask for git write operations, deny anything touching prod

```toml
[tool.taui.permission]
bash = {
  "git log *"       = "allow",
  "git diff *"      = "allow",
  "git show *"      = "allow",
  "git status"      = "allow",
  "git push *prod*" = "deny",
  "git push *"      = "ask",
  "git commit *"    = "ask",
  "*"               = "ask"
}
```

### Auto-approve reads in `src/`, ask for everything else

```toml
[tool.taui.permission]
read  = { "src/*" = "allow", "*" = "ask" }
glob  = { "src/*" = "allow", "*" = "ask" }
grep  = { "src/*" = "allow", "*" = "ask" }
edit  = { "src/*" = "allow", "*" = "ask" }
write = { "*" = "ask" }
bash  = { "*" = "ask" }
```

### Deny all shell access except a whitelist of safe commands

```toml
[tool.taui.permission]
bash = {
  "git status"     = "allow",
  "git log *"      = "allow",
  "git diff *"     = "allow",
  "uv run pytest*" = "allow",
  "uv run ruff *"  = "allow",
  "*"              = "deny"
}
```

### Protect secrets files while keeping the rest readable

```toml
[tool.taui.permission]
read = {
  ".env"          = "deny",
  "*.env"         = "deny",
  ".env.*"        = "ask",
  ".env.example"  = "allow",
  "*"             = "allow"
}
```

---

## Reference

- `taui/permissions.py` — ruleset parsing, subject extraction, and match evaluation
- `taui/tools/executor.py` — where permission checks are applied before tool execution
- [Agent Variants](agents.md) — per-variant permission overrides
- `AGENTS.md` — extension and configuration loading conventions
