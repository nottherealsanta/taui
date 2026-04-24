---
title: Editable Prompts
last_updated: 2026-04-11
---

# Editable Prompts

User-customizable system prompts for all agent types and tangle tools.

Depends on: [Agent System](../domains/agent-system.md), [Server](../domains/server.md)

## Purpose

- Let users view and customize the system prompts that control agent behavior and tangle document structure.
- Replaces rigid frontmatter-based structure with flexible, user-controlled conventions.

## User / Business Outcome

- Users can tune agent behavior without modifying source code.
  - Teams can standardize tangle conventions by editing the `tangle_maker` prompt.
  - Different projects can have different tangle structures (e.g., a game studio vs. a SaaS team).
- Default prompts ship with taui and are upgradeable — user edits are preserved across upgrades.

## Scope

- **In scope**
  - Five prompt types: `prime_system`, `root_agent_system`, `sub_agent_system`, `tangle_maker`, `tangle_reviewer`
  - Storage in `.taui/settings.json` under the `prompts` key
  - RPC methods: `prompts.list`, `prompts.get`, `prompts.update`, `prompts.reset`
  - Settings UI: "Prompts" section where users view and edit each prompt
  - Default seeding on first run
  - Upgrade behavior: only overwrite prompts where `is_default` is `true`
- **Out of scope**
  - Per-tangle prompt overrides (all prompts are project-wide)
  - Prompt versioning / history (beyond `last_updated` timestamp)

## Constraints

- Prompts stored in `settings.json`, not in the database.
  - Each prompt has `content`, `is_default`, and `last_updated` fields.
  - When a user edits a prompt, `is_default` flips to `false`.
  - Taui only overwrites prompts where `is_default` is `true` during upgrades.
  - `prompts.reset` reverts a prompt to the built-in default and sets `is_default` back to `true`.
  - `taui/config/project_settings.py:ProjectSettingsStore.update_prompt` — sets `is_default=False` on edit
  - `taui/config/project_settings.py:ProjectSettingsStore.reset_prompt` — resets to default, sets `is_default=True`

## Design

- **Prompt types and what they control**
  - `prime_system` — prime agent behavior, personality, instructions
  - `root_agent_system` — root agent (long task) behavior
  - `sub_agent_system` — sub-agent behavior and scoping rules
  - `tangle_maker` — how agents write and structure tangle documents
  - `tangle_reviewer` — how agents review and update existing tangles
    - Default guidance now checks tree-first progressive disclosure and flags standalone code-reference sections
  - `taui/config/project_settings.py:default_prompt_content` — default text for all five types
- **Storage format** — each prompt entry in `settings.json` under the `prompts` key:
  - `content` — prompt text string
  - `is_default` — `true` until user edits, controls upgrade overwrite behavior
  - `last_updated` — ISO date string
- **How this replaces frontmatter structure**
  - Old plan pushed `refs`, `test_refs`, `depends_on`, `tags`, `status`, `owners` into frontmatter
  - Now: the `tangle_maker` prompt can shape writing style directly
    - Example default guidance: "Write tangles as 2-3 level trees for progressive disclosure; code refs are leaf nodes under the ideas they ground."
    - Teams can still customize this (for example, prefer a dedicated Testing Strategy subsection in each feature tangle)
  - The tangle format only requires `title` and `last_updated` in frontmatter; everything else is free-form body shaped by the prompt
  - See: [Minimal Frontmatter](../decisions/0001-minimal-frontmatter.md)
- **Backend RPC handlers**
  - `taui/server/handlers.py:_handle_prompts_list` — lists all prompts
  - `taui/server/handlers.py:_handle_prompts_get` — fetches single prompt
  - `taui/server/handlers.py:_handle_prompts_update` — updates prompt content
  - `taui/server/handlers.py:_handle_prompts_reset` — resets to built-in default
- **Prompt loading for agents**
  - `taui/agent/system_prompt_loader.py:get_prompt_template_for_workspace` — loads prompt for agent role, checks settings first then falls back to `system_prompts.md`
  - `taui/agent/system_prompt_loader.py:render_prompt_template` — fills template variables
  - `taui/agent/system_prompt_loader.py:_load_sections` — parses `system_prompts.md` into sections
- **Frontend RPC calls**
  - `app/src/lib/services/backend-client.ts:BackendClient.promptsList`
  - `app/src/lib/services/backend-client.ts:BackendClient.promptsUpdate`
  - `app/src/lib/services/backend-client.ts:BackendClient.promptsReset`
- **Settings persistence**
  - `taui/config/project_settings.py:ProjectSettingsStore.list_prompts` — lists all prompts
  - `taui/config/project_settings.py:ProjectSettingsStore.get_prompt` — fetches single prompt

## Tests / Verification

- `tests/test_prompts.py` — 10 tests: all five prompt keys, list/get/update/reset, persistence, upgrade simulation
- `tests/test_settings.py` — settings.json lifecycle including prompt section
- Run: `pytest tests/test_prompts.py tests/test_settings.py -q`

## Open Questions

- Should prompts support template variables (e.g., `{{project_name}}`, `{{tangle_tree}}`)?
- Should there be a UI preview of how a prompt will affect tangle generation?

## Related Decisions

- [Minimal Frontmatter](../decisions/0001-minimal-frontmatter.md)
