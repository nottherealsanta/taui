---
name: prompt-toolkit
description: 'Build interactive Python terminal UIs with python-prompt-toolkit. Use when: creating CLI prompts, autocompletion, syntax highlighting, input validation, dialogs, progress bars, full screen TUI apps, key bindings, formatted text output, colored prompts.'
---

# Python Prompt Toolkit

Build interactive terminal applications and rich CLI prompts using the `prompt_toolkit` library.

## When to Use

- Adding interactive prompts with autocompletion, history, and validation
- Building full screen terminal applications (TUI)
- Displaying colored/formatted text in the terminal
- Creating dialog boxes (message, input, yes/no, radio, checkbox)
- Showing progress bars for long-running tasks
- Adding custom key bindings to terminal input
- Implementing syntax highlighting in user input

## Installation

```bash
pip install prompt_toolkit
```

## Quick Start

```python
from prompt_toolkit import prompt

text = prompt("Give me some input: ")
print(f"You said: {text}")
```

For persistent sessions with history:

```python
from prompt_toolkit import PromptSession

session = PromptSession()
while True:
    text = session.prompt("> ")
    print(f"You said: {text}")
```

## Procedure

### 1. Determine the Use Case

| Need | Approach | Reference |
|------|----------|-----------|
| Simple input with features | `prompt()` or `PromptSession` | [prompts-input.md](./references/prompts-input.md) |
| Colored/styled terminal output | `print_formatted_text()` with `HTML`/`ANSI` | [formatted-text.md](./references/formatted-text.md) |
| Dialog windows | `message_dialog()`, `input_dialog()`, etc. | [dialogs.md](./references/dialogs.md) |
| Progress indicators | `ProgressBar` context manager | [progress-bars.md](./references/progress-bars.md) |
| Full screen TUI app | `Application` with layout + key bindings | [full-screen-apps.md](./references/full-screen-apps.md) |
| Custom colors/themes | `Style.from_dict()` or Pygments styles | [styling.md](./references/styling.md) |

### 2. Add Features Incrementally

For prompts, layer features onto the basic `prompt()` call:

1. **Autocompletion** — pass a `completer` (`WordCompleter`, `NestedCompleter`, `FuzzyCompleter`, or custom `Completer`)
2. **Syntax highlighting** — pass a `lexer` (wrap Pygments lexers with `PygmentsLexer`)
3. **Input validation** — pass a `validator` (`Validator` subclass or `Validator.from_callable()`)
4. **History** — use `PromptSession` with `FileHistory` for disk persistence
5. **Auto suggestions** — pass `auto_suggest=AutoSuggestFromHistory()`
6. **Key bindings** — create `KeyBindings()` and pass via `key_bindings`
7. **Bottom toolbar / right prompt** — pass `bottom_toolbar` or `rprompt` (text, formatted text, or callable)
8. **Vi mode** — pass `vi_mode=True`

### 3. For Full Screen Apps

1. Define the layout using containers (`HSplit`, `VSplit`, `FloatContainer`) and controls (`BufferControl`, `FormattedTextControl`)
2. Wrap content in `Window` objects
3. Create global `KeyBindings` (at minimum, add `c-q` to exit)
4. Build an `Application(layout=..., key_bindings=..., full_screen=True)`
5. Call `app.run()`

### 4. For Async Applications

Use `prompt_async()` instead of `prompt()` and wrap output with `patch_stdout()`:

```python
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout

async def main():
    session = PromptSession()
    with patch_stdout():
        result = await session.prompt_async("Say something: ")
```

## Key Imports Cheat Sheet

```python
# Core
from prompt_toolkit import prompt, PromptSession, print_formatted_text, HTML, ANSI

# Completion
from prompt_toolkit.completion import WordCompleter, NestedCompleter, FuzzyCompleter, Completer, Completion

# Validation
from prompt_toolkit.validation import Validator, ValidationError

# History
from prompt_toolkit.history import FileHistory, InMemoryHistory

# Auto suggestion
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

# Styling
from prompt_toolkit.styles import Style, merge_styles, style_from_pygments_cls
from prompt_toolkit.lexers import PygmentsLexer

# Key bindings
from prompt_toolkit.key_binding import KeyBindings

# Formatted text
from prompt_toolkit.formatted_text import HTML, ANSI, FormattedText

# Dialogs
from prompt_toolkit.shortcuts import message_dialog, input_dialog, yes_no_dialog, button_dialog, radiolist_dialog, checkboxlist_dialog

# Progress bars
from prompt_toolkit.shortcuts import ProgressBar

# Full screen apps
from prompt_toolkit import Application
from prompt_toolkit.layout.containers import HSplit, VSplit, Window, FloatContainer
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.widgets import TextArea, Button, Frame
```

## References

- [Prompts & Input](./references/prompts-input.md) — autocompletion, validation, history, key bindings, multiline, passwords
- [Formatted Text](./references/formatted-text.md) — HTML, ANSI, style tuples, Pygments tokens
- [Dialogs](./references/dialogs.md) — message box, input box, yes/no, button, radio list, checkbox
- [Progress Bars](./references/progress-bars.md) — simple, parallel, custom formatters, key bindings
- [Full Screen Apps](./references/full-screen-apps.md) — layout, containers, controls, key bindings, focus
- [Styling](./references/styling.md) — Style.from_dict, Pygments styles, colored prompts, color depth
