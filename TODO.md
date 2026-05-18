# TODO

- [x] **Self-edit hotreload.** On exiting `/i` mode, auto-rebuild system prompt + tools + agent config so changes take effect immediately — no new session needed. `reload_extensions()` exists but doesn't rebuild the system prompt or re-register agent-level changes; chain it with `update_system_prompt()`.

- [x] **Dynamic context UI refresh.** The rendered system prompt block (shown at first user message) and tool list should reactively update when agent config changes. Same for permissions and anything else tied to the agent. Currently static after session creation. `update_system_prompt()` exists on `AgentLoop` — wire it to config changes.

- [x] **Tool rendering.** Better visual styling and per-tool-type structured output: diffs for edit, line numbers for read, tables for grep, trees for repo_overview. Multi-line per tool if needed. when a tool takes a while, for example bash or sub-agent, then show a spinner instead of ✦. 
"""
<tool name> <args>
<tool output (multi-line if needed)>
"""
for edit tool output could be diff(up to 10 line) else just show the number of added/removed lines. For read tool, just show argument, including offset and limit number if any. For grep, show only number of matches. for most tools keep the output to 1 line if possible.

- [ ] **Smart notifications.** In-app Textual toast notifications when taui is the focused window. macOS OS-level notifications when taui is backgrounded (e.g. agent task completion). Needs terminal focus detection (`\e[?1004h` focus reporting) and `osascript` or `terminal-notifier` for OS notifications. use only """ printf "\e]777;notify;Header;Your message here\a" """ for notifications on macos. raise notification when agent finishes, or when asking questions to user. this behaviour is customizable. 

- [x] **research dynamic rendering with widgets** use textual widgets to render. for example, ability to toggle dropdown of the assistant message for every user message - like having a chevron to click to expand/collapse the assistant messages to a particular user message - then auto collapsing for any message older than current_message - 2. or another example is to peek more into every tool output.

- [x] **Change window title.** Dynamically set the terminal window/tab title to reflect current state (e.g., agent name, session info). Use ANSI escape `\e]0;title\a`.

- [x] **Pasted content as attachment.** When multi-line text is pasted into the input, treat it as a collapsible attachment (like pasted images) rather than inline text.

- [x] **Rich text input movement.** Support VS Code-style text editing in the chat input: shift+arrow for selection, ctrl/cmd+arrow for word-jump, shift+ctrl for word-select, overwrite selected text by typing, etc. Standard editor keybindings that terminals don't provide by default.

- [x] **Question UI: paste support.** The custom answer input field in the question tool UI doesn't support paste — fix it.

- [x] **Question UI: mouse click shouldn't dismiss.** Clicking the custom answer option currently dismisses the question UI prematurely. It should select/focus the custom answer field for editing instead.

- [x] **Commands with optional args.** Slash commands should support optional arguments. E.g., `/new` starts a fresh session, `/new <message>` starts fresh with an initial message.

- [x] **Command with required args: no-op on empty enter.** If a slash command requires arguments and the user hits enter without providing them, do nothing (no-op) instead of erroring.

- [x] **`/agents` and `/models` dual trigger fix.** Currently typing `/agents` or `/models` fully + space shows results in the info bar, AND selecting them from the command palette also triggers. Selecting agents/models from the command palette should open the info2 panel for selection instead.

- [x] **`@` file/folder reference should be lazy.** When `@`-mentioning a file or folder, only keep the reference (the path) in context — don't inline the entire file content. The model can then choose to use the read tool if it needs the contents.

- [ ] **Enable word wrap in edit diff rendering.** Diff output for edit tools should wrap long lines instead of clipping or horizontal scrolling. Default to "split" (side-by-side) diff mode.

- [ ] **Faster `/new` session creation.** Reduce the time it takes to go from `/new` to a fully ready new session.

- [x] **Remove `/session` command.** Only keep `/sessions` (plural); remove the singular `/session` variant.

- [x] **Preserve newlines in user messages.** When rendering user messages in the chat log, display newlines as actual line breaks instead of collapsing them.

- [x] **Show agent ID in collapsed message summary.** Include the agent identifier in the collapsed/summary view of messages.

- [ ] **Auto-update provider models from models.dev.** Pull model metadata from models.dev at least once per day (on startup if stale). Add a `/update-providers-models` slash command to trigger a manual refresh on demand. Cache results locally and update the available models list for all providers.