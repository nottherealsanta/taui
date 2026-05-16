# Skills System

Skills are reusable capability bundles — directories containing a `SKILL.md` file with
instructions that are injected into the agent's conversation on demand. Taui follows the
[Agent Skills](https://agentskills.io/) open standard so skills are portable across
compatible tools.

---

## Architecture

```
SkillRegistry.discover()
  │
  ├── Scan ~/.config/agents/skills/  (global, XDG standard)
  ├── Scan ~/.taui/skills/           (global, taui-native)
  ├── Scan .agents/skills/           (project, Agent Skills standard)
  └── Scan .taui/skills/             (project, taui-native — highest priority)
          │
          ▼
SkillsTool (agent-facing)
  │
  ├── list    → re-discovers, returns available skills
  ├── load    → reads SKILL.md, injects as system message
  ├── unload  → marks skill as not loaded
  └── status  → shows loaded skills and token estimates
```

---

## Discovery Paths

Discovery order is fixed — later directories override earlier entries for the same skill
name. Within a session, project-scoped skills take priority over global ones.

### Global (scanned in order)

| Path | Standard |
|------|----------|
| `~/.config/agents/skills/<name>/SKILL.md` | Agent Skills / XDG |
| `~/.taui/skills/<name>/SKILL.md` | taui-native |

### Project (scanned in order, override global)

| Path | Standard |
|------|----------|
| `.agents/skills/<name>/SKILL.md` | Agent Skills standard |
| `.taui/skills/<name>/SKILL.md` | taui-native — highest priority |

Skills created by other tools that use `.agents/skills/` (Crush, Claude Code, etc.) are
automatically discovered. taui-native paths take final precedence when both exist.

---

## Skill Structure

```
.taui/skills/
├── testing/
│   └── SKILL.md     # Instructions for writing tests
├── docker/
│   └── SKILL.md     # Docker workflow instructions
└── api-design/
    └── SKILL.md     # API design guidelines
```

The skill name is the directory name. `SKILL.md` is Markdown with instructions the agent
follows when the skill is loaded.

---

## Skill Dataclass

```python
@dataclass(slots=True)
class Skill:
    name: str            # Directory name
    path: Path           # Directory containing SKILL.md
    scope: str           # "global", "project", or "extension"
    content: str = ""    # SKILL.md text, loaded lazily
    loaded: bool = False # Whether injected into conversation
```

Key members:

| Member | Description |
|--------|-------------|
| `skill_file` | Property returning `path / "SKILL.md"` |
| `estimated_tokens` | `max(1, len(content) // 4)` — rough token count |
| `load_content()` | Reads `SKILL.md` from disk; truncates at `MAX_SKILL_CHARS`; caches result |

---

## Content Limits

`MAX_SKILL_CHARS = 8_000` — content longer than this is truncated and a
`[skill content truncated]` marker is appended. Content is cached after first read;
it does not change for the lifetime of the session.

---

## SkillRegistry API

| Method / Property | Description |
|-------------------|-------------|
| `discover()` | Scans all four directories, resets the registry |
| `get(name)` | Returns a `Skill` or `None` |
| `list_all()` | Returns all `Skill` objects in sorted name order |
| `loaded_skills()` | Returns only skills where `loaded=True` |
| `add_from_path(path, scope="extension")` | Adds a skill from an explicit `.md` file or `SKILL.md` directory |
| `names` | Sorted list of skill names |

```python
registry = SkillRegistry(working_dir)
registry.discover()
```

---

## SkillsTool Operations

| Operation | Args | Behavior |
|-----------|------|----------|
| `list` | — | Re-runs `discover()` to pick up new skills; returns names and scopes |
| `load` | `skill: str` | Calls `load_content()`, injects content as a system message via callback |
| `unload` | `skill: str` | Marks `loaded=False`; does not remove already-injected messages |
| `status` | — | Shows loaded skills with token estimates |

### Injection

When a skill is loaded its content is appended as a system message directly to the
agent loop's message list:

```python
async def inject_skill_message(content: str) -> None:
    loop._messages.append(Message(role="system", content=content))
```

This callback is wired by `Session.create()` after the loop is constructed.

---

## Extension-Contributed Skills

Extensions can bundle skill files and register them via `ctx.skills.add_path()`:

```python
def register(ctx):
    ctx.skills.add_path("skills/my-skill.md")   # relative to extension file
```

`add_path()` accepts either a plain `.md` file or a directory containing `SKILL.md`.
Relative paths are resolved against the extension's own directory by `SkillContribution`
before being forwarded to `SkillRegistry.add_from_path()`. These skills receive scope
`"extension"` and behave identically to file-system-discovered skills.

---

## Wiring (Session.create)

```python
skill_registry = SkillRegistry(config.working_dir)
skill_registry.discover()
skills_tool = registry.get("skills")
skills_tool._skill_registry = skill_registry
skills_tool._inject_message = inject_skill_message  # wired after loop creation
```

Extension skill paths collected during `load_all()` are forwarded to
`SkillRegistry.add_from_path()` so they are immediately available through the
`skills` tool.
