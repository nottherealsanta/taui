# Dialogs

High-level API for displaying dialog windows in the terminal (similar to Whiptail, but pure Python).

## Message Box

```python
from prompt_toolkit.shortcuts import message_dialog

message_dialog(
    title="Example dialog window",
    text="Do you want to continue?\nPress ENTER to quit.",
).run()
```

## Input Box

Returns user input as a string:

```python
from prompt_toolkit.shortcuts import input_dialog

text = input_dialog(
    title="Input dialog example",
    text="Please type your name:",
).run()
```

For password input:

```python
text = input_dialog(
    title="Password dialog",
    text="Enter your password:",
    password=True,
).run()
```

## Yes/No Confirmation

Returns a boolean:

```python
from prompt_toolkit.shortcuts import yes_no_dialog

result = yes_no_dialog(
    title="Yes/No dialog example",
    text="Do you want to confirm?",
).run()
```

## Button Dialog

Returns the value associated with the clicked button:

```python
from prompt_toolkit.shortcuts import button_dialog

result = button_dialog(
    title="Button dialog example",
    text="Do you want to confirm?",
    buttons=[
        ("Yes", True),
        ("No", False),
        ("Maybe...", None),
    ],
).run()
```

## Radio List Dialog

Returns the value of the selected radio item:

```python
from prompt_toolkit.shortcuts import radiolist_dialog

result = radiolist_dialog(
    title="RadioList dialog",
    text="Which breakfast would you like?",
    values=[
        ("breakfast1", "Eggs and bacon"),
        ("breakfast2", "French breakfast"),
        ("breakfast3", "Equestrian breakfast"),
    ],
).run()
```

## Checkbox List Dialog

Returns a list of selected values:

```python
from prompt_toolkit.shortcuts import checkboxlist_dialog

results_array = checkboxlist_dialog(
    title="CheckboxList dialog",
    text="What would you like in your breakfast?",
    values=[
        ("eggs", "Eggs"),
        ("bacon", "Bacon"),
        ("croissants", "20 Croissants"),
        ("daily", "The breakfast of the day"),
    ],
).run()
```

## Styling Dialogs

Pass a custom `Style` and use `HTML` for formatted text in title/text:

```python
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import message_dialog
from prompt_toolkit.styles import Style

example_style = Style.from_dict({
    "dialog": "bg:#88ff88",
    "dialog frame.label": "bg:#ffffff #000000",
    "dialog.body": "bg:#000000 #00ff00",
    "dialog shadow": "bg:#00aa00",
})

message_dialog(
    title=HTML('<style bg="blue" fg="white">Styled</style> '
               '<style fg="ansired">dialog</style> window'),
    text="Do you want to continue?\nPress ENTER to quit.",
    style=example_style,
).run()
```

## Styling Reference

### Components Used by Each Shortcut

| Shortcut | Components |
|----------|-----------|
| `yes_no_dialog` | Label, Button (x2) |
| `button_dialog` | Label, Button |
| `input_dialog` | TextArea, Button (x2) |
| `message_dialog` | Label, Button |
| `radiolist_dialog` | Label, RadioList, Button (x2) |
| `checkboxlist_dialog` | Label, CheckboxList, Button (x2) |
| `progress_dialog` | Label, TextArea (locked), ProgressBar |

All shortcuts use the `Dialog` component implicitly.

### Available CSS-like Class Names

| Widget | Class Names |
|--------|------------|
| Dialog | `dialog`, `dialog.body` |
| TextArea | `text-area`, `text-area.prompt` |
| Label | `label` |
| Button | `button`, `button.focused`, `button.arrow`, `button.text` |
| Frame | `frame`, `frame.border`, `frame.label` |
| Shadow | `shadow` |
| RadioList | `radio-list`, `radio`, `radio-checked`, `radio-selected` |
| CheckboxList | `checkbox-list`, `checkbox`, `checkbox-checked`, `checkbox-selected` |
| VerticalLine | `line`, `vertical-line` |
| HorizontalLine | `line`, `horizontal-line` |
| ProgressBar | `progress-bar`, `progress-bar.used` |

### Custom Styled Checkbox Example

```python
from prompt_toolkit.shortcuts import checkboxlist_dialog
from prompt_toolkit.styles import Style

results = checkboxlist_dialog(
    title="CheckboxList dialog",
    text="What would you like in your breakfast?",
    values=[
        ("eggs", "Eggs"),
        ("bacon", "Bacon"),
        ("croissants", "20 Croissants"),
        ("daily", "The breakfast of the day"),
    ],
    style=Style.from_dict({
        "dialog": "bg:#cdbbb3",
        "button": "bg:#bf99a4",
        "checkbox": "#e8612c",
        "dialog.body": "bg:#a9cfd0",
        "dialog shadow": "bg:#c98982",
        "frame.label": "#fcaca3",
        "dialog.body label": "#fd8bb6",
    }),
).run()
```
