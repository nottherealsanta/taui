# CLI & Commands

The CLI is the terminal frontend. It wires agent callbacks to colored terminal output and handles slash commands.

---

## Entry Points

```
python -m taui             → taui/__main__.py → cli.main()
taui                       → pyproject.toml [project.scripts] → cli:main
```

```python
def main(argv=None):           # Sync wrapper
    asyncio.run(async_main(argv))

async def async_main(argv=None):
    parsed = parse_args(argv)  # argparse
    config = Config.load(**parsed)
    session = await Session.create(config)

    if initial_message:
        # Non-interactive: single message, print, exit
        repl = Repl(session)
        repl._print_banner()
        await repl._send(initial_message)
        await session.close()
    else:
        # Interactive REPL
        repl = Repl(session)
        await repl.run()
```

### CLI Arguments

```
-p, --provider    copilot | codex
-m, --model       Model name (e.g. claude-sonnet-4.6)
-d, --dir         Working directory
message           Optional positional args → non-interactive mode
```

---

## REPL (`taui/cli.py`)

### Initialization

```python
class Repl:
    def __init__(self, session: Session):
        self._session = session
        self._wire_callbacks()       # Connect agent loop → terminal output
        self._commands = self._build_commands()  # Slash command registry
```

### Callback Wiring

```python
def _wire_callbacks(self):
    loop = self._session._loop
    loop._on_tool_call = self._on_tool_call       # Show tool invocation
    loop._on_tool_result = self._on_tool_result   # Show result summary
    loop._on_approval = self._on_approval         # Interactive approval prompt

    # Wire question tool callback
    question_tool = registry.get("question")
    question_tool._ask = self._ask_question
```

### Display Callbacks

| Callback | Display |
|----------|---------|
| `_on_tool_call(call_id, name, args)` | `▸ read(src/main.py)` in cyan |
| `_on_tool_result(call_id, name, content, is_error)` | 3 lines preview or `(N lines)` in dim; errors in red |
| `_on_approval(call_id, name, args) -> bool` | `⚠ bash requires approval` in yellow, `Allow? [y/N]` prompt |
| `_ask_question(question, options) -> str` | `? question` in yellow, numbered options |

### Compact Arg Display

`_format_args(name, arguments)` renders tool args compactly per tool:

```
read     → "src/main.py"
write    → "src/main.py, 42 lines"
edit     → "src/main.py, 3 edits"
glob     → "**/*.py"
grep     → "/pattern/ *.py"
bash     → "pytest tests/" (truncated at 80 chars)
git      → "commit (message=Fix bug)"
question → "Which approach?" (truncated at 60 chars)
```

### Multi-line Input

Trailing `\` continues input on the next line:

```
> Write a function that\
... calculates the fibonacci\
... sequence
```

### Run Loop

```python
async def run(self):
    self._print_banner()
    while True:
        user_input = self._prompt()      # Input with ">" prompt
        if user_input.startswith("/"):
            if await self._handle_command(user_input):
                continue                  # Command handled
            else:
                break                     # /quit
        await self._send(user_input)      # Agent interaction
    await self._session.close()
```

### Send Flow

```python
async def _send(self, message):
    result = await self._session.send(message)
    # Display final response text
    print(result.text)
    # Display summary: [2 turns | tokens: 1500→200, 3000→150 | $0.0120]
```

---

## Command System (`taui/commands/`)

### SlashCommand Protocol

```python
class SlashCommand(Protocol):
    name: str               # e.g. "help"
    description: str        # e.g. "Show available commands"

    async def execute(self, ctx: CommandContext) -> CommandResult: ...
```

### CommandContext

```python
@dataclass
class CommandContext:
    raw_input: str          # "/model gpt-4o"
    args: list[str]         # ["gpt-4o"]
    extras: dict[str, Any]  # For extensions
```

### CommandResult

```python
@dataclass
class CommandResult:
    output: str
    error: bool = False
    metadata: dict[str, Any] = {}

    @classmethod ok(output, **metadata)
    @classmethod fail(output, **metadata)
```

### CommandRegistry

```python
registry = CommandRegistry()
registry.register(my_command)            # Add command
registry.alias("h", "help")             # Create alias
command = registry.get("help")           # Lookup (resolves aliases)
result = await registry.execute("/help") # Parse + dispatch

registry.names                           # Sorted command names
registry.help_text()                     # Formatted help string
```

Command dispatch:
1. Strip leading `/`
2. Split into name + args
3. Resolve alias → canonical name
4. Lookup in registry
5. Create `CommandContext(raw_input, args)`
6. Call `command.execute(ctx)`

Unknown commands → error with list of available commands.

### Built-in Commands

| Command | Aliases | Description |
|---------|---------|-------------|
| `/help` | `/h`, `/?` | Show all commands |
| `/cost` | — | Token usage and cost summary |
| `/compact` | — | Request conversation compaction |
| `/clear` | — | Clear conversation history |
| `/model` | — | Show or set model (`/model gpt-4o`) |
| `/quit` | `/q`, `/exit` | Exit (handled directly in REPL, not via registry) |

**Note**: `/quit`, `/q`, `/exit` are handled in the REPL loop before reaching the command registry.

### Dependency Injection

Commands receive dependencies via closures:

```python
def register_builtins(registry, *, get_session, get_tracker):
    clear_cmd = ClearCommand()
    clear_cmd._get_loop = lambda: get_session()._loop

    model_cmd = ModelCommand()
    model_cmd._get_session = get_session

    cost_cmd = CostCommand()
    cost_cmd._get_tracker = get_tracker
```

---

## Extension Points for Self-Edit

1. **New slash commands**: Create a class satisfying `SlashCommand` protocol, register via `registry.register(cmd)`
2. **Command aliases**: `registry.alias("shortcut", "long_name")`
3. **Custom display**: Replace callbacks on `session._loop` to change tool output formatting

The command registry is built in `Repl._build_commands()`. Extensions loaded before REPL start can add commands to `session._commands` (or the Repl needs an extension hook — currently the registry is built privately).

---

## Terminal Colors

Helper functions for ANSI colors (auto-detected via `isatty()`):

```python
_dim(text)     # Grey
_bold(text)    # Bold
_green(text)   # User prompt ">"
_yellow(text)  # Warnings, approvals
_red(text)     # Errors
_cyan(text)    # Tool calls
```

---

## Files

| File | Purpose |
|------|---------|
| `taui/cli.py` | Repl, parse_args, async_main, main, color helpers |
| `taui/commands/registry.py` | CommandContext, CommandResult, SlashCommand, CommandRegistry |
| `taui/commands/builtins.py` | HelpCommand, CostCommand, CompactCommand, ClearCommand, ModelCommand |
| `taui/commands/__init__.py` | Re-exports |
