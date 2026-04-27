# TUI (Terminal User Interface)

Rich terminal UI built with [Textual](https://textual.textualize.io/). Opt-in via `taui --tui`. Provides a split-pane interface with message history, live tool output, and an input bar.

---

## Architecture

```
taui --tui
  │
  └── TauiApp (textual.App)
        │
        ├── on_mount()
        │   ├── Session.create(config)
        │   └── Wire callbacks (tool_call, tool_result, text)
        │
        ├── Layout:
        │   ┌──────────────────────────────┐
        │   │  Header (taui title)         │
        │   ├──────────────────────────────┤
        │   │  MessageLog (scrollable)     │
        │   │  - User messages (green)     │
        │   │  - Agent responses           │
        │   │  - Turn summaries            │
        │   ├──────────────────────────────┤
        │   │  ToolLog (compact, docked)   │
        │   │  - Tool calls (cyan)         │
        │   │  - Tool results (dim/red)    │
        │   ├──────────────────────────────┤
        │   │  StatusBar (provider/model)  │
        │   ├──────────────────────────────┤
        │   │  Input bar                   │
        │   ├──────────────────────────────┤
        │   │  Footer (keybindings)        │
        │   └──────────────────────────────┘
        │
        └── Event handling:
            ├── Input.Submitted → send message or handle command
            ├── Ctrl+C          → quit
            └── Ctrl+L          → clear messages
```

---

## Widgets

| Widget | Role | CSS Class |
|--------|------|-----------|
| `MessageLog` | Scrollable message history with Rich markup | `RichLog`, border accent |
| `ToolLog` | Compact tool call/result display, docked bottom | `RichLog`, 10 lines height |
| `StatusBar` | Shows `provider/model · cwd` | `Static`, docked bottom |
| `Input` | Text input with placeholder | Standard `Input` |

---

## Agent Callbacks

The TUI wires into the same callback hooks as the CLI REPL:

| Callback | Display |
|----------|---------|
| `on_tool_call` | `[cyan]▸ tool_name[/cyan](args...)` in ToolLog |
| `on_tool_result` | First line of error in red, or compact dim summary |
| `on_text` | No-op (full response shown after `send()` completes) |
| `on_question` | Shows question in yellow in MessageLog (basic support) |

---

## Slash Commands

| Command | Action |
|---------|--------|
| `/help` | Show available commands |
| `/clear` | Clear message log |
| `/quit`, `/q`, `/exit` | Exit the TUI |

---

## Key Bindings

| Key | Action |
|-----|--------|
| `Enter` | Submit message |
| `Ctrl+C` | Quit |
| `Ctrl+L` | Clear messages |

---

## Concurrency

Messages are sent using Textual's `@work(exclusive=True)` decorator, which runs the agent interaction in a worker thread without blocking the UI. The `_busy` flag prevents sending while a previous message is in progress.

---

## Dependencies

```
pip install textual
```

Textual is imported at call time — the rest of taui works without it.

---

## CLI Integration

```bash
taui --tui                          # launch terminal UI
taui --tui -p codex -m o3-mini      # with provider/model overrides
taui --tui -d /path/to/project      # explicit working directory
```

---

## Module Layout

```
taui/tui.py     # TauiApp, MessageLog, ToolLog, StatusBar, run_tui()
```

Single file — the TUI is a presentation layer over the existing `Session` and `AgentLoop`.
