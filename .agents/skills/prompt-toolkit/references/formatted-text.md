# Formatted Text

`prompt_toolkit` provides `print_formatted_text()` as a drop-in replacement for `print()` with color and formatting support. This works cross-platform (VT100 on Linux/macOS, Win32 API or VT100 on Windows).

Formatted text can be used everywhere: `print_formatted_text()`, prompt messages, toolbars, dialogs, and full screen app controls.

## Printing Plain Text

```python
from prompt_toolkit import print_formatted_text

print_formatted_text("Hello world")
```

Replace the built-in `print`:

```python
from prompt_toolkit import print_formatted_text as print

print("Hello world")
```

## Four Ways to Create Formatted Text

### 1. HTML

Supports `<b>`, `<i>`, `<u>` for bold, italic, underline. Custom tags map to style class names.

```python
from prompt_toolkit import print_formatted_text, HTML

print_formatted_text(HTML('<b>This is bold</b>'))
print_formatted_text(HTML('<i>This is italic</i>'))
print_formatted_text(HTML('<u>This is underlined</u>'))

# ANSI palette colors
print_formatted_text(HTML('<ansired>This is red</ansired>'))
print_formatted_text(HTML('<ansigreen>This is green</ansigreen>'))

# Named colors (256 or true color)
print_formatted_text(HTML('<skyblue>This is sky blue</skyblue>'))
print_formatted_text(HTML('<violet>This is violet</violet>'))

# Foreground and background via attributes
print_formatted_text(HTML('<aaa fg="ansiwhite" bg="ansigreen">White on green</aaa>'))
```

Custom tags with a style sheet:

```python
from prompt_toolkit import print_formatted_text, HTML
from prompt_toolkit.styles import Style

style = Style.from_dict({
    'aaa': '#ff0066',
    'bbb': '#44ff00 italic',
})

print_formatted_text(HTML('<aaa>Hello</aaa> <bbb>world</bbb>!'), style=style)
```

### 2. ANSI Escape Sequences

Parse VT100 ANSI escape sequences. Works cross-platform — prompt_toolkit maps them internally.

```python
from prompt_toolkit import print_formatted_text, ANSI

print_formatted_text(ANSI('\x1b[31mhello \x1b[32mworld'))
```

### 3. (style, text) Tuples

The most powerful and verbose method. Uses `FormattedText`.

```python
from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import FormattedText

text = FormattedText([
    ('#ff0066', 'Hello'),
    ('', ' '),
    ('#44ff00 italic', 'World'),
])

print_formatted_text(text)
```

With class names and a style sheet:

```python
from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.styles import Style

text = FormattedText([
    ('class:aaa', 'Hello'),
    ('', ' '),
    ('class:bbb', 'World'),
])

style = Style.from_dict({
    'aaa': '#ff0066',
    'bbb': '#44ff00 italic',
})

print_formatted_text(text, style=style)
```

### 4. Pygments (Token, text) Tuples

Wrap Pygments token lists in `PygmentsTokens`:

```python
from pygments.token import Token
from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import PygmentsTokens

text = [
    (Token.Keyword, 'print'),
    (Token.Punctuation, '('),
    (Token.Literal.String.Double, '"hello"'),
    (Token.Punctuation, ')'),
]

print_formatted_text(PygmentsTokens(text))
```

Print output of a Pygments lexer directly:

```python
import pygments
from pygments.lexers.python import PythonLexer
from prompt_toolkit.formatted_text import PygmentsTokens
from prompt_toolkit import print_formatted_text

tokens = list(pygments.lex('print("Hello")', lexer=PythonLexer()))
print_formatted_text(PygmentsTokens(tokens))
```

## Pygments Token → Class Name Mapping

| Pygments Token | prompt_toolkit Class |
|---|---|
| `Token.Keyword` | `class:pygments.keyword` |
| `Token.Punctuation` | `class:pygments.punctuation` |
| `Token.Literal.String.Double` | `class:pygments.literal.string.double` |
| `Token.Text` | `class:pygments.text` |
| `Token` | `class:pygments` |

A class like `pygments.literal.string.double` decomposes into four: `pygments`, `pygments.literal`, `pygments.literal.string`, `pygments.literal.string.double`. The final style is computed by combining all four.

## to_formatted_text()

Convert any formatted text type with an optional additional style:

```python
from prompt_toolkit.formatted_text import to_formatted_text, HTML
from prompt_toolkit import print_formatted_text

html = HTML('<aaa>Hello</aaa> <bbb>world</bbb>!')
text = to_formatted_text(html, style='class:my_html bg:#00ff00 italic')

print_formatted_text(text)
```
