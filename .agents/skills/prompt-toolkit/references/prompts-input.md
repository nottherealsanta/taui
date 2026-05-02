# Prompts & Input

Comprehensive reference for `prompt()` and `PromptSession` — the core of interactive CLI input.

## Hello World

```python
from prompt_toolkit import prompt

text = prompt("Give me some input: ")
print(f"You said: {text}")
```

This gives a simple prompt with Emacs key bindings (like readline).

## PromptSession

Use `PromptSession` for repeated input calls that share history and configuration:

```python
from prompt_toolkit import PromptSession

session = PromptSession()

while True:
    text = session.prompt("> ")
    print(f"You said: {text}")
```

**Advantages:**
- Input history is kept between calls
- Configuration (completion, highlighting, etc.) can be set once on the session and overridden per-call

## Syntax Highlighting

Wrap any Pygments lexer in `PygmentsLexer`:

```python
from pygments.lexers.html import HtmlLexer
from prompt_toolkit.shortcuts import prompt
from prompt_toolkit.lexers import PygmentsLexer

text = prompt("Enter HTML: ", lexer=PygmentsLexer(HtmlLexer))
```

With a custom Pygments style:

```python
from pygments.styles import get_style_by_name
from prompt_toolkit.styles.pygments import style_from_pygments_cls

style = style_from_pygments_cls(get_style_by_name("monokai"))
text = prompt(
    "Enter HTML: ",
    lexer=PygmentsLexer(HtmlLexer),
    style=style,
    include_default_pygments_style=False,
)
```

## Autocompletion

### WordCompleter

```python
from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter

html_completer = WordCompleter(["<html>", "<body>", "<head>", "<title>"])
text = prompt("Enter HTML: ", completer=html_completer)
```

### NestedCompleter

For hierarchical command completion (like router CLIs):

```python
from prompt_toolkit import prompt
from prompt_toolkit.completion import NestedCompleter

completer = NestedCompleter.from_nested_dict({
    "show": {
        "version": None,
        "clock": None,
        "ip": {
            "interface": {"brief"}
        }
    },
    "exit": None,
})

text = prompt("# ", completer=completer)
```

`None` = no further nesting. A set can replace a dict where all values are `None`.

### Custom Completer

```python
from prompt_toolkit import prompt
from prompt_toolkit.completion import Completer, Completion

class MyCustomCompleter(Completer):
    def get_completions(self, document, complete_event):
        yield Completion("completion", start_position=0)

text = prompt("> ", completer=MyCustomCompleter())
```

- `get_completions()` takes a `Document` and yields `Completion` instances
- `start_position` — negative values delete and replace characters before cursor (useful for case-insensitive or fuzzy)

### Styled Completions

```python
from prompt_toolkit.completion import Completer, Completion

class MyCustomCompleter(Completer):
    def get_completions(self, document, complete_event):
        yield Completion("completion1", start_position=0, style="bg:ansiyellow fg:ansiblack")
        yield Completion("completion2", start_position=0, style="underline")
        yield Completion("completion3", start_position=0, style="class:special-completion")
```

Use `display=HTML(...)` for full formatted text in the display:

```python
from prompt_toolkit.formatted_text import HTML

yield Completion(
    "completion1",
    start_position=0,
    display=HTML("<b>completion</b><ansired>1</ansired>"),
    style="bg:ansiyellow",
)
```

### FuzzyCompleter

Wraps any completer to enable fuzzy matching (e.g., "djm" matches "django_migrations"):

```python
from prompt_toolkit.completion import FuzzyCompleter, FuzzyWordCompleter

# Wrap an existing completer
fuzzy = FuzzyCompleter(my_completer)

# Or use the word variant directly
fuzzy = FuzzyWordCompleter(["django_migrations", "django_models", "flask_app"])
```

### Complete While Typing

```python
text = prompt("Enter HTML: ", completer=my_completer, complete_while_typing=True)
```

**Note:** Incompatible with `enable_history_search` (up/down key conflicts).

### Asynchronous Completion

For heavy completers, run in a background thread:

```python
from prompt_toolkit.completion import ThreadedCompleter

text = prompt("> ", completer=ThreadedCompleter(MyCustomCompleter()))
# Or:
text = prompt("> ", completer=MyCustomCompleter(), complete_in_thread=True)
```

## Input Validation

### Validator Class

```python
from prompt_toolkit.validation import Validator, ValidationError
from prompt_toolkit import prompt

class NumberValidator(Validator):
    def validate(self, document):
        text = document.text
        if text and not text.isdigit():
            i = 0
            for i, c in enumerate(text):
                if not c.isdigit():
                    break
            raise ValidationError(
                message="This input contains non-numeric characters",
                cursor_position=i,
            )

number = int(prompt("Give a number: ", validator=NumberValidator()))
```

### Validator from Callable

Simpler — covers 90% of cases:

```python
from prompt_toolkit.validation import Validator
from prompt_toolkit import prompt

validator = Validator.from_callable(
    lambda text: text.isdigit(),
    error_message="This input contains non-numeric characters",
    move_cursor_to_end=True,
)

number = int(prompt("Give a number: ", validator=validator))
```

### Validation Timing

```python
# Validate in real-time (default)
prompt("Give a number: ", validator=my_validator)

# Validate only on Enter
prompt("Give a number: ", validator=my_validator, validate_while_typing=False)
```

For CPU-intensive validators, wrap in `ThreadedValidator`.

## History

### In-Memory (default with PromptSession)

```python
from prompt_toolkit import PromptSession

session = PromptSession()  # InMemoryHistory by default
while True:
    session.prompt("> ")
```

### File-Based Persistence

```python
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

session = PromptSession(history=FileHistory("~/.myhistory"))
while True:
    session.prompt("> ")
```

## Auto Suggestion

Fish shell-style suggestions from history (shown as gray text, accept with → or Ctrl-E):

```python
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

session = PromptSession()
while True:
    text = session.prompt("> ", auto_suggest=AutoSuggestFromHistory())
    print(f"You said: {text}")
```

**Tip:** Share one `History` object between calls (using `PromptSession` handles this).

Custom suggestions: implement the `AutoSuggest` abstract base class.

## Bottom Toolbar

Accepts plain text, formatted text, or a callable (called on every render for dynamic content):

```python
from prompt_toolkit import prompt
from prompt_toolkit.formatted_text import HTML

def bottom_toolbar():
    return HTML("This is a <b><style bg='ansired'>Toolbar</style></b>!")

text = prompt("> ", bottom_toolbar=bottom_toolbar)
```

With style tuples:

```python
from prompt_toolkit import prompt
from prompt_toolkit.styles import Style

def bottom_toolbar():
    return [("class:bottom-toolbar", " This is a toolbar. ")]

style = Style.from_dict({
    "bottom-toolbar": "#ffffff bg:#333333",
})

text = prompt("> ", bottom_toolbar=bottom_toolbar, style=style)
```

Default class name: `bottom-toolbar`.

## Right Prompt (rprompt)

Like ZSH's RPROMPT:

```python
from prompt_toolkit import prompt
from prompt_toolkit.styles import Style

example_style = Style.from_dict({
    "rprompt": "bg:#ff0066 #ffffff",
})

def get_rprompt():
    return "<rprompt>"

answer = prompt("> ", rprompt=get_rprompt, style=example_style)
```

## Coloring the Prompt Itself

Use formatted text (style/text tuples) as the prompt message:

```python
from prompt_toolkit.shortcuts import prompt
from prompt_toolkit.styles import Style

style = Style.from_dict({
    "": "#ff0066",            # User input (default text)
    "username": "#884444",
    "at": "#00aa00",
    "host": "#00ffff bg:#444400",
    "path": "ansicyan underline",
    "pound": "#00aa00",
})

message = [
    ("class:username", "john"),
    ("class:at", "@"),
    ("class:host", "localhost"),
    ("class:path", ":/user/john"),
    ("class:pound", "# "),
]

text = prompt(message, style=style)
```

For true 24-bit color:

```python
from prompt_toolkit.output import ColorDepth

text = prompt(message, style=style, color_depth=ColorDepth.TRUE_COLOR)
```

## Vi Input Mode

```python
from prompt_toolkit import prompt

prompt("> ", vi_mode=True)
```

## Custom Key Bindings

```python
from prompt_toolkit import prompt
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.key_binding import KeyBindings

bindings = KeyBindings()

@bindings.add("c-t")
def _(event):
    def print_hello():
        print("hello world")
    run_in_terminal(print_hello)

@bindings.add("c-x")
def _(event):
    event.app.exit()

text = prompt("> ", key_bindings=bindings)
```

Use `run_in_terminal()` for key bindings that print output (prevents mixing with prompt display).

### Conditional Key Bindings

```python
from prompt_toolkit.filters import Condition

@Condition
def is_active():
    return datetime.datetime.now().second > 30

@bindings.add("c-t", filter=is_active)
def _(event):
    pass
```

### Toggle Vi/Emacs Mode

```python
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.application.current import get_app

@bindings.add("f4")
def _(event):
    app = event.app
    if app.editing_mode == EditingMode.VI:
        app.editing_mode = EditingMode.EMACS
    else:
        app.editing_mode = EditingMode.VI
```

### Ctrl-Space for Completion

```python
kb = KeyBindings()

@kb.add("c-space")
def _(event):
    buff = event.app.current_buffer
    if buff.complete_state:
        buff.complete_next()
    else:
        buff.start_completion(select_first=False)
```

## Other Options

### Multiline Input

```python
prompt("> ", multiline=True)
```

Enter inserts newline; Meta+Enter (or Esc then Enter) accepts input.

Custom continuation prompt:

```python
def prompt_continuation(width, line_number, is_soft_wrap):
    return "." * width

prompt("multiline input> ", multiline=True, prompt_continuation=prompt_continuation)
```

### Default Value

```python
import getpass
prompt("What is your name: ", default=f"{getpass.getuser()}")
```

### Mouse Support

```python
prompt("What is your name: ", mouse_support=True)
```

### Line Wrapping

```python
prompt("What is your name: ", wrap_lines=False)  # Horizontal scroll instead
```

### Password Input

```python
prompt("Enter password: ", is_password=True)
```

## Cursor Shapes

```python
from prompt_toolkit.cursor_shapes import CursorShape, ModalCursorShapeConfig

prompt(">", cursor=CursorShape.BLOCK)
prompt(">", cursor=CursorShape.BEAM)
prompt(">", cursor=CursorShape.UNDERLINE)
prompt(">", cursor=CursorShape.BLINKING_BLOCK)
prompt(">", cursor=CursorShape.BLINKING_BEAM)
prompt(">", cursor=CursorShape.BLINKING_UNDERLINE)
prompt(">", cursor=ModalCursorShapeConfig())  # Changes with Vi mode
```

## Async Prompts

For asyncio applications — never block the event loop:

```python
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout

async def my_coroutine():
    session = PromptSession()
    while True:
        with patch_stdout():
            result = await session.prompt_async("Say something: ")
        print(f"You said: {result}")
```

`patch_stdout()` ensures other coroutine output doesn't destroy the prompt.

## Reading Raw Keys

Read individual key presses without a prompt:

```python
import asyncio
from prompt_toolkit.input import create_input
from prompt_toolkit.keys import Keys

async def main() -> None:
    done = asyncio.Event()
    input = create_input()

    def keys_ready():
        for key_press in input.read_keys():
            print(key_press)
            if key_press.key == Keys.ControlC:
                done.set()

    with input.raw_mode():
        with input.attach(keys_ready):
            await done.wait()

if __name__ == "__main__":
    asyncio.run(main())
```
