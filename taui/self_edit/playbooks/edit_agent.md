## Active playbook: edit agent

The user wants to edit an existing agent.

### What to edit where

- **Prompt changes** → edit the Markdown prompt file at
  `.taui/self_edit/agents/<ID>.md`. This is what the agent reads as its system
  prompt at runtime.
- **Metadata changes** (name, provider, model, allowed_tools) → edit the matching
  row in `.taui/self_edit/agents.json`.

Don't move the prompt body inline into `agents.json`; the loader migrates inline
prompts back out into per-ID Markdown files, so inline prompts are wasteful.

### Workflow

1. Look at the panel — the selected row tells you the agent ID and prompt path.
2. Read the relevant file with `Read`.
3. Apply edits with `Edit`. Keep the JSON valid.
4. Confirm with the user what changed.
