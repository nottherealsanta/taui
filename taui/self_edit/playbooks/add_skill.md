## Active playbook: add skill

The user wants to add a new skill. Skills are Markdown prompt bundles that an
agent can load mid-session via the `skills` tool.

### Layout

Each skill is a directory containing a `SKILL.md`:

- Project: `.taui/skills/<name>/SKILL.md` or `.agents/skills/<name>/SKILL.md`.
- Global: `~/.taui/skills/<name>/SKILL.md` or `~/.config/agents/skills/<name>/SKILL.md`.

### `SKILL.md` contract

Front-matter is optional but supported. The body is the actual instructions
loaded into the agent's context. Keep total content under ~8 KB; longer files
are truncated by the loader.

```markdown
---
name: code-review
description: Structured pull-request review checklist
---

# Code review skill

You are reviewing a pull request. Walk through:

1. ...
```

### Workflow

1. Confirm the skill name (lowercase, kebab-case) and what it should help the
   agent do.
2. Create the directory and write `SKILL.md`. Use `Write` to create the file.
3. Tell the user the skill will be discovered next time they enter a session
   (or when they exit self-edit and the registry re-scans).
