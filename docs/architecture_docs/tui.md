# TUI Architecture

`TauiApp` is the sole user interface for taui. It is a Textual `App[None]` that renders
a full-screen chat log, manages streaming from the agent loop, handles approvals and
tool visibility, and dispatches slash commands.

---

## Layout

`compose()` produces a single `Horizontal` layout (`#main-layout`) containing:

```
Horizontal #main-layout
├── Sidebar                       (hidden by default, width=35)
└── Vertical #chat-area
    ├── VerticalScroll #chat-log  (scrollable, anchored to bottom)
    ├── Info2 #info2              (expandable panel: completions/pickers/approval)
    ├── Vertical #chat-container
    │   ├── AttachmentsBar        (image pill strip)
    │   ├── ChatInput             (text area, hidden until session ready)
    │   └── InfoBar               (single-line status bar)
    └── ActivityProgress          (breathing/spinner, docked bottom)
```

**Startup sequence**: `on_mount` launches `_initialize_session` as a worker. The chat
panel is hidden and the spinner runs while the session is being created. Once
`Session.create()` returns, the panel is shown and `ChatInput` receives focus.

---

## Key Bindings

Defined in `TauiApp.BINDINGS`:

| Key | Action | Description |
|-----|--------|-------------|
| `Ctrl+Q` | `quit_app` | Quit |
| `Ctrl+N` | `new_chat` | New session |
| `Ctrl+C` | `cancel_request` | Cancel active request or approval |
| `Ctrl+D` | `ctrl_d` | Quit (double-press required) |
| `Ctrl+B` | `toggle_sidebar` | Show/hide sidebar |
| `Ctrl+E` | `enter_self_edit` | Enter self-edit mode |
| `Ctrl+P` | `command_palette` | Open Textual command palette |
| `Ctrl+X` | `show_context` | Open context breakdown |
| `Escape` | `escape` | Leave self-edit / dismiss panels |

`Ctrl+C` and `Ctrl+D` both track a last-press timestamp; a second press within a short
window confirms the action. `Escape` on an empty `ChatInput` with no agent busy posts
`CancelRequested`, acting like `Ctrl+C`.

---

## Custom Message Classes

Defined in `taui/tui/messages.py`.

### `ToolStarted`
Posted by `ToolController.on_tool_call` when the agent invokes a tool.

```python
ToolStarted(tool_key: str, tool_name: str, args_str: str)
```

`tool_key` is `"{name}_{counter}"` — a monotonically increasing counter per session.
`TauiApp.handle_tool_started` delegates to `ToolController.handle_tool_started`, which
creates a `ToolStatusWidget` inside the current tool section.

### `ToolEnded`
Posted by `ToolController.on_tool_result` when a tool finishes.

```python
ToolEnded(tool_key: str, tool_name: str, result: str, is_error: bool)
```

`TauiApp.handle_tool_ended` delegates to `ToolController.handle_tool_ended`, which
calls `widget.complete(result)` or `widget.fail(result)` on the matched widget.

### `StreamTextDelta`
Posted from `_on_text_delta_sync` for every LLM text token.

```python
StreamTextDelta(text: str)
```

`handle_stream_text` appends to the current `AgentResponse` widget, creating one if
needed. If reasoning was in progress, it is finalized first.

### `StreamReasoningDelta`
Posted from `_on_reasoning_delta_sync` for reasoning tokens.

```python
StreamReasoningDelta(text: str)
```

`handle_stream_reasoning` buffers up to 300 characters into a dim/italic `Static`
widget. When regular text starts arriving, the reasoning widget is finalized in place.

### `AgentBusy` / `AgentIdle`
Marker messages (no fields) for when the agent starts and finishes processing. Used to
communicate busy state to consumers that need lifecycle events. `TauiApp` itself tracks
`_is_processing` directly via `_set_busy(bool)`.

### `CompactionOccurred`
Posted by `_on_compact_sync` when the agent loop auto-compacts context.

```python
CompactionOccurred(removed: int, before_tokens: int, after_tokens: int)
```

`handle_compaction` mounts a dim status line in the chat log with before/after token
counts.

---

## ToolController

`taui/tui/tool_controller.py` — owns all mutable state for in-flight tool calls.

**State:**

| Field | Type | Purpose |
|-------|------|---------|
| `_tool_counter` | `int` | Monotonically increases; makes each tool invocation's key unique |
| `_pending_tool_keys` | `dict[str, list[str]]` | FIFO queue of keys per tool name; matches starts to ends |
| `_active_tool_widgets` | `dict[str, ToolStatusWidget]` | Maps tool key → live widget |
| `_current_tool_section` | `Vertical \| None` | Current `.tool-section` container in the chat log |

**Tool key matching:**

`on_tool_call` increments `_tool_counter` and pushes `"{name}_{counter}"` onto
`_pending_tool_keys[name]`. `on_tool_result` pops the first key from
`_pending_tool_keys[name]` (FIFO). If the queue is empty it falls back to a prefix
scan of `_active_tool_widgets`. This handles concurrent tool calls with the same name
in correct issue order.

**Widget lifecycle:**

`handle_tool_started`:
1. Calls `_finalize_response()` to close any open streaming text block.
2. Creates a new `Vertical(classes="tool-section")` if `_current_tool_section` is None.
3. Mounts a `ToolStatusWidget` inside the tool section.

`handle_tool_ended`:
1. Pops the widget from `_active_tool_widgets`.
2. Calls `widget.complete(result)` or `widget.fail(result)`.

`reset()` clears all state and is called on session reset. `reset_section()` nulls only
`_current_tool_section`; called before each turn and after `_finalize_response()`.

---

## Widgets

### `ChatInput`

Extends `TextArea`. Manages user input, history, image attachments, and slash-command
completions.

**Key bindings (in `_on_key`):**

| Key | Behaviour |
|-----|-----------|
| `Enter` | Submit (`_do_submit`) |
| `Shift+Enter` / `Ctrl+J` | Insert newline |
| `Alt+Enter` | Queue message if agent busy; else insert newline |
| `Tab` | Accept completion; or cycle agent profile (normal) / scope (self-edit) |
| `Escape` (empty input) | Post `CancelRequested` |
| `Escape` (with content) | Double-press within 0.4s clears input and posts `InputCleared` |
| `Up` / `Down` | History navigation when cursor is on first/last line |
| `Ctrl+V` | Read image from system clipboard |

**Messages posted:**

- `Submitted(value, queue, images)` — normal or queued send
- `AgentCycleRequested` — Tab when not in self-edit
- `ScopeCycleRequested` — Tab when in self-edit mode
- `InputCleared` — double-Escape clear
- `CancelRequested` — Escape on empty input
- `ImageAttached(count)` — after paste/clipboard attach

**`@file` expansion** is done in `TauiApp._expand_file_refs` before the message is sent.
Words starting with `@` are resolved relative to `config.working_dir`. Image extensions
are encoded as base64 data URLs; text files are inlined as fenced code blocks.

**Image paste support:**

`_on_paste` intercepts `Paste` events. It checks each line for image file paths
(handling plain paths, quoted paths, shell-escaped spaces, `file://` URIs). Recognized
images are base64-encoded and queued in `_pending_images`; the path text is not inserted
into the input. `Ctrl+V` calls `_read_clipboard_image` directly, using `pngpaste` (macOS)
or `xclip` (Linux) as backends.

**Prompt history** is loaded from `~/.cache/taui/prompt_history` (up to 500 entries,
newest first). Entries are appended on submit and saved to disk.

**Slash-command completions** are driven by `_completions: list[Completion]` where each
entry is `(name, description, accepts_args)`. The dropdown is rendered inside `Info2` in
`COMPLETIONS` mode. Per-command argument completers are registered via
`set_arg_completer(command_name, fn)`.

### `Sidebar`

A `Vertical` of width 35, hidden by default. Contains a directory header label,
`DirectoryTree` rooted at `config.working_dir`, and a `TaskPanel` for task display.
Toggled with `Ctrl+B` via `toggle()` which adds/removes the `.visible` CSS class.
The `Escape` binding in `Sidebar.BINDINGS` calls `action_dismiss`.

### `ToolStatusWidget`

A horizontal widget displaying a single tool execution row.

```
✦  tool_name  arg_summary…
```

On creation the icon and name are shown. After completion `complete(output)` replaces
the args with a truncated (150 char) single-line output preview. On failure `fail(error)`
shows `Failed` and up to 200 chars of the error in red. Mounted inside `Vertical.tool-section`
containers in the chat log.

### `ApprovalPrompt`

An inline widget that renders `Allow tool_name(args_summary)?` with Allow/Deny buttons.
Exposes `wait_for_response() -> bool` backed by an `asyncio.Future`. Posted `Responded`
message carries `approved: bool`. The `_future` is resolved by button press.

The approval flow is orchestrated by `ApprovalController` (not `TauiApp` directly).
Approvals are rendered inside `Info2` in `APPROVAL` mode with five options: Allow once,
allow all for this session pattern, allow all via project extension, allow all via global
extension, or Deny.

### `InfoBar`

A single-line `Horizontal` below the chat input. Renders:

- **EXT** badge (yellow) when `extensions_mode` is active
- **PLAN** badge (purple) when `plan_mode` is set
- `AgentBadge` — clickable active agent ID; color determined by `_agent_color(agent_id)`
- `ModelBadge` — model name (clickable, opens model picker)
- `ProviderBadge` — provider name (clickable, same action as model badge)
- `ContextBadge` — `{tokens}/{max_tokens}` formatted as `Nk/Mk` (clickable, opens context)
- Cost static — `$N.NNNN` when cost > 0
- `SessionBadge` — `⏱` icon; clickable, opens session picker

Click handlers post `InfoBar.*Clicked` messages caught by `TauiApp` event handlers.

`update_info(...)` rebuilds all child statics. All fields are keyword-only.

### `Info2`

A `ScrollableContainer` that acts as a unified panel above the input, replacing
`ChatInput`'s dropdown and the old modal screens for model/session picking. Always
present in the DOM; shown/hidden by adding/removing the `.active` class.

**Modes** (`Info2Mode` enum):

| Mode | Content |
|------|---------|
| `HIDDEN` | Nothing displayed |
| `COMPLETIONS` | Slash-command autocomplete list |
| `MODELS` | Inline model picker |
| `AGENTS` | Inline agent picker |
| `SESSIONS` | Inline session picker |
| `CONTEXT` | Inline context tree (read-only `Tree`) |
| `APPROVAL` | Tool approval prompt with 5 options |
| `QUESTIONS` | Multi-question panel via `QuestionsPanel` |

Navigation: `move_up()` / `move_down()` cycle `selected_index` modulo item count and
call `_update_highlight()`. `accept()` dispatches based on mode.

**Messages posted:**

- `CompletionSelected(value, accepts_args)`
- `ModelSelected(model_id)`
- `AgentSelected(agent_id)`
- `SessionSelected(session_id)`
- `ApprovalResponse(approved, pattern)`
- `Dismissed`

`show_approval` stores an `asyncio.Future`; `wait_for_approval()` awaits it.
`accept()` in `APPROVAL` mode resolves the future with an `ApprovalResult` whose
`pattern` or `tool_scope` fields trigger auto-approve extension generation.

---

## Screens

### `ContextBreakdownScreen`

> **Note:** This modal screen exists in `taui/tui/screens/context_breakdown.py` but the
> current `TauiApp` renders context inline via `Info2.show_context_tree()`. The screen
> is retained for potential future use.

A `ModalScreen[None]`. Takes `messages` and `max_tokens`. Renders:
- Total token count and percentage
- Per-role breakdown (System, User Messages, Assistant, Tool Results) with ASCII bar
  charts colored green/yellow/red by percentage

Dismissed by the Close button or `Escape`.

### `SessionPickerScreen`

> **Note:** Session picking is now inline via `Info2.show_sessions()`. This screen
> exists in `taui/tui/screens/session_picker.py` for the `@on(Info2.SessionSelected)`
> path still using it indirectly via `_show_session_picker` → `Info2`.

A `ModalScreen[str | None]` that presents sessions as a tree (parent → children) in an
`OptionList`. `_build_tree_order` recurses parent/child links from `parent_session_id`.
Each row shows: session ID, description (or created timestamp), message count, and
relative time. Returns the selected `session_id` or `None` on dismiss.

---

## Streaming Rendering

Each agent turn follows this sequence inside `_do_send`:

1. `_begin_reply_footer()` mounts a `ReplyFooter` (agent ID + model label) at the
   bottom of the chat log. All subsequent widgets for this turn are mounted *before*
   this footer via `_mount_in_reply(widget)`.
2. `session.send(text, images)` is awaited. As the LLM streams:
   - `_on_text_delta_sync` is called synchronously by the provider, posts
     `StreamTextDelta`. The handler creates an `AgentResponse` on first delta and
     appends text incrementally.
   - `_on_reasoning_delta_sync` posts `StreamReasoningDelta`. The handler maintains a
     buffered display (capped at 300 chars) in a dim/italic `Static`.
3. When a tool call begins, `ToolController.handle_tool_started` calls
   `_finalize_response()` to close the open `AgentResponse`, then mounts the tool
   section and widget.
4. After `session.send()` returns, `_finalize_response()` is called to flush any
   remaining buffer. If `_streamed_text` is false (no streaming occurred), the full
   `result.text` is mounted as a `Markdown` widget.
5. A turn-summary line (cost, `turn_summary` hook output) is appended if non-empty.

**Auto-scroll**: The `#chat-log` `VerticalScroll` is anchored with `anchor()` on
mount and on every explicit user submission (`_snap_to_bottom`). Textual's compositor
keeps it pinned to the bottom. Scrolling up releases the anchor; scrolling back to the
end re-engages it.

---

## Steering While Busy and Queued Follow-ups

`ChatInput` sets `agent_busy` from `TauiApp._set_busy()`. When busy:

- **Enter** — `ChatInput.Submitted` fires with `queue=False`. `handle_input` calls
  `session._loop.steer(text)`, which puts the message in the loop's `_steering_queue`.
  A `steer-indicator` (`s> text`) is mounted in the chat log.
- **Alt+Enter** — `ChatInput.Submitted` fires with `queue=True`. `handle_input` appends
  `(text, images)` to `TauiApp._queued`. A `queue-indicator` (`q> text`) is shown.

After `_do_send` finishes the current message it loops over `_queued` and calls
`_do_send` for each entry. `_send_and_drain` is marked `@work(exclusive=True)`, so
only one drain worker runs at a time.

---

## Slash Command Dispatch

`_handle_command(cmd)` is called whenever `ChatInput` submits a string starting with
`/`. The flow:

1. Special-cased commands are handled inline: `/quit`, `/q`, `/exit`, `/i`, `/clear`,
   `/new`, and `/self-edit`.
2. For `/new`: `_begin_new_session()` tears down the in-flight turn, silences loop
   callbacks, cancels workers, and resets TUI state. The prior agent profile ID is
   saved and re-applied after the new session loop is created.
3. All other commands are passed to `self._commands.execute(cmd)` (a `CommandRegistry`).
4. `result.metadata["action"]` controls post-execution TUI side-effects:
   - `session_picker` → calls `_show_session_picker`
   - `open_model_picker` / `open_agent_picker` / `open_context_tree` → inline Info2 panels
   - `compact_requested` → runs `manual_compact` and reports token delta
   - `new_session` / `session_resumed` / `extensions_on` / `extensions_off` /
     `model_changed` / `agent_activated` → re-wires callbacks and updates status bar
   - `session_resumed` additionally calls `_render_replay()`

The Textual command palette is extended through `TauiApp.get_system_commands()` with Taui
actions, hidden slash-command entries, and direct model-switch entries from
`taui.llm_provider.models.list_models()`. Textual's built-in Theme command remains
available through `super().get_system_commands()`.

The `CommandRegistry` is built in `_build_commands()` with lazy references to session,
cost tracker, extension registry, and self-edit store. Completions are pushed to
`ChatInput` via `_refresh_command_completions()`.

---

## Session Replay from Store

`_render_replay()` clears the `#chat-log` and re-renders `session.replay_items` (a list
of `ReplayItem` objects populated by `Session._replay_stream`). Item kinds:

| Kind | Widget |
|------|--------|
| `user` | `Static` with `.user-message` class |
| `assistant` | `AgentResponse` (appended and finalized) |
| `tool_call` | `ToolStatusWidget` inside a `Vertical.tool-section` |
| `tool_result` | Updates the matching pending `ToolStatusWidget` |

Each agent turn in the replay is capped with a `ReplyFooter`. `_flush_turn_footer()` is
called when a `user` item arrives after `turn_has_content` is set. The final open turn
(if any) is flushed at the end of iteration.

`_resume_session(session_id)` calls `Session.resume_session`, re-applies callbacks and
status, then calls `_render_replay`. Failures are reported inline in the chat log.
