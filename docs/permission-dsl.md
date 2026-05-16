# Permission DSL

Taui uses a pattern-based permission ruleset to control tool access. Rules map
`(tool_name, argument_pattern)` to a policy decision. Patterns use fnmatch glob syntax.

Source: `taui/permissions.py`

## `PermissionRule`

```python
@dataclass(slots=True)
class PermissionRule:
    tool: str           # Tool name, e.g. "bash", "read", "edit"
    pattern: str        # fnmatch glob matched against the tool's subject
    action: PolicyDecision  # AUTO, CONFIRM, or DENY
```

**Specificity** determines evaluation order within a layer. Longer patterns (more
non-wildcard characters) are more specific and checked first:

```python
@property
def specificity(self) -> int:
    return len(self.pattern.replace("*", "").replace("?", ""))
```

So `.env.example` (12) beats `*.env` (4) beats `*` (0).

## `PermissionRuleset`

Three layers evaluated in order: **agent → project → global**. Within each layer,
rules are sorted by specificity (most specific first). The first match in the first
matching layer wins.

```python
class PermissionRuleset:
    _agent_rules:   list[PermissionRule]
    _project_rules: list[PermissionRule]
    _global_rules:  list[PermissionRule]
```

### `add_rules(rules, layer)`

```python
ruleset.add_rules(
    {
        "read":  {"*": "allow", "*.env": "ask"},
        "bash":  {"git status": "allow", "git push": "ask", "*": "ask"},
        "edit":  {"src/**": "allow", "*": "ask"},
    },
    layer="project",  # "agent", "project", or "global"
)
```

Action strings: `"allow"` maps to `PolicyDecision.AUTO`; `"ask"` maps to
`PolicyDecision.CONFIRM`. Invalid strings are silently skipped.

### `decide(tool_name, subject)`

```python
decision = ruleset.decide("bash", "git status")
# returns PolicyDecision.AUTO | CONFIRM | DENY | None
```

Returns `None` if no rule matches. `ToolPolicy` falls back to per-tool overrides and
built-in defaults when `None` is returned.

### `extract_subject(tool_name, arguments)`

Extracts the string to match against patterns from tool arguments:

| Tool | Subject extracted from |
|------|----------------------|
| `bash` | `arguments["command"]` |
| `read`, `write`, `edit` | `file_path` / `filePath` / `path` |
| `glob` | `arguments["pattern"]` |
| `grep` | `arguments["pattern"]` |
| others | `""` (empty string) |

## TOML Format

Rules are expressed as a `[taui.permission]` table. Each key is a tool name; its value
is a table of `pattern = action` pairs.

### Project permissions: `.taui/permissions.toml`

```toml
[taui.permission]
# Read everything, but ask before reading .env files
read = { "*" = "allow", "*.env" = "ask", ".env.example" = "allow" }

# Allow safe git commands, ask for everything else
bash = { "git status" = "allow", "git log*" = "allow", "git push*" = "ask", "*" = "ask" }

# Allow edits in src/, ask elsewhere
edit = { "src/**" = "allow", "tests/**" = "allow", "*" = "ask" }

# Block writes to config files entirely
write = { "*.toml" = "deny", "*.yaml" = "deny", "*" = "allow" }
```

### Global permissions: `~/.taui/permissions.toml`

Same format. Applied as the `"global"` layer (lowest priority).

### Agent variant permissions

Specified inline in a variant's TOML file under `[permission]`:

```toml
# .taui/agents/reviewer.toml
name = "reviewer"
read_only = true

[permission]
read = { "*" = "allow" }
grep = { "*" = "allow" }
glob = { "*" = "allow" }
```

Applied as the `"agent"` layer (highest priority) when `session.switch_variant()` is
called.

## Integration with `ToolPolicy`

`ToolPolicy.decide(tool_name, arguments)` consults the ruleset first:

```
ruleset.decide(tool_name, subject) → decision?
    yes → return decision
    no  → check per-tool overrides
           no  → check built-in defaults (bash/write/edit = CONFIRM)
                  no  → return AUTO
```

`ToolPolicy.should_auto_approve(tool_name, arguments)` returns `True` if the ruleset
returns `PolicyDecision.AUTO` for the subject, or if a stored per-call glob pattern
matches (used by the TUI's persistent auto-approve extension mechanism).

## Loading Rules at Session Start

In `Session.create()`:

```python
if config.permission:
    ruleset = PermissionRuleset()
    ruleset.add_rules(config.permission, layer="project")
    policy.set_ruleset(ruleset)
```

`config.permission` is populated from `.taui/permissions.toml` (or the `[taui.permission]`
section in a project config file). Extensions can also call
`ctx.policy.set_ruleset(ruleset)` to layer additional rules.

## Pattern Matching Examples

```
tool: bash, subject: "git status"
pattern: "git status"     → exact match, specificity 10
pattern: "git *"          → glob match, specificity 4
pattern: "*"              → wildcard, specificity 0
→ "git status" wins

tool: read, subject: "secrets/.env"
pattern: ".env.example"   → no match
pattern: "*.env"          → match (fnmatch: "*.env" matches "secrets/.env"? No — fnmatch
                            does not cross directory separators by default)
pattern: "*"              → match
→ "*" wins (but note fnmatch does not expand ** across slashes without pathlib)
```

> **Note:** fnmatch does not treat `/` specially. `src/**` matches
> `src/foo/bar` on some platforms but not others. Prefer flat patterns like `src/*`
> or test your patterns with Python's `fnmatch.fnmatch()` directly.
