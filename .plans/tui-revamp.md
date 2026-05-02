# TUI Revamp Plan

## Phase 1: Cleanup & Core TUI (Foundation)

### 1.1 Delete CLI code
- Delete `taui/cli/` package entirely
- Delete `taui/server/` package entirely
- Remove `prompt-toolkit` from dependencies
- Remove `[web]` optional dependencies (fastapi, uvicorn, websockets)
- Remove `[tui]` optional group — make `textual>=3.0` a core dependency

### 1.2 New entry point
- Create `taui/main.py` with `main()` that launches TUI directly
- Update `pyproject.toml`: `taui = "taui.main:main"`
- Support only: `taui`, `taui --version`, `taui --help`
- Remove `--tui`, `--web`, `--print`, `--json` flags

### 1.3 Restructure TUI into a package
```
taui/tui/
├── __init__.py              # exports run_tui()
├── app.py                   # TauiApp(App) — main Textual app
├── screens/
│   ├── __init__.py
│   ├── main.py              # MainScreen
│   ├── model_selection.py   # Modal: model picker
│   ├── context_breakdown.py # Modal: token usage
│   └── diff_view.py         # Modal: diff on click
├── widgets/
│   ├── __init__.py
│   ├── conversation.py      # Central orchestrator
│   ├── agent_response.py    # Streaming via MarkdownStream
│   ├── chat_input.py        # TextArea: Enter/Alt+Enter, history, steering/queue
│   ├── tool_status.py       # Per-tool animated braille spinner
│   ├── status_bar.py        # Model + context % bar
│   ├── context_pane.py      # Inline context popup
│   ├── model_selector.py    # Inline model picker popup
│   ├── sidebar.py           # Plan + project directory tree
│   ├── spinner.py           # Global thinking spinner
│   ├── footer.py            # Key legend
│   ├── terminal.py          # Embedded terminal emulator
│   └── approval.py          # Inline approval + question answering
└── styles.tcss              # Textual CSS
```

### 1.4 Streaming responses with MarkdownStream
- Replace RichLog with Markdown + MarkdownStream
- Token fragments from `_on_text` → `stream.write(fragment)`
- Smart scroll: only auto-scroll if user near bottom

### 1.5 Steering and Queue in TUI
- ChatInput stays enabled while agent works (no _busy blocking)
- Enter while busy → `session._loop.steer(text)` (inject between tool calls)
- Alt+Enter while busy → append to `_queued` (follow-up after turn)
- Enter while idle → normal send
- Alt+Enter while idle → insert newline
- Visual indicators: pending steer/queue above input (dimmed, s/q prefix)
- Queue drain: after send() completes, drain _queued sequentially
- Ctrl+C while busy: cancel + clear both queues

### 1.6 Tool status widgets
- ToolStatusWidget with animated braille spinner per tool
- FIFO queue matching tool_start → tool_end
- Green check on success, red on failure, truncated preview
- Tool section grouping per LLM turn

## Phase 2: Rich UI Features

### 2.1 Sidebar
- Left pane: collapsible project directory tree
- Toggle: Ctrl+B
- Show agent plan/todo if available

### 2.2 Diff view modal
- Clickable "View changes" in tool status
- Modal with side-by-side/unified diff
- Dismiss with Escape

### 2.3 Embedded terminal
- For bash/shell tools, embed live terminal widget
- Support kill, wait-for-exit

### 2.4 Model selection & context screens
- Ctrl+T → inline ModelSelector popup
- Click model → modal ModelSelectionScreen
- Click context bar → modal ContextBreakdownScreen
- Inline ContextPane popup

### 2.5 Approval & question flow
- Approval: inline `Allow [tool]? [y/N]` prompt
- Question: selectable option list, return answer to agent

## Phase 3: Polish & Testing

### 3.1 Input enhancements
- Command history (persist, Up/Down navigation)
- @file expansion
- Slash command tab completion

### 3.2 Visual polish
- Markdown heading colors
- Mouse auto-copy on selection
- Kitty keyboard protocol
- Reasoning text display (dim)

### 3.3 Testing
- Unit tests for ChatInput steering/queue
- Integration: steer between tool calls
- Integration: queue fires after turn
- Ctrl+C clears both queues
- MarkdownStream rendering
- Tool status FIFO matching
- Approval and question flows

### 3.4 Documentation
- Rewrite AGENTS.md (TUI-only)
- Update pyproject.toml metadata
- Remove CLI/web references from README

## Files to Delete
- `taui/cli/` (entire package)
- `taui/server/` (entire package)

## Files to Create
- `taui/main.py` (new entry point)
- `taui/tui/` (restructured package, see 1.3)

## Files to Modify
- `pyproject.toml` (entry point, deps)
- `AGENTS.md` (delete and rewrite)
