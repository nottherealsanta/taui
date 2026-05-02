# Styling

Control colors, fonts, and visual attributes across all prompt_toolkit components.

## Style.from_dict()

The primary way to create styles:

```python
from prompt_toolkit.styles import Style

style = Style.from_dict({
    "pygments.comment": "#888888 bold",
    "pygments.keyword": "#ff88ff bold",
})
```

### Style String Format

Styles are space-separated attributes:

| Attribute | Example | Description |
|-----------|---------|-------------|
| Hex color | `#ff0066` | Foreground color |
| `bg:` prefix | `bg:#00ff00` | Background color |
| `bold` | | Bold text |
| `italic` | | Italic text |
| `underline` | | Underlined text |
| `blink` | | Blinking text |
| `reverse` | | Swap fg/bg |
| `nobold` | | Explicitly disable bold |
| `noitalic` | | Explicitly disable italic |
| `nounderline` | | Explicitly disable underline |
| `noblink` | | Explicitly disable blink |
| `noreverse` | | Explicitly disable reverse |

### ANSI Color Names

Instead of hex, use built-in ANSI names that map to the terminal's 16-color palette:

```
ansiblack, ansired, ansigreen, ansiyellow, ansiblue, ansimagenta, ansicyan, ansiwhite
ansibrightblack, ansibrightred, ansibrightgreen, ansibrightyellow,
ansibrightblue, ansibrightmagenta, ansibrightcyan, ansibrightwhite
```

### Named Colors

256-color palette and true color named colors are also supported:

```
skyblue, seagreen, violet, darkred, olive, etc.
```

## Using Pygments Styles

Wrap any Pygments style class:

```python
from prompt_toolkit.styles import style_from_pygments_cls
from pygments.styles.tango import TangoStyle

tango_style = style_from_pygments_cls(TangoStyle)

text = prompt(
    "Enter HTML: ",
    lexer=PygmentsLexer(HtmlLexer),
    style=tango_style,
)
```

## Merging Styles

Combine a Pygments style with custom overrides:

```python
from prompt_toolkit.styles import Style, style_from_pygments_cls, merge_styles
from pygments.styles.tango import TangoStyle

our_style = merge_styles([
    style_from_pygments_cls(TangoStyle),
    Style.from_dict({
        "pygments.comment": "#888888 bold",
        "pygments.keyword": "#ff88ff bold",
    }),
])
```

## Applying Style to a Prompt

```python
from pygments.lexers.html import HtmlLexer
from prompt_toolkit.shortcuts import prompt
from prompt_toolkit.styles import Style
from prompt_toolkit.lexers import PygmentsLexer

our_style = Style.from_dict({
    "pygments.comment": "#888888 bold",
    "pygments.keyword": "#ff88ff bold",
})

text = prompt(
    "Enter HTML: ",
    lexer=PygmentsLexer(HtmlLexer),
    style=our_style,
)
```

## Coloring the Prompt Text

Use style/text tuples for the prompt message with class-based styling:

```python
from prompt_toolkit.shortcuts import prompt
from prompt_toolkit.styles import Style

style = Style.from_dict({
    "": "#ff0066",              # Default user input color
    "username": "#884444",
    "at": "#00aa00",
    "colon": "#0000aa",
    "pound": "#00aa00",
    "host": "#00ffff bg:#444400",
    "path": "ansicyan underline",
})

message = [
    ("class:username", "john"),
    ("class:at", "@"),
    ("class:host", "localhost"),
    ("class:colon", ":"),
    ("class:path", "/user/john"),
    ("class:pound", "# "),
]

text = prompt(message, style=style)
```

## Color Depth

By default, colors use the 256-color palette. For 24-bit true color:

```python
from prompt_toolkit.output import ColorDepth

text = prompt(message, style=style, color_depth=ColorDepth.TRUE_COLOR)
```

Available depths:
- `ColorDepth.DEPTH_1_BIT` — monochrome
- `ColorDepth.DEPTH_4_BIT` — 16 colors (ANSI)
- `ColorDepth.DEPTH_8_BIT` — 256 colors (default)
- `ColorDepth.TRUE_COLOR` — 24-bit (16M colors)

## Styling Dialogs

See [dialogs.md](./dialogs.md#styling-dialogs) for dialog-specific class names and examples.

## Common Style Classes

| Context | Class Name | Purpose |
|---------|-----------|---------|
| Prompt input | `""` (empty string) | Default user input style |
| Bottom toolbar | `bottom-toolbar` | Toolbar background + text |
| Right prompt | `rprompt` | Right-aligned prompt |
| Completion menu | `completion-menu`, `completion-menu.completion` | Dropdown menu |
| Completion selection | `completion-menu.completion.current` | Selected item |
| Scrollbar | `scrollbar.background`, `scrollbar.button` | Scroll indicators |
| Dialog | `dialog`, `dialog.body` | Dialog window |
| Buttons | `button`, `button.focused` | Dialog buttons |

## Style Differences from Pygments

- `roman`, `sans`, `mono`, `border` options are **ignored**
- Added: `blink`, `noblink`, `reverse`, `noreverse`
- Colors accept `#rrggbb` hex OR built-in ANSI color names
- ANSI color names map directly to the terminal's 16-color palette
