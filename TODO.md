# TODO

- [x] **Self-edit hotreload.** On exiting `/i` mode, auto-rebuild system prompt + tools + agent config so changes take effect immediately — no new session needed. `reload_extensions()` exists but doesn't rebuild the system prompt or re-register agent-level changes; chain it with `update_system_prompt()`.

- [x] **Dynamic context UI refresh.** The rendered system prompt block (shown at first user message) and tool list should reactively update when agent config changes. Same for permissions and anything else tied to the agent. Currently static after session creation. `update_system_prompt()` exists on `AgentLoop` — wire it to config changes.

- [ ] **Color tweaks.** Self-edit elements should be yellow. Markdown should not default to orange. System prompt and tools headings at top should match the active agent's color — signifying they change with the agent.

- [ ] **Tool rendering.** Better visual styling and per-tool-type structured output: diffs for edit, line numbers for read, tables for grep, trees for repo_overview. Multi-line per tool if needed. when a tool takes a while, for example bash or sub-agent, then show a spinner instead of ✦. 
"""
<tool name> <args>
<tool output (multi-line if needed)>
"""
for edit tool output could be diff(up to 10 line) else just show the number of added/removed lines. For read tool, just show argument, including offset and limit number if any. For grep, show only number of matches. for most tools keep the output to 1 line if possible.

- [ ] **Smart notifications.** In-app Textual toast notifications when taui is the focused window. macOS OS-level notifications when taui is backgrounded (e.g. agent task completion). Needs terminal focus detection (`\e[?1004h` focus reporting) and `osascript` or `terminal-notifier` for OS notifications. use only """ printf "\e]777;notify;Header;Your message here\a" """ for notifications on macos. raise notification when agent finishes, or when asking questions to user. this behaviour is customizable. 

- [x] **research dynamic rendering with widgets** use textual widgets to render. for example, ability to toggle dropdown of the assistant message for every user message - like having a chevron to click to expand/collapse the assistant messages to a particular user message - then auto collapsing for any message older than current_message - 2. or another example is to peek more into every tool output.