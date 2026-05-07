# Taui
There are many coding harnesses out there. Taui is the one you can reshape.

Taui is a highly customizable agentic coding interface. Instead of adapting your workflow to a fixed assistant, you control the interface itself: UI, agent, tools, prompts, and storage.

Taui is a full-screen Textual TUI. Running `taui` starts the terminal interface: sidebar, scrollable chat, live streaming, tool status, approvals, questions, steering, and queued follow-up messages.

The defaults are intentionally focused. The goal is not to ship several competing shells, but to provide one polished interface with extension points for tools, prompts, commands, skills, storage, and agent behavior.

## How It Works

1. Start from a prompt, plan, spec, or tangle.
2. Ask the agent to inspect, plan, edit, or implement.
3. Spawn sub-agents when a task should be split into focused sub-work.
4. Let Taui call tools, update state, and feed results back into the conversation.
5. If the interface itself gets in your way, enter `/i` to reshape it — change tools, prompts, UI, or storage. Changes land as extensions that can't break the core.

## Self-Edit Mode

The central idea: `/i` enters self-edit mode, where Taui can modify its own UI, agent behavior, tools, prompts, and storage.

Self-edits are treated as extensions, not patches to the core. When you modify Taui through `/i`, the changes land in an extension layer that sits on top of the base system:

- **Extensions are isolated.** A broken extension (bad tool, crashing hook, malformed prompt) does not take down the core agent loop, the Store, or the TUI. The base system always remains functional.
- **Extensions are reversible.** Every self-edit is logged to the Store. You can list active extensions, disable one, or roll back to the base state.
- **Extensions are scoped.** An extension can be project-local (only active in this workspace) or global (active everywhere). The agent can create either.
- **The core is protected.** Self-edit mode cannot modify the core agent loop, the Store schema, or the transport layer. It can extend tools, add UI components, modify prompts, and register new commands — but the base system is not in the blast radius.

If the agent breaks something through `/i`, start Taui with extensions disabled once that recovery flag is available, then fix or remove the offending extension from `.taui/extensions/`.

See [self-edit.md](architecture_docs/self-edit.md) for the full extension system design — scopes, lifecycle, loading order, and what self-edit can and cannot touch.

## Core Capabilities

- Sub-agents can be spawned for focused sub-tasks; each child completes by calling the sub-agent-only return-to-parent tool with required context, and the parent waits for that handoff before continuing.
- Tools are part of the system surface, so Taui can create or extend tools and use them in later conversations.
- TUI customization can change layout, panes, and interaction patterns instead of forcing a fixed workflow.
- Storage customization lets you change how Taui stores specs, tangles, history, or other project state.
- Agent memory allows agents to retain useful context from prior conversation state and use it in later decisions.
- LSP integration can provide code intelligence such as completion, navigation, and symbol lookup.
- Clarification and amendment workflows let agents ask concrete questions when they hit ambiguity instead of guessing, and propose spec amendments when implementation conflicts with the current plan.
- Tool policies control which tools are auto-approved, which require confirmation, and which are forbidden. Policies are configured per tool, per agent, per project, or globally — most specific wins. See [architecture.md](architecture.md) for default policies per tool.
- Skill system lets agents install, load, and use skills as reusable capability packages that extend what they can do. Skill tokens are estimated as chat_count / 4 = n_tokens; if current context plus estimated skill tokens exceeds 80 percent of window size, Context Manager compaction runs before injection. Skill context is not pinned by default.

## Advanced Workflows

- Branch-like message history lets you fork a conversation at any point and explore alternate paths.
- Prompt-level customization lets you tune how the agent behaves.
- Taui can support spec-driven or tangle-driven workflows where prose, planning, and implementation stay close together.
- Durable store makes agent sessions an append-only event log in SQLite. Clients can reconnect, replay from any offset, and multiple windows can watch the same session. Token streaming survives page refresh.
- Single-process runtime is the default: the TUI and agent runtime run in one Python process to keep streaming and coordination simple. Components are modular with explicit interfaces, so they can be separated into distinct processes later without redesigning boundaries.
- Session replay lets you replay or audit any past agent run step by step, since everything is logged to the same SQLite store.
- Git-aware workflows let agents branch, commit, diff, and open PRs as part of their tool surface, not just edit files.

## Design Goal

Taui is meant to be a coding interface you can evolve, not just use. The default app is minimal on purpose. The architecture is the product.

---

## Future Extensions

See [future.md](future.md) for ideas the architecture can support but that are not current requirements.

---

## Self-Edit & Extensions

See [self-edit.md](architecture_docs/self-edit.md) for the extension system — how `/i` works, extension scopes, lifecycle, and boundaries.

## Architecture

See [architecture.md](architecture.md) for the full architecture, component descriptions, diagrams, and per-agent vs shared scoping.
