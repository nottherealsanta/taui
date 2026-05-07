# Built-in Tools

9 tools ship with taui. All are dataclasses with `working_dir: Path` set by `Session.create()`.

---

## File Tools (`taui/tools/builtins/files.py`)

### read

```
name: "read"
category: FILE_READ
parameters: path (required), offset (int, 1-indexed), limit (int, default 500)
```

- If `path` is a directory → returns sorted listing (`dirs/` first)
- If `path` is a file → returns numbered lines (`    1| line content`)
- Binary files → rejected with error
- Max 2000 lines per call, max 2000 chars per line (truncated with `…`)
- On file-not-found → suggests similar filenames via `difflib.get_close_matches`
- Path traversal protection via `resolve_path()` (must stay within workspace)

### write

```
name: "write"
category: FILE_WRITE
parameters: path (required), content (required)
```

- Creates parent directories automatically
- **Atomic writes**: writes to temp file then renames (via `tempfile.mkstemp` + `Path.replace`)
- Returns line count in result

### glob

```
name: "glob"
category: SEARCH
parameters: pattern (required), path (optional base dir)
```

- Uses `Path.glob()` — supports `**/*.py`, `src/**/*.ts`, etc.
- Skips `SKIP_DIRS` (.git, node_modules, __pycache__, .venv, etc.)
- Sorts by modification time (newest first)
- Max 200 results shown

### grep

```
name: "grep"
category: SEARCH
parameters: pattern (required, regex), path (optional base dir), include (optional filename glob)
```

- Compiles regex via `re.compile()` — invalid regex returns error
- Skips binary files and `SKIP_DIRS`
- Returns `file:line: content` format
- Max 500 matches
- Groups results by file with file headers

---

## Edit Tool (`taui/tools/builtins/edit.py`)

```
name: "edit"
category: FILE_WRITE
parameters: path (required), edits (required, list of {old_text, new_text})
```

- **Fuzzy matching chain**: exact match → stripped match → `difflib.SequenceMatcher` (0.6 threshold)
- **Per-file locking**: `asyncio.Lock` per file path prevents concurrent edits
- **Atomic writes**: same temp-file-then-rename pattern as WriteTool
- Creates file if it doesn't exist (with all `new_text` concatenated)
- Returns unified diff of changes

**Edit schema**:
```json
{
    "path": "src/main.py",
    "edits": [
        {"old_text": "def foo():", "new_text": "def foo(x: int):"},
        {"old_text": "return None", "new_text": "return x"}
    ]
}
```

---

## Bash Tool (`taui/tools/builtins/bash.py`)

```
name: "bash"
category: SHELL
parameters: command (required), timeout (int, default 60, max 300)
```

- **Filtered environment**: only allowlisted vars passed through (HOME, PATH, LANG, EDITOR, XDG_*, etc.)
- **Process group isolation**: `start_new_session=True` so kill reaches all child processes
- **Graceful kill**: SIGTERM → 1s wait → SIGKILL if still alive
- **Output cap**: 50KB / 2000 lines (whichever hits first)
- Non-zero exit code → `error=True` with exit code in content

---

## Git Tool (`taui/tools/builtins/git.py`)

```
name: "git"
category: GIT
parameters: operation (required), args (optional dict)
```

### Operations

| Operation | Read/Write | Args |
|-----------|-----------|------|
| `status` | read | — |
| `diff` | read | `staged: bool`, `file: str` |
| `log` | read | `count: int` (default 10, max 100), `file: str` |
| `show` | read | `ref: str` (default HEAD) |
| `blame` | read | `file: str` (required), `line_start/line_end: int` |
| `branch_list` | read | — |
| `branch_current` | read | — |
| `stash_list` | read | — |
| `commit` | write | `message: str` (required) |
| `add` | write | `files: list[str]` or `str` (default: `-A`) |
| `checkout` | write | `ref: str` (required) |
| `stash_push` | write | `message: str` |
| `stash_pop` | write | `index: int` |

- All operations via `asyncio.create_subprocess_exec` with 30s timeout
- Output capped at 50KB
- Write operations should be gated by `CONFIRM` policy in production

---

## Memory Tool (`taui/tools/builtins/memory.py`)

```
name: "memory"
category: MEMORY
parameters: operation (required), key (str), content (str)
```

### Operations

| Operation | Required args | Description |
|-----------|--------------|-------------|
| `save` | key, content | Create or overwrite `.taui/memory/{key}.md` |
| `read` | key | Read entry content |
| `list` | — | List all entries with sizes |
| `delete` | key | Remove entry |

- Storage: `.taui/memory/*.md` files in workspace
- **Path traversal protection**: keys sanitized (`/`, `\`, `..` replaced with `_`)
- On read miss → suggests existing keys
- Files are plain markdown — editable by hand

---

## Question Tool (`taui/tools/builtins/question.py`)

```
name: "question"
category: QUESTION
parameters: question (required, str), options (optional, list[str])
```

- Uses `_ask` callback (async function set by the UI layer)
- TUI wires `_ask` to an inline question prompt
- If no callback → returns "Proceed with your best judgment"
- If user dismisses → same fallback response

**Callback signature**: `async (question: str, options: list[str] | None) -> str | None`

---

## Shared Utilities (`taui/tools/builtins/common.py`)

| Function | Purpose |
|----------|---------|
| `resolve_path(working_dir, raw)` | Resolve + workspace boundary check |
| `is_binary(path)` | Null-byte + non-printable heuristic |
| `suggest_similar(path, working_dir)` | `difflib.get_close_matches` on siblings |
| `truncate(text, max_lines, max_bytes)` | Line-aware truncation |
| `SKIP_DIRS` | frozenset of dirs to skip (.git, node_modules, etc.) |

---

## How Tools Are Wired

```python
# In Session.create():
registry = ToolRegistry()
register_builtins(registry)            # Registers all 9 tools

# Set working_dir on each tool
for name in registry.names:
    tool = registry.get(name)
    if hasattr(tool, "working_dir"):
        tool.working_dir = config.working_dir

# Wire question callback (in the UI layer)
question_tool = registry.get("question")
question_tool._ask = my_ask_function

# Tools are passed to LLM via schemas
schemas = registry.schemas()           # OpenAI function-calling format
```
