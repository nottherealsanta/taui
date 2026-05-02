---
name: rich
description: 'Build beautiful terminal output with the Rich Python library. Use when: formatting CLI output, rendering tables, progress bars, trees, panels, syntax highlighting, tracebacks, markdown, live displays, logging, styled text, console markup, custom renderables.'
---

# Rich — Terminal Formatting Library

Render rich text, tables, progress bars, tracebacks, and more in the terminal using the `rich` Python library (v15+).

Docs: https://rich.readthedocs.io/en/latest/
Source: https://github.com/Textualize/rich

## When to Use

- Adding color, bold, italic, or other styles to terminal output
- Rendering tables, trees, panels, or columns
- Displaying progress bars for long-running tasks
- Pretty printing data structures and JSON
- Showing beautiful tracebacks with local variables
- Syntax highlighting source code in the terminal
- Rendering markdown in the terminal
- Building live-updating terminal displays
- Integrating Rich logging with Python's `logging` module
- Creating custom renderables via the Console Protocol

## Installation

```bash
pip install rich
```

Verify: `python -m rich`

## Quick Start

```python
from rich import print
print("[bold magenta]Hello[/] World :sparkles:")
```

For full control, use `Console`:

```python
from rich.console import Console
console = Console()
console.print("Hello", style="bold red")
```

## Procedure

### 1. Determine the Use Case

| Need | Class / Function | Docs |
|------|-----------------|------|
| Styled terminal output | `Console.print()` with markup | https://rich.readthedocs.io/en/latest/console.html |
| Tables | `Table` | https://rich.readthedocs.io/en/latest/tables.html |
| Progress bars | `track()` or `Progress` | https://rich.readthedocs.io/en/latest/progress.html |
| Tree views | `Tree` | https://rich.readthedocs.io/en/latest/tree.html |
| Panels / borders | `Panel` | https://rich.readthedocs.io/en/latest/panel.html |
| Syntax highlighting | `Syntax` | https://rich.readthedocs.io/en/latest/syntax.html |
| Live updating display | `Live` | https://rich.readthedocs.io/en/latest/live.html |
| Pretty tracebacks | `console.print_exception()` / `rich.traceback.install()` | https://rich.readthedocs.io/en/latest/traceback.html |
| Logging handler | `RichHandler` | https://rich.readthedocs.io/en/latest/logging.html |
| Markdown rendering | `Markdown` | https://rich.readthedocs.io/en/latest/markdown.html |
| Pretty print objects | `rich.pretty.install()` or `console.print()` | https://rich.readthedocs.io/en/latest/pretty.html |
| Inspect any object | `rich.inspect()` | https://rich.readthedocs.io/en/latest/reference/init.html |
| Spinner / status | `console.status()` | https://rich.readthedocs.io/en/latest/console.html#status |
| Horizontal rule | `console.rule()` | https://rich.readthedocs.io/en/latest/console.html#rules |
| JSON formatting | `console.print_json()` | https://rich.readthedocs.io/en/latest/console.html#printing-json |
| Layout / split panes | `Layout` | https://rich.readthedocs.io/en/latest/layout.html |
| Custom renderable | Console Protocol (`__rich__` or `__rich_console__`) | https://rich.readthedocs.io/en/latest/protocol.html |

### 2. Console — Central Object

Create one `Console` per project (typically in a shared module):

```python
# myproject/console.py
from rich.console import Console
console = Console()
```

Key `Console` constructor options:
- `stderr=True` — write to stderr (for error consoles)
- `record=True` — enable export to text/HTML/SVG
- `width=N` — override terminal width
- `force_terminal=True` — emit ANSI even when piped
- `theme=Theme({...})` — custom named styles
- `color_system="truecolor"` / `"256"` / `"standard"` / `None`

Key `console.print()` options:
- `style="bold red on white"` — set output style
- `justify="center"` — left / center / right / full
- `markup=False` — disable `[tag]` interpretation
- `highlight=False` — disable automatic highlighting
- `overflow="ellipsis"` — fold / crop / ellipsis / ignore
- `soft_wrap=True` — disable word wrapping

### 3. Styles & Markup

Docs: https://rich.readthedocs.io/en/latest/style.html / https://rich.readthedocs.io/en/latest/markup.html

**Inline markup** (bbcode-like):
```python
console.print("[bold cyan]Name:[/] [green]Alice[/]")
console.print("[link=https://example.com]Click here[/link]")
```

**Style definitions** — space-separated words:
```
bold italic red on white underline
color(5)
#af00ff
rgb(175,0,255)
not bold
link https://example.com
```

Available attributes: `bold` (`b`), `dim`, `italic` (`i`), `underline` (`u`), `strike` (`s`), `reverse` (`r`), `blink`, `overline` (`o`), `conceal`

**Style objects**:
```python
from rich.style import Style
danger = Style(color="red", bold=True, blink=True)
console.print("ALERT", style=danger)
```

**Themes** — named style sets:
```python
from rich.console import Console
from rich.theme import Theme
console = Console(theme=Theme({
    "info": "dim cyan",
    "warning": "magenta",
    "danger": "bold red",
}))
console.print("Watch out!", style="danger")
console.print("[warning]Careful[/warning]")
```

**Escaping user input** (prevents markup injection):
```python
from rich.markup import escape
console.print(f"User said: {escape(user_input)}")
```

### 4. Tables

Docs: https://rich.readthedocs.io/en/latest/tables.html

```python
from rich.table import Table

table = Table(title="Users")
table.add_column("ID", justify="right", style="cyan", no_wrap=True)
table.add_column("Name", style="magenta")
table.add_column("Role", justify="center", style="green")

table.add_row("1", "Alice", "Admin")
table.add_row("2", "Bob", "User")

console.print(table)
```

Key options:
- `box=rich.box.MINIMAL` — border style (see `python -m rich.box`)
- `box=None` — no borders
- `expand=True` — stretch to terminal width
- `show_lines=True` — lines between every row
- `row_styles=["dim", ""]` — alternating row styles (zebra)
- `Table.grid(expand=True)` — borderless grid for layout

Column options: `justify`, `width`, `min_width`, `max_width`, `ratio`, `no_wrap`, `style`, `vertical`

### 5. Progress Bars

Docs: https://rich.readthedocs.io/en/latest/progress.html

**Simple** — `track()`:
```python
from rich.progress import track

for item in track(range(100), description="Processing..."):
    do_work(item)
```

**Advanced** — `Progress` context manager with multiple tasks:
```python
from rich.progress import Progress

with Progress() as progress:
    task1 = progress.add_task("[red]Downloading...", total=1000)
    task2 = progress.add_task("[green]Processing...", total=500)
    while not progress.finished:
        progress.update(task1, advance=0.5)
        progress.update(task2, advance=0.3)
```

**Custom columns**:
```python
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

progress = Progress(
    SpinnerColumn(),
    *Progress.get_default_columns(),
    TimeElapsedColumn(),
)
```

Available columns: `BarColumn`, `TextColumn`, `TimeElapsedColumn`, `TimeRemainingColumn`, `SpinnerColumn`, `MofNCompleteColumn`, `FileSizeColumn`, `DownloadColumn`, `TransferSpeedColumn`

Options: `transient=True` (disappear on finish), `expand=True`, `auto_refresh=False`, `refresh_per_second=N`

Indeterminate: `progress.add_task("Waiting...", total=None)`

### 6. Panels, Trees & Columns

**Panel** — border around content (https://rich.readthedocs.io/en/latest/panel.html):
```python
from rich.panel import Panel
console.print(Panel("Hello!", title="Greeting", subtitle="v1.0"))
console.print(Panel.fit("Compact panel", border_style="green"))
```

**Tree** — hierarchical view (https://rich.readthedocs.io/en/latest/tree.html):
```python
from rich.tree import Tree

tree = Tree("Root")
branch = tree.add("Branch A")
branch.add("[red]Leaf 1")
branch.add("[green]Leaf 2")
tree.add("Branch B")

console.print(tree)
```

**Columns** — flowing columns (https://rich.readthedocs.io/en/latest/columns.html):
```python
from rich.columns import Columns
console.print(Columns(["Item 1", "Item 2", "Item 3"], equal=True))
```

### 7. Live Display

Docs: https://rich.readthedocs.io/en/latest/live.html

Update terminal content in-place (progress, dashboards):

```python
from rich.live import Live
from rich.table import Table

table = Table()
table.add_column("Row")

with Live(table, refresh_per_second=4) as live:
    for i in range(20):
        table.add_row(f"Row {i}")
        time.sleep(0.2)
```

To replace the whole renderable:
```python
with Live(generate_display(), refresh_per_second=4) as live:
    for _ in range(100):
        live.update(generate_display())
```

Options: `transient=True`, `screen=True` (alternate screen), `auto_refresh=False`, `vertical_overflow="crop"`

Print above the live display: `live.console.print("status message")`

### 8. Tracebacks & Logging

**Install globally** (all uncaught exceptions get rich tracebacks):
```python
from rich.traceback import install
install(show_locals=True)
```

**Catch and print** a specific exception:
```python
try:
    risky_operation()
except Exception:
    console.print_exception(show_locals=True)
```

Suppress framework frames: `install(suppress=[click, django])`

**Logging handler**:
```python
import logging
from rich.logging import RichHandler

logging.basicConfig(
    level="INFO",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)],
)
log = logging.getLogger("myapp")
log.info("Server started")
```

Enable markup in logs: `RichHandler(markup=True)` or per-message `extra={"markup": True}`

### 9. Other Renderables

**Syntax highlighting**:
```python
from rich.syntax import Syntax
syntax = Syntax.from_path("main.py", theme="monokai", line_numbers=True)
console.print(syntax)
```

**Markdown**:
```python
from rich.markdown import Markdown
console.print(Markdown("# Title\n\n- item 1\n- item 2"))
```

**Status spinner**:
```python
with console.status("Working..."):
    do_work()
# Custom spinner:
with console.status("Loading...", spinner="dots"):
    do_work()
```

**Rule** (horizontal divider):
```python
console.rule("[bold red]Section Title")
```

**JSON**:
```python
console.print_json('{"key": "value"}')
```

**Padding, Align**:
```python
from rich.padding import Padding
from rich.align import Align
console.print(Padding("Hello", (1, 4)))       # top/bottom=1, left/right=4
console.print(Align.center("Centered text"))
```

### 10. Console Protocol — Custom Renderables

Docs: https://rich.readthedocs.io/en/latest/protocol.html

**Simple** — return a Rich object from `__rich__()`:
```python
class MyObj:
    def __rich__(self) -> str:
        return "[bold cyan]MyObj()[/]"
```

**Full control** — yield renderables from `__rich_console__()`:
```python
from rich.console import Console, ConsoleOptions, RenderResult
from rich.table import Table

class Report:
    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield "[b]Report[/b]"
        table = Table("Key", "Value")
        table.add_row("status", "ok")
        yield table
```

**Measurement** — tell Rich how wide your renderable is:
```python
from rich.measure import Measurement

class MyWidget:
    def __rich_measure__(self, console, options):
        return Measurement(8, options.max_width)
```

### 11. Exporting & Capturing

```python
# Record output for export
console = Console(record=True)
console.print("Hello")
html = console.export_html()
svg = console.export_svg(title="Output")
text = console.export_text()

# Save directly
console.save_html("output.html")
console.save_svg("output.svg")

# Capture output as string
with console.capture() as capture:
    console.print("[bold]Hello[/]")
result = capture.get()
```

## Key Imports Cheat Sheet

```python
# Core
from rich.console import Console
from rich import print, inspect

# Renderables
from rich.table import Table, Column
from rich.panel import Panel
from rich.tree import Tree
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.columns import Columns
from rich.json import JSON
from rich.text import Text
from rich.rule import Rule
from rich.align import Align
from rich.padding import Padding

# Progress & Live
from rich.progress import Progress, track, SpinnerColumn, BarColumn, TextColumn
from rich.progress import TimeElapsedColumn, TimeRemainingColumn, MofNCompleteColumn
from rich.live import Live

# Styling
from rich.style import Style
from rich.theme import Theme
from rich.markup import escape
from rich import box  # box.MINIMAL, box.ROUNDED, box.SIMPLE, etc.

# Logging & Tracebacks
from rich.logging import RichHandler
from rich.traceback import install as install_rich_traceback

# Pretty printing
from rich.pretty import install as install_rich_repr, Pretty

# Layout
from rich.layout import Layout

# Console Protocol
from rich.console import ConsoleOptions, RenderResult
from rich.measure import Measurement
from rich.segment import Segment
```

## Common Patterns

**Shared console module** — create once, import everywhere:
```python
# myproject/_console.py
from rich.console import Console
console = Console()
error_console = Console(stderr=True, style="bold red")
```

**Conditional styling** — adapt to terminal:
```python
console = Console()
if console.is_terminal:
    console.print("[bold]Interactive mode[/]")
else:
    console.print("Piped mode", highlight=False)
```

**Testing** — capture output without a real terminal:
```python
from io import StringIO
from rich.console import Console

console = Console(file=StringIO(), force_terminal=True)
console.print("[bold]test[/]")
output = console.file.getvalue()
```

**Environment variables**:
- `NO_COLOR` — disables all color output
- `FORCE_COLOR` — forces color even without a terminal
- `COLUMNS` / `LINES` — override terminal dimensions
- `TERM=dumb` — disables color and cursor movement

## Pitfalls

- **Markup injection**: Always use `rich.markup.escape()` when printing user-supplied strings
- **Nested markup mismatch**: `[bold]Hello[/red]` raises `MarkupError` — close tags must match
- **Color system**: Setting `color_system="truecolor"` on a terminal that doesn't support it produces garbled output — prefer `"auto"` (default)
- **Live + print**: Use `live.console.print()` not the built-in `print()` to avoid breaking live displays (Rich redirects stdout, but explicit use is safer)
- **Progress in Jupyter**: Auto-refresh is disabled in notebooks — use `track()` or call `progress.refresh()` / `update(..., refresh=True)` manually
