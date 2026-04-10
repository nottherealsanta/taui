---
title: Editable Prompts
last_updated: 2026-04-10
---

# Editable Prompts

User-customizable system prompts for all agent types and tangle tools.

Depends on: [Agent System](../domains/agent-system.md), [Server](../domains/server.md)

## Purpose

Let users view and customize the system prompts that control agent behavior and tangle document structure. This replaces rigid frontmatter-based structure with flexible, user-controlled conventions.

## User / Business Outcome

- Users can tune agent behavior without modifying source code.
- Teams can standardize tangle conventions by editing the `tangle_maker` prompt.
- Different projects can have different tangle structures (a game studio vs. a SaaS team).
- Default prompts ship with taui and are upgradeable — user edits are preserved across upgrades.

## Scope

In scope:
- Five prompt types: `prime_system`, `root_agent_system`, `sub_agent_system`, `tangle_maker`, `tangle_reviewer`
- Storage in `.taui/settings.json` under the `prompts` key
- RPC methods: `prompts.list`, `prompts.get`, `prompts.update`, `prompts.reset`
- Settings UI: "Prompts" section where users view and edit each prompt
- Default seeding on first run
- Upgrade behavior: only overwrite prompts where `is_default` is `true`

Out of scope:
- Per-tangle prompt overrides (all prompts are project-wide)
- Prompt versioning / history (beyond `last_updated` timestamp)

## Constraints

- Prompts stored in `settings.json`, not in the database.
- Each prompt has `content`, `is_default`, and `last_updated` fields.
- When a user edits a prompt, `is_default` flips to `false`.
- Taui only overwrites prompts where `is_default` is `true` during upgrades.
- `prompts.reset` reverts a prompt to the built-in default and sets `is_default` back to `true`.

## Design

### Prompt Types

| Prompt | What it controls |
|---|---|
| `prime_system` | Prime agent behavior, personality, instructions |
| `root_agent_system` | Root agent (long task) behavior |
| `sub_agent_system` | Sub-agent behavior, scoping rules |
| `tangle_maker` | How agents write/structure tangle documents |
| `tangle_reviewer` | How agents review/update existing tangles |

### Storage Format

```json
{
  "prompts": {
    "prime_system": {
      "content": "You are the prime agent...",
      "is_default": true,
      "last_updated": "2026-04-07"
    },
    "tangle_maker": {
      "content": "When writing a tangle, include...",
      "is_default": false,
      "last_updated": "2026-04-10"
    }
  }
}
```

### How This Replaces Frontmatter Structure

The old plan pushed `refs`, `test_refs`, `depends_on`, `tags`, `status`, `owners` into frontmatter. Now:

- The `tangle_maker` prompt says: "When writing a tangle, include a Dependencies section with markdown links..."
- The user can edit this to: "Skip Dependencies. Always include a Testing Strategy section instead."
- The tangle format only requires `title` and `last_updated` in frontmatter. Everything else is free-form body content shaped by the prompt.

## Code References

- `taui/config/project_settings.py:default_prompt_content` — default prompt text for all 5 prompt types
- `taui/config/project_settings.py:ProjectSettingsStore.list_prompts` — lists all prompts
- `taui/config/project_settings.py:ProjectSettingsStore.get_prompt` — gets single prompt
- `taui/config/project_settings.py:ProjectSettingsStore.update_prompt` — updates prompt, sets is_default=False
- `taui/config/project_settings.py:ProjectSettingsStore.reset_prompt` — resets to default, sets is_default=True
- `taui/agent/system_prompt_loader.py:get_prompt_template_for_workspace` — loads prompt for agent role, checks settings first then fallback to system_prompts.md
- `taui/agent/system_prompt_loader.py:render_prompt_template` — fills template variables
- `taui/agent/system_prompt_loader.py:_load_sections` — parses system_prompts.md into sections
- `taui/server/handlers.py:_handle_prompts_list` — RPC handler
- `taui/server/handlers.py:_handle_prompts_get` — RPC handler
- `taui/server/handlers.py:_handle_prompts_update` — RPC handler
- `taui/server/handlers.py:_handle_prompts_reset` — RPC handler
- `app/src/lib/services/backend-client.ts:BackendClient.promptsList` — frontend RPC call
- `app/src/lib/services/backend-client.ts:BackendClient.promptsUpdate` — frontend RPC call
- `app/src/lib/services/backend-client.ts:BackendClient.promptsReset` — frontend RPC call

## Tests / Verification

- `tests/test_prompts.py` — 10 tests: all five prompt keys, list/get/update/reset, persistence, upgrade simulation
- `tests/test_settings.py` — settings.json lifecycle including prompt section

```
pytest tests/test_prompts.py tests/test_settings.py -q
```

## Open Questions

- Should prompts support template variables (e.g., `{{project_name}}`, `{{tangle_tree}}`)?
- Should there be a UI preview of how a prompt will affect tangle generation?

## Related Decisions

- [Minimal Frontmatter](../decisions/0001-minimal-frontmatter.md)
