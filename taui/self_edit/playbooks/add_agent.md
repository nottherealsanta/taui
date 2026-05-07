## Active playbook: add agent

The user wants to add a new sub-agent profile.

### Where agents live

- Metadata: `.taui/self_edit/agents.json` (project) or
  `~/.taui/self_edit/agents.json` (global). Each row in the `profiles` list looks
  like:

  ```json
  {
    "id": "RVW",
    "name": "Reviewer",
    "provider": "",
    "model": "",
    "allowed_tools": [],
    "prompt_path": ".taui/self_edit/agents/RVW.md"
  }
  ```

- Prompt: `.taui/self_edit/agents/<ID>.md` — a Markdown file with the agent's
  system prompt.

### Workflow

1. Ask the user what the agent should do (its responsibilities, tone, allowed
   tools, model preferences) if they haven't already said.
2. Pick a 3-letter uppercase ID that doesn't collide with existing agents (the
   panel's Agents section lists current IDs). Use mnemonic letters drawn from the
   role name when possible.
3. Write the prompt file at `.taui/self_edit/agents/<ID>.md` with a clear
   system prompt. Lead with "You are…" and describe the role concretely.
4. Read or create `.taui/self_edit/agents.json`. Append a new row for the agent;
   keep `provider` / `model` empty unless the user asked for a specific one,
   and keep `allowed_tools` empty (means: all tools) unless restricted.
5. Tell the user to `activate <ID>` (after exiting self-edit mode) to start using
   the agent.
