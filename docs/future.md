# Future Extensions

The core is a single agent loop with sequential sub-agent spawning, running in one Python process. Everything below is for later implementation — ideas that showcase what the framework's architecture can support, not current requirements.

- **Multi-Agent Coordinator** — run multiple agent loops in parallel against the same workspace, with file locking, conflict resolution, cost rollup, and recovery when a parallel agent fails.
- **Multi-Process Runtime** — split agent execution and UI/runtime transport into separate processes for crash isolation, independent scaling, or stricter security boundaries.
- **RLM** — recursive language model workflows, where agents recursively delegate or refine work.
- **Monty** — an agent writes helper code to batch multi-step work, executes it, and returns the result.
- **Agent reflection** — an agent reviews its own output before committing, catching mistakes it would normally miss in a single pass.
