# Permission DSL

Permissions map `(tool, subject pattern)` to `allow`, `ask`, or `deny`.

## Code

- Rule dataclass: `taui/permissions.py:24`
- Ruleset layers and matching: `taui/permissions.py:38`
- Decision method: `taui/permissions.py:86`
- Tool policy integration: `taui/tools/executor.py:60`
- Auto-approval check: `taui/tools/executor.py:99`
- Config fields: `taui/config.py:50`

## Layers

Rules are evaluated in this order:

1. agent
2. project
3. global

Within one layer, more specific patterns are checked first. Specificity is calculated by
removing `*` and `?` from the pattern and measuring the remaining length:
`taui/permissions.py:30`.

## Subjects

`extract_subject()` chooses the matched text from tool arguments:
`taui/permissions.py:103`.

| Tool | Subject |
| --- | --- |
| `bash` | command string |
| `read`, `write`, `edit` | `file_path`, `filePath`, or `path` |
| `glob`, `grep` | pattern |
| other tools | empty string |

## TOML

Project rules live in `.taui/permissions.toml` or a project config table.
Global rules live in `~/.taui/permissions.toml`.

```toml
[taui.permission]
read = { "*" = "allow", "*.env" = "ask" }
bash = { "git status" = "allow", "git log*" = "allow", "*" = "ask" }
edit = { "src/*" = "allow", "tests/*" = "allow", "*" = "ask" }
write = { "*.toml" = "deny", "*" = "ask" }
```

Config loading copies `[taui.permission]` into `Config.permission`:
`taui/config.py:81`. `Session.create()` installs it into `ToolPolicy`:
`taui/session.py:176`.

## Actions

| TOML value | Runtime decision |
| --- | --- |
| `allow` | `PolicyDecision.AUTO` |
| `ask` | `PolicyDecision.CONFIRM` |
| `deny` | `PolicyDecision.DENY` |

If no rule matches, `ToolPolicy` falls back to per-tool overrides and then builtin
defaults: `taui/tools/executor.py:60`.
