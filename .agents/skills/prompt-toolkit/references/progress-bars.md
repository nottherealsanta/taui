# Progress Bars

High-level API for displaying progress bars, inspired by tqdm.

## Simple Progress Bar

Wrap any iterable with the `ProgressBar` context manager:

```python
from prompt_toolkit.shortcuts import ProgressBar
import time

with ProgressBar() as pb:
    for i in pb(range(800)):
        time.sleep(.01)
```

For iterables without a known length (generators), pass `total`:

```python
def some_iterable():
    yield ...

with ProgressBar() as pb:
    for i in pb(some_iterable(), total=1000):
        time.sleep(.01)
```

## Multiple Parallel Tasks

Each task runs in a separate thread; the progress bar UI runs in its own thread:

```python
from prompt_toolkit.shortcuts import ProgressBar
import time
import threading

with ProgressBar() as pb:
    def task_1():
        for i in pb(range(100)):
            time.sleep(.05)

    def task_2():
        for i in pb(range(150)):
            time.sleep(.08)

    t1 = threading.Thread(target=task_1)
    t2 = threading.Thread(target=task_2)
    t1.daemon = True
    t2.daemon = True
    t1.start()
    t2.start()

    # Wait with timeout so Ctrl-C works on Windows
    for t in [t1, t2]:
        while t.is_alive():
            t.join(timeout=.5)
```

Set `daemon=True` so Ctrl-C exits without waiting for background threads.

## Title and Label

Both accept formatted text:

```python
from prompt_toolkit.shortcuts import ProgressBar
from prompt_toolkit.formatted_text import HTML
import time

title = HTML('Downloading <style bg="yellow" fg="black">4 files...</style>')
label = HTML('<ansired>some file</ansired>: ')

with ProgressBar(title=title) as pb:
    for i in pb(range(800), label=label):
        time.sleep(.01)
```

## Custom Formatting

The display is composed of a sequence of `Formatter` objects:

```python
from prompt_toolkit.shortcuts.progress_bar.formatters import *

# Default formatting
default_formatting = [
    Label(),
    Text(' '),
    Percentage(),
    Text(' '),
    Bar(),
    Text(' '),
    Progress(),
    Text(' '),
    Text('eta [', style='class:time-left'),
    TimeLeft(),
    Text(']', style='class:time-left'),
    Text(' '),
]
```

### apt-get Style Example

```python
from prompt_toolkit.shortcuts import ProgressBar
from prompt_toolkit.styles import Style
from prompt_toolkit.shortcuts.progress_bar import formatters
import time

style = Style.from_dict({
    'label': 'bg:#ffff00 #000000',
    'percentage': 'bg:#ffff00 #000000',
    'current': '#448844',
    'bar': '',
})

custom_formatters = [
    formatters.Label(),
    formatters.Text(': [', style='class:percentage'),
    formatters.Percentage(),
    formatters.Text(']', style='class:percentage'),
    formatters.Text(' '),
    formatters.Bar(sym_a='#', sym_b='#', sym_c='.'),
    formatters.Text('  '),
]

with ProgressBar(style=style, formatters=custom_formatters) as pb:
    for i in pb(range(1600), label='Installing'):
        time.sleep(.01)
```

## Key Bindings and Toolbar

Add custom key bindings and a bottom toolbar:

```python
from prompt_toolkit import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.shortcuts import ProgressBar
import os
import time
import signal

bottom_toolbar = HTML(' <b>[f]</b> Print "f" <b>[x]</b> Abort.')

kb = KeyBindings()
cancel = [False]

@kb.add('f')
def _(event):
    print('You pressed `f`.')

@kb.add('x')
def _(event):
    cancel[0] = True
    os.kill(os.getpid(), signal.SIGINT)

with patch_stdout():
    with ProgressBar(key_bindings=kb, bottom_toolbar=bottom_toolbar) as pb:
        for i in pb(range(800)):
            time.sleep(.01)
            if cancel[0]:
                break
```

Use `patch_stdout()` to ensure print output appears above the progress bar.
