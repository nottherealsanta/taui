# Skills System

Skills are reusable capability bundles — directories containing a `SKILL.md` file with instructions that can be loaded into the agent's conversation on demand.

---

## Architecture

```
SkillRegistry.discover()
  │
  ├── Scan global dirs (XDG, ~/.taui/skills/)
  ├── Scan project dirs (.agents/skills/, .taui/skills/)
  └── Later dirs override earlier for same-named skills
          │
          ▼
SkillsTool (agent-facing)
  │
  ├── list    → re-discovers, returns available skills
  ├── load    → reads SKILL.md, injects as system message
  ├── unload  → marks skill as unloaded
  └── status  → shows loaded skills and token usage
```

---

## Discovery Paths

Skills follow the [Agent Skills](https://agentskills.io/) open standard. Discovery order (later overrides earlier):

### Global
| Path | Standard |
|------|----------|
| `~/.config/agents/skills/<name>/SKILL.md` | Agent Skills / XDG |
| `~/.taui/skills/<name>/SKILL.md` | taui-native |

### Project
| Path | Standard |
|------|----------|
| `.agents/skills/<name>/SKILL.md` | Agent Skills standard |
| `.taui/skills/<name>/SKILL.md` | taui-native |

This means skills from Crush, Claude Code, or any other tool that uses `.agents/skills/` are automatically discovered. taui-native paths take priority when both exist.

---

## Skill Structure

Each skill is a directory containing at minimum a `SKILL.md` file:

```
.taui/skills/
├── testing/
│   └── SKILL.md     # Instructions for writing tests
├── docker/
│   └── SKILL.md     # Docker workflow instructions
└── api-design/
    └── SKILL.md     # API design guidelines
```

The `SKILL.md` content is Markdown with instructions the agent should follow when the skill is loaded.

---

## Skill Dataclass

```python
@dataclass(slots=True)
class Skill:
    name: str            # Directory name
    path: Path           # Directory containing SKILL.md
    scope: str           # "global" or "project"
    content: str = ""    # Loaded lazily from SKILL.md
    loaded: bool = False # Whether injected into conversation
```

- `load_content()` — reads SKILL.md from disk, truncates at `MAX_SKILL_CHARS` (8,000)
- `estimated_tokens` — rough `len(content) // 4`
- Content is cached after first read

---

## SkillsTool Operations

| Operation | Args | Behavior |
|-----------|------|----------|
| `list` | — | Re-runs `discover()` to pick up new skills, returns names + scopes |
| `load` | `skill: str` | Reads SKILL.md, injects as system message via callback |
| `unload` | `skill: str` | Marks skill as not loaded (does not remove from messages) |
| `status` | — | Shows loaded skills with token estimates |

### Injection

When the agent loads a skill, its content is injected as a system message directly into the agent loop's message list:

```python
async def inject_skill_message(content: str) -> None:
    loop._messages.append(Message(role="system", content=content))
```

This callback is wired by `Session.create()`.

---

## Wiring (Session.create)

```python
skill_registry = SkillRegistry(config.working_dir)
skill_registry.discover()
skills_tool = registry.get("skills")
skills_tool._skill_registry = skill_registry
skills_tool._inject_message = inject_skill_message  # wired after loop creation
```

---

## Content Limits

- `MAX_SKILL_CHARS = 8_000` — content longer than this is truncated with a `[skill content truncated]` marker
- Content is cached after first read (immutable for the session lifetime)
- Token estimate: `max(1, len(content) // 4)`
