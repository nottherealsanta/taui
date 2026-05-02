# Full Screen Applications

Build complex terminal UIs with layouts, controls, key bindings, and focus management.

## Minimal Application

```python
from prompt_toolkit import Application

app = Application(full_screen=True)
app.run()
```

Without `full_screen=True`, the app won't use the alternate screen buffer.

An application consists of:
- **I/O objects** — input/output streams (usually auto-detected)
- **Layout** — graphical structure (containers + controls)
- **Style** — colors and formatting
- **Key bindings** — user interaction handlers

## Layout Architecture

Three levels of abstraction (low to high):

### 1. Containers + Controls (Low Level)

**Containers** arrange layout by splitting the screen:

| Container | Purpose |
|-----------|---------|
| `HSplit` | Horizontal split (stack vertically) |
| `VSplit` | Vertical split (side by side) |
| `FloatContainer` | Floating overlays |
| `Window` | Wraps a `UIControl` (leaf node) |
| `ScrollablePane` | Scrollable form/nested layout |
| `ConditionalContainer` | Visible only when condition is met |

**Controls** generate actual content:

| UIControl | Purpose |
|-----------|---------|
| `BufferControl` | Editable/scrollable text buffer |
| `FormattedTextControl` | Static formatted text display |

`Window` is the adaptor between containers and controls. It handles scrolling and line wrapping.

### 2. Widgets (Mid Level)

Reusable components with a `__pt_container__` method:

| Widget | Purpose |
|--------|---------|
| `TextArea` | Multi-line text input |
| `Button` | Clickable button |
| `Frame` | Border with title |
| `VerticalLine` | Vertical separator |

### 3. Shortcuts (High Level)

`prompt()`, `message_dialog()`, etc. — no layout thinking required.

## Example: Split Layout

```python
from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.layout.containers import VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout

buffer1 = Buffer()  # Editable buffer

root_container = VSplit([
    # Editable buffer on the left
    Window(content=BufferControl(buffer=buffer1)),

    # Vertical line separator
    Window(width=1, char="|"),

    # Static text on the right
    Window(content=FormattedTextControl(text="Hello world")),
])

layout = Layout(root_container)

app = Application(layout=layout, full_screen=True)
app.run()
```

Nest `VSplit`, `HSplit`, and `FloatContainer` for complex layouts.

## Key Bindings

### Global Key Bindings

Always active regardless of focus:

```python
from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings

kb = KeyBindings()

@kb.add("c-q")
def exit_(event):
    """Pressing Ctrl-Q will exit the user interface."""
    event.app.exit()

app = Application(key_bindings=kb, full_screen=True)
app.run()
```

### Control-Specific Key Bindings

Both `BufferControl` and `FormattedTextControl` accept a `key_bindings` argument. These are only active when the control has focus.

### Modal Containers

`VSplit`, `HSplit`, and `FloatContainer` accept `modal=True`. A modal container's children do **not** inherit parent key bindings when focused — only global key bindings remain active.

Useful when different regions have conflicting key bindings.

## Focus Management

```python
from prompt_toolkit.application import get_app

# Focus a specific window
w = Window(...)
get_app().layout.focus(w)
```

`focus()` accepts a `Window`, `Buffer`, or `UIControl`.

## Window Options

`Window` provides:

- **Margins** — left/right (scroll bars, line numbers)
- **`cursorline` / `cursorcolumn`** — highlight current line/column
- **Alignment** — left, right, center
- **Background fill** — default character
- **`wrap_lines`** — line wrapping behavior

## BufferControl & Input Processors

A `Processor` post-processes `BufferControl` content before display:

| Processor | Purpose |
|-----------|---------|
| `HighlightSearchProcessor` | Highlight search results |
| `HighlightSelectionProcessor` | Highlight selection |
| `PasswordProcessor` | Display `*` characters |
| `BracketsMismatchProcessor` | Highlight bracket mismatches |
| `BeforeInput` | Insert text before content |
| `AfterInput` | Insert text after content |
| `AppendAutoSuggestion` | Show auto-suggestion text |
| `ShowLeadingWhiteSpaceProcessor` | Visualize leading whitespace |
| `ShowTrailingWhiteSpaceProcessor` | Visualize trailing whitespace |
| `TabsProcessor` | Visualize tabs as spaces/symbols |

Merge multiple processors:

```python
from prompt_toolkit.layout.processors import merge_processors

merged = merge_processors([proc1, proc2, proc3])
control = BufferControl(input_processors=[merged])
```

## Complete Example: Editor-like App

```python
from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout

# Buffers
buffer1 = Buffer()
buffer2 = Buffer()

# Key bindings
kb = KeyBindings()

@kb.add("c-q")
def exit_(event):
    event.app.exit()

@kb.add("tab")
def focus_next(event):
    event.app.layout.focus_next()

# Layout
root = HSplit([
    # Top: two editor panes side by side
    VSplit([
        Window(content=BufferControl(buffer=buffer1)),
        Window(width=1, char="|"),
        Window(content=BufferControl(buffer=buffer2)),
    ]),
    # Bottom: status bar
    Window(height=1, content=FormattedTextControl("Press Ctrl-Q to exit | Tab to switch focus")),
])

app = Application(
    layout=Layout(root),
    key_bindings=kb,
    full_screen=True,
)

app.run()
```
