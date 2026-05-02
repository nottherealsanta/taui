# CLI Redesign Plan

A ground-up rethink of `taui/cli.py` — minimal core, pi-level features, Python-native.

---

## Design Philosophy

**From pi:** "Adapt the tool to your workflows, not the other way around."
**From opencode:** Full TUI with session management, model switching, and keyboard-driven navigation.
**For taui:** Take the best of both — pi's minimal, extensible CLI surface with opencode's session/model UX — and build it in Python with prompt-toolkit + Rich.

### Guiding Principles

1. **Minimal core, maximum extensibility** — The CLI ships with the essentials. Everything else loads via extensions, skills, and hooks.
2. **Editor-first input** — The prompt area is a proper editor, not a readline box. File references, path completion, multiline, image paste.
3. **Non-interactive mode is first-class** — Pipe support, `--print` mode, JSON output, stdin merging. Scripts and CI must work naturally.
4. **Keyboard-driven** — Every action has a shortcut. Customizable keybindings.
5. **Hooks everywhere** — Extensions can replace the prompt, add footer segments, intercept tool calls, render custom UI.

---

## Current State (What We Have)

| Area | Status | Notes |
|------|--------|-------|
| Interactive REPL | ✅ Working | prompt-toolkit + Rich, basic but functional |
| Slash commands | ✅ 11 commands | /help, /cost, /compact, /clear, /model, /provider, /extensions, /i, /reload, /sessions, /new |
| Streaming output | ✅ Working | Rich Markdown rendering in real-time via Live display |
| Tool approval | ✅ Working | Inline [y/N] prompt |
| Agent callbacks | ✅ 5 callbacks | on_tool_call, on_tool_result, on_approval, on_text_delta, on_text |
| Session management | ⚠️ Basic | New/resume/list |
| Non-interactive | ⚠️ Partial | Initial message works, but no --print, no stdin pipe, no JSON output |
| Keyboard shortcuts | ⚠️ Minimal | Enter to submit, Meta+Enter for newline. That's it. |
| Message queue | ✅ Working | Inline steering input visible during agent work; messages injected between tool calls |
| Model switching | ⚠️ Basic | /model command exists but no Ctrl+L selector, no model cycling |
| Thinking levels | ❌ Missing | No thinking level control |
| Context display | ❌ Missing | No context window usage indicator |
| File references | ❌ Missing | No @file in editor |
| Export/share | ❌ Missing | No session export |
| Custom keybindings | ❌ Missing | Hardcoded only |
| Themes | ❌ Missing | Single style |
| Banner/footer hooks | ✅ Working | Extensions can add lines |

---

## Target Feature Matrix (Inspired by Pi)

### Tier 1: Core (Must-Have for v0.3)

These are the features that make a coding CLI *usable* day-to-day.

#### 1.1 Editor Enhancements

| Feature | Pi Reference | Implementation |
|---------|-------------|----------------|
| **@file references** | Type `@` to fuzzy-search project files | `@` triggers `FuzzyCompleter` sourced from `glob("**/*")`. Selected path inserted as `@path/to/file`. Agent loop resolves `@` prefixed paths into file content before sending. |
| **Path completion** | Tab completes paths | Custom `Completer` that triggers on `/` or `./` patterns. Uses `pathlib.Path.iterdir()`. |
| **Multi-line** | Shift+Enter | Already works (Meta+Enter). Add Shift+Enter as alias via key bindings. |
| **!command** | `!cmd` runs bash, sends output to LLM | Parse `!` prefix in REPL loop. Run via `asyncio.create_subprocess_shell`. `!cmd` → output becomes user message. `!!cmd` → run silently. |
| **Image paste** | Ctrl+V pastes images | Detect clipboard image data via `PIL` or platform utils. Encode as base64. Requires vision-capable model detection. |

#### 1.2 Commands (Slash Commands)

Complete command set matching pi's surface:

| Command | Status | Description |
|---------|--------|-------------|
| `/help`, `/h` | ✅ Exists | Show commands |
| `/quit`, `/q` | ✅ Exists | Exit |
| `/cost` | ✅ Exists | Token usage and cost |
| `/compact` | ✅ Exists | Compact context. Add optional `[prompt]` arg for custom instructions. |
| `/clear` | ✅ Exists | Clear conversation |
| `/model` | ✅ Exists | Enhance: add fuzzy selector mode (not just `list/select`) |
| `/provider` | ✅ Exists | Keep as-is |
| `/new` | ✅ Exists | New session |
| `/sessions`, `/resume` | ✅ Exists | Enhance with fuzzy picker |
| `/login`, `/logout` | 🆕 **Add** | OAuth authentication flow for providers |
| `/settings` | 🆕 **Add** | Interactive settings editor (thinking level, theme, etc.) |
| `/name <name>` | 🆕 **Add** | Name the current session |
| `/session` | 🆕 **Add** | Show current session info (ID, tokens, cost, context %) |
| `/copy` | 🆕 **Add** | Copy last assistant message to clipboard |
| `/export [file]` | 🆕 **Add** | Export session to markdown/HTML |
| `/reload` | ✅ Exists | Hot-reload extensions, skills, prompts |
| `/hotkeys` | 🆕 **Add** | Show all keyboard shortcuts |

#### 1.3 Keyboard Shortcuts

| Shortcut | Action | Notes |
|----------|--------|-------|
| Enter | Submit message | ✅ Exists |
| Meta+Enter / Shift+Enter | Insert newline | ✅ Exists (Meta), add Shift |
| Ctrl+C | Clear editor / cancel | Change: first press clears, second quits |
| Ctrl+D | Quit | ✅ Exists |
| Escape | Cancel running agent | 🆕 Add |
| Ctrl+L | Open model selector | 🆕 Add |
| Ctrl+P / Shift+Ctrl+P | Cycle scoped models | 🆕 Add |
| Shift+Tab | Cycle thinking level | 🆕 Add |
| Ctrl+O | Collapse/expand tool output | 🆕 Add |
| Ctrl+T | Collapse/expand thinking | 🆕 Add |
| Ctrl+G | Open external editor ($EDITOR) | 🆕 Add |

#### 1.4 Message Queue

| Type | Trigger | Behavior |
|------|---------|----------|
| **Steering** | Enter while agent works | Delivered after current tool call completes |
| **Follow-up** | Alt+Enter while agent works | Delivered after agent finishes all work |
| **Cancel** | Escape while agent works | Abort current run, restore queued messages to editor |

Currently we have basic queuing. Enhance with steering vs follow-up distinction.

#### 1.5 Non-Interactive Mode

| Feature | CLI Flag | Behavior |
|---------|----------|----------|
| **Print mode** | `-p`, `--print` | Single prompt → print response → exit |
| **Stdin pipe** | pipe input | `cat file | taui -p "summarize"` merges stdin into prompt |
| **JSON output** | `--mode json` | All events as JSON lines to stdout |
| **Quiet mode** | `-q`, `--quiet` | Suppress spinner/progress in non-interactive |
| **File args** | `@file` | `taui @readme.md "review this"` includes file content |
| **Output format** | `-f json|text` | Output format control |

#### 1.6 Footer & Status Bar

The bottom toolbar should show:

```
────────────────────────────────────────────────────────────────────────
⠋ copilot/claude-sonnet-4  thinking:high  session:fix-bug  42% ctx  $0.0312
```

Components:
- Spinner (when agent working)
- Provider/model
- Thinking level indicator
- Session name (if named)
- Context window usage percentage
- Cost
- Extension-provided segments (via `toolbar` hook)

---

### Tier 2: Polish (v0.3.x)

#### 2.1 CLI Argument Expansion

Full CLI reference matching pi's surface:

```
taui [options] [@files...] [messages...]
```

| Category | Flags |
|----------|-------|
| **Modes** | (default) interactive, `-p`/`--print`, `--mode json` |
| **Model** | `-p`/`--provider`, `-m`/`--model`, `--thinking <level>` |
| **Session** | `-c`/`--continue`, `-r`/`--resume`, `--session <id>`, `--fork <id>`, `--no-session` |
| **Tools** | `--tools <list>`, `--no-tools` |
| **Resources** | `--no-extensions`, `--no-skills`, `--no-context-files` |
| **Other** | `--system-prompt <text>`, `--append-system-prompt <text>`, `--verbose`, `--offline` |

#### 2.3 Thinking Level Control

```
┌─────────────┐
│ off          │  No extended thinking
│ low          │  Minimal reasoning
│ medium       │  Balanced (default)
│ high         │  Deep reasoning
│ xhigh        │  Maximum reasoning
└─────────────┘
```

- Cycle with Shift+Tab
- Visual indicator: editor border color or prompt color changes
- Stored in session settings
- `--thinking` CLI flag

#### 2.4 Model Selector (Ctrl+L)

Interactive fuzzy model picker:
- List all available models from current provider
- Filter by typing
- Show model capabilities (vision, tool use, context size)
- Enter to select, Escape to cancel
- Implemented as a prompt-toolkit dialog overlay

#### 2.5 Context Window Display

Track and display context window usage:
- Calculate from `usage.input_tokens` / model's context limit
- Show in footer as percentage
- Color-code: green (<60%), yellow (60-80%), red (>80%)
- Trigger auto-compact warning at 80%

#### 2.6 Export & Share

- `/export` → write session to `.taui/exports/session-{id}.md` (or custom path)
- Format: Markdown with user/assistant messages, tool calls collapsed
- `/copy` → copy last assistant message to system clipboard via `pyperclip` or `subprocess`

---

### Tier 3: Advanced (v0.4+)

#### 3.1 Custom Keybindings

File: `~/.config/taui/keybindings.json` or `.taui/keybindings.json`

```json
{
  "ctrl+l": "model_selector",
  "ctrl+p": "cycle_model_forward",
  "shift+ctrl+p": "cycle_model_backward",
  "shift+tab": "cycle_thinking",
  "ctrl+o": "toggle_tool_output",
  "ctrl+g": "external_editor",
  "escape escape": "open_tree"
}
```

Each action maps to a registered `KeyAction` that the REPL executes.

#### 3.2 Themes

File: `.taui/themes/dark.toml` or `~/.config/taui/themes/dark.toml`

```toml
[colors]
prompt = "green bold"
assistant = "white"
tool_name = "cyan bold"
tool_result = "dim"
error = "red"
warning = "yellow"
footer = "#5f87af"
separator = "#444444"
thinking_off = "dim"
thinking_low = "blue"
thinking_medium = "green"
thinking_high = "yellow"
thinking_xhigh = "red bold"
```

Hot-reload: watch file with `watchdog` or check mtime on each render.

#### 3.3 Prompt Templates

Reusable prompt files: `.taui/prompts/review.md`

```markdown
Review this code for bugs, security issues, and performance.
Focus on: {{focus}}
```

Type `/review` → expands template, prompts for `{{focus}}` variable.

---

## Architecture Changes

### Current Architecture

```
cli.py (850 lines, monolithic)
├── Repl class (REPL loop + all callbacks + all rendering)
├── _SlashCompleter
├── parse_args()
├── async_main()
└── main()
```

### Proposed Architecture

```
taui/cli/
├── __init__.py          # main(), async_main(), parse_args()
├── app.py               # CliApp — top-level orchestrator
├── editor.py            # Editor — input area with @file, !cmd, path completion
├── renderer.py          # Renderer — Rich-based output (messages, tools, markdown)
├── footer.py            # Footer — status bar with model, cost, context %
├── shortcuts.py         # KeybindingManager — load, register, dispatch
├── completers.py        # SlashCompleter, FileCompleter, PathCompleter
├── commands/             # (keep existing taui/commands/ — no change needed)
├── dialogs.py           # ModelSelector, SessionPicker, SettingsEditor
└── queue.py             # MessageQueue — steering vs follow-up
```

### Key Design Decisions

#### 1. Split Repl into Composable Parts

The current `Repl` class is 500+ lines doing everything: input, output, callbacks, commands, toolbar, formatting. Split into:

- **`CliApp`** — owns the event loop, wires components together, handles lifecycle
- **`Editor`** — prompt-toolkit session with all input features (@file, !cmd, completers)
- **`Renderer`** — all Rich output (tool calls, results, markdown, errors, status)
- **`Footer`** — dynamic bottom toolbar with extensible segments
- **`MessageQueue`** — steering/follow-up queue with cancel support

#### 2. Make Renderer Stateful for Collapse/Expand

Currently tool output is fire-and-forget (print and move on). To support Ctrl+O (collapse/expand tool output), the renderer needs to track rendered blocks:

```python
@dataclass
class RenderedBlock:
    block_id: str
    block_type: Literal["tool_call", "tool_result", "thinking", "text"]
    content: str
    collapsed: bool = False
    line_range: tuple[int, int] | None = None  # terminal line range
```

Rich's `Live` display or manual ANSI cursor control to re-render collapsed blocks.

**Alternative (simpler):** Don't do live collapse. Just offer `/verbose` and `/quiet` modes that control default verbosity. Ctrl+O toggles for *future* output, not past. This is much simpler and may be sufficient.

#### 3. Non-Interactive as a Separate Code Path

Don't try to make the REPL handle non-interactive mode. Instead:

```python
async def async_main(parsed):
    if parsed.get("print_mode"):
        await run_print_mode(parsed)  # Simple: prompt → response → exit
    elif parsed.get("mode") == "json":
        await run_json_mode(parsed)   # Stream events as JSONL
    else:
        await run_interactive(parsed) # Full REPL
```

#### 4. @file Resolution in Editor, Not Agent Loop

When the user types `@src/main.py`, the editor resolves it *before* sending to the agent:

```python
# In Editor
def resolve_at_files(text: str) -> str:
    """Replace @path references with file content."""
    for match in re.finditer(r'@(\S+)', text):
        path = Path(match.group(1))
        if path.exists():
            content = path.read_text()
            text = text.replace(match.group(0), f"\n```{path.name}\n{content}\n```\n")
    return text
```

This keeps the agent loop clean and is consistent with pi's approach.

#### 5. Thinking Level as Session State

```python
@dataclass
class SessionState:
    thinking_level: ThinkingLevel = ThinkingLevel.MEDIUM
    scoped_models: list[str] = field(default_factory=list)
    session_name: str = ""
    verbose_tools: bool = True  # show full tool output
```

Stored in `Config` or `Session`, persisted to store metadata.

---

## Implementation Plan

### Phase 1: Restructure (Non-Breaking) ✅

**Goal:** Split `cli.py` into `taui/cli/` package without changing any behavior.

1. ✅ Create `taui/cli/__init__.py` with `main()`, `async_main()`, `parse_args()` (moved from `cli.py`)
2. ✅ Move `Repl` to `taui/cli/app.py` as `CliApp`
3. ✅ Extract `_SlashCompleter` to `taui/cli/completers.py`
4. ✅ Extract rendering methods to `taui/cli/renderer.py`
5. ✅ Extract footer to `taui/cli/styles.py`
6. ✅ Keep old `taui/cli.py` as a thin re-export for backwards compat
7. ✅ Update `pyproject.toml` entry point if needed
8. ✅ Run all tests — everything must pass unchanged

### Phase 2: Editor Enhancements ✅

**Goal:** Make the input area a power tool.

1. ✅ **@file completion** — Add `FileCompleter` that triggers on `@`, fuzzy-searches workspace files
2. ✅ **@file resolution** — Pre-process user input to inline file content before sending
3. ✅ **Path completion** — Tab-completes filesystem paths after `/` or `./`
4. ✅ **!command** — Parse `!` prefix, run via subprocess, inject output as user message
5. ✅ **Shift+Enter** — Add as newline alias alongside Meta+Enter

### Phase 3: Commands & Shortcuts ✅

**Goal:** Full slash command set and keyboard shortcuts.

1. ✅ Add missing commands: `/login`, `/logout`, `/session`, `/copy`, `/export`, `/hotkeys`
2. ✅ Implement keyboard shortcuts: Ctrl+C (clear/quit), Escape (cancel)
4. Deferred: Shift+Tab thinking level cycling (needs thinking level infrastructure)
5. ✅ Add `/hotkeys` command listing all shortcuts

### Phase 4: Non-Interactive & Pipes ✅

**Goal:** First-class scripting support.

1. ✅ Add `--print` flag for single-prompt mode
2. ✅ Add stdin pipe detection and merging: `cat file | taui -p "summarize"`
3. ✅ Add `--json` flag for JSONL event output
4. ✅ Add `@file` CLI arguments: `taui @readme.md "review this"`
5. ✅ Add `--quiet` flag to suppress spinner/progress

### Phase 5: Message Queue & Steering ✅

**Goal:** Interact with the agent while it works.

1. ✅ Distinguish steering (Enter) vs follow-up (Alt+Enter)
2. ✅ Steering messages delivered between tool calls
3. ✅ Follow-up messages delivered after agent finishes
4. ✅ Escape cancels and restores queued messages to editor
5. ✅ Show queue status in footer

### Phase 6: Polish ✅

**Goal:** Professional finish.

1. ✅ Context window usage tracking and display in footer (% with color-coded warning)
2. ✅ Collapsible tool output — `/verbose` toggle command (verbose/quiet modes)
3. ✅ Theme support from config file (`[taui.theme]` in config.toml)
4. ✅ Config fields for keybindings and theme (`Config.keybindings`, `Config.theme`)
5. Deferred: Thinking level indicator (needs thinking level infrastructure)
6. Deferred: Custom keybindings runtime mapping (config field ready)

### Streaming & Input Architecture

**Markdown streaming** — Rich `Live` + `Markdown` renderable. As the LLM
streams tokens, `_on_text_delta` accumulates them in `_stream_buffer` and
refreshes the Live display. The user sees fully-rendered Markdown (headings,
bold, code blocks, lists) updating in real-time. When the stream ends, the
Live display is torn down (transient) and the final Markdown is printed
permanently to the scrollback.

**Inline steering input** — While the agent is working, the terminal is set
to cbreak mode (no line-buffering, no echo, ISIG disabled). Keystrokes are
read via `asyncio.add_reader` on stdin and displayed in the bottom of the
Live renderable as `> typed text▏`. Pressing Enter injects the message into
the agent's steering queue (delivered between tool calls). Ctrl-C cancels
the active task. Ctrl-U clears the input line. Escape sequences (arrow keys
etc.) are silently discarded. When the agent finishes, the stdin reader is
torn down and prompt-toolkit's `PromptSession` resumes normal input
handling.

---

## What We Explicitly Skip (Following Pi's Philosophy)

| Feature | Why Skip | Alternative |
|---------|----------|-------------|
| Built-in plan mode | Opinionated, many valid approaches | Write plans to files, or build via extension |
| Built-in permissions UI | Environment-specific | Use hooks (`on_approval`), or build via extension |
| Built-in MCP discovery UI | Already handled by tools | MCP tool already exists |
| Background bash | Complexity, observability issues | Use tmux, or build via extension |
| Built-in git checkpointing | Opinionated workflow | Build via extension with `on_tool_call` hook |

---

## Summary

The CLI redesign brings taui from "basic REPL with slash commands" to "power-user coding interface" while keeping the core minimal and extensible. Every feature either exists in pi (proven useful) or solves a pain point visible in the current implementation.

**Lines of code estimate:**
- Phase 1 (restructure): ~0 net new lines, mostly moving code
- Phase 2 (editor): ~200-300 lines
- Phase 3 (commands): ~400-500 lines
- Phase 4 (non-interactive): ~150-200 lines
- Phase 5 (queue): ~100-150 lines
- Phase 6 (polish): ~200-300 lines

Total: ~1,100-1,700 lines across the `taui/cli/` package, replacing the current ~850 line monolith.
