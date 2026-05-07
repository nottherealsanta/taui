1. Make the public story match the code
     README.md is stale: it still says CLI default, TUI opt-in, and Web opt-in, while current
     project instructions and taui/main.py say the Textual TUI is the default and only
     interface. Fix README and docs so every entry point says the same thing.
  2. Finish self-edit as one clear workflow
     self-edit-plan.md is on the right track. The important thing is to avoid two competing
     models:
      - panel inventory + verbs
      - old chat-listing verbs like agents, tools, new tool

     The polished version should be: enter /i, select row or type add tool, then use a small
     verb set. Remove the old inventory-printing path once the panel exists.
  3. Treat extensions as the only customization boundary
     This is the simplifier. Self-edit should create/edit:
      - .taui/extensions/*.py
      - .taui/self_edit/agents/*.md
      - .taui/skills/*/SKILL.md

     It should not imply the agent can patch core Taui during normal use. Built-ins should be
     read-only with a “copy/mirror as extension” route.
  4. Add lifecycle guarantees before adding polish
     These are required for trust:
      - refuse /i while the current agent turn is active, or implement real pause semantics
      - restore the exact prior loop on /q
      - surface reload errors inline
      - keep the user in self-edit mode if reload fails badly enough
      - clear selection when a selected row disappears after refresh
  5. Ship playbooks as real packaged assets
     taui/self_edit/playbooks/*.md should be included in package data and tested. The playbooks
     are product surface, not just prompts. They need to be short, concrete, and example-driven.
  6. Add focused tests around the new contract
      - loop freeze/restore
      - panel refresh and selection
      - rm confirmation
      - playbook prompt composition
  7. Polish the TUI details
     After correctness:
      - tab completion for self-edit verbs and targets
      - empty states for each panel section
      - README.md
      - docs/architecture.md
      - specific architecture docs that match current code
      - one self-edit spec