# Built-in Tools

20 tools ship with taui. All are dataclasses wired up by `Session.create()`, which sets
`working_dir` and injects any required callbacks or sub-system references.

---

## File Read Tools

### read (`taui/tools/builtins/files.py`)

```
category:   FILE_READ
parameters: path (required), offset (int, 1-indexed, default 1), limit (int, default 500)
```

- **Directory path** → sorted listing with trailing `/` on subdirectory names
- **File path** → numbered lines: `    1| line content`
- Binary files rejected with error
- Max 2000 lines per call (hard cap); max 2000 chars per line (excess replaced with `…`)
- On file-not-found → suggests similar filenames via `difflib.get_close_matches`
- Path traversal protection via `resolve_path()` (must stay within workspace)
- Metadata: `total_lines`, `path`
- Guidelines: read before editing; use `offset`/`limit` to page large files

### peek (`taui/tools/builtins/peek.py`)

```
category:   FILE_READ
parameters: handle (required, str), offset (int, default 0), limit (int, default 4096)
```

Retrieves a byte-addressed window from a truncated tool output stored in
`TruncationStore`. When a tool produces output larger than 8 KiB, the executor
truncates it and appends a handle like `tr_abc12345`. Use `peek` to read the remainder.

- `handle` — the `tr_xxxx` string from the truncation notice
- `offset` — byte position to start reading from
- `limit` — max bytes to return (default 4 KiB)
- Returns `None`-like error if the handle has expired (session ended)
- Appends a continuation hint showing how many KiB remain and the next offset
- The executor never truncates the output of `peek` itself (circular guard)

### webfetch (`taui/tools/builtins/webfetch.py`)

```
category:   FILE_READ
parameters: url (required), max_bytes (int, default 32768)
```

Fetches and caches web content (documentation, API references, etc.).

- Requires `httpx` to be installed; returns error if not available
- **Cache**: SHA-256 keyed JSON files in `.taui/cache/web/`, TTL 1 hour
- Cached response is returned immediately without a network request
- `max_bytes` caps the response before returning to the LLM
- Follows HTTP redirects (`follow_redirects=True`)
- Cache content is stored untruncated; only the in-memory return is capped

---

## File Write Tools

### write (`taui/tools/builtins/files.py`)

```
category:   FILE_WRITE
parameters: path (required), content (required)
default policy: CONFIRM
```

- Creates parent directories automatically (`mkdir -p` behaviour)
- **Atomic write**: writes to `.taui_write_*.tmp` in the same directory, then renames
  to prevent partial writes on crash
- Returns line count in the `ToolResult.ok` message
- Metadata: `path`, `lines`
- Guidelines: use `write` for new files or full replacement; use `edit` for targeted changes

### edit (`taui/tools/builtins/edit.py`)

```
category:   FILE_WRITE
parameters: path (required), edits (required, array of {old_text, new_text})
default policy: CONFIRM
```

Edit a file by search-and-replace. Multiple edits can be batched in a single call.

**Fuzzy matching chain** (tried in order until a unique match is found):

| Strategy | Description |
|----------|-------------|
| `exact` | Verbatim string search |
| `unicode_normalized` | Normalizes smart quotes, em-dashes, ellipsis, NBSP, etc. |
| `whitespace_normalized` | Strips trailing whitespace from each line |
| `indentation_flexible` | `textwrap.dedent` on the search block |

- Returns an error if `old_text` matches zero or more than one location
- Edits are applied in reverse position order so earlier offsets remain stable
- Overlapping edits are rejected with an error
- **Per-file locking**: `asyncio.Lock` per absolute path serializes concurrent edits
- **Atomic write**: same temp-file-then-rename pattern as `write`
- Returns unified diff of changes in `content`; metadata: `path`, `edits_applied`, `strategies`
- `output_schema` defined (diff string + lines_changed)
- Guidelines: keep `old_text` minimal but unique; include a few lines of context

### apply_patch (`taui/tools/builtins/apply_patch.py`)

```
category:   FILE_WRITE
parameters: patch (required, unified diff text)
```

Apply a standard unified diff patch to one or more files. More efficient than multiple
`edit` calls for large refactors with many hunks.

- Parses `--- a/...` / `+++ b/...` headers and `@@ ... @@` hunk markers
- Supports multi-hunk and multi-file patches
- Creates new files when the patch targets a non-existent path
- Trailing whitespace differences in context lines are tolerated
- Returns a summary line per file: `Created <path>` or `Patched <path>`
- Respects `_path_guard` and `_file_tracker` hooks (same as `write`/`edit`)

### notebook_edit (`taui/tools/builtins/notebook_edit.py`)

```
category:   FILE_WRITE
parameters: path (required), cell_index (required, int), action (required), source (str), cell_type (str)
actions:    replace | insert | delete
```

Cell-aware editor for Jupyter notebooks (`.ipynb`).

- `replace` — overwrite `cells[cell_index].source`; `cell_index` must be in range
- `insert` — insert a new cell at `cell_index`; `cell_type` defaults to `"code"`
- `delete` — remove `cells[cell_index]`
- Writes the notebook back with `json.dumps(nb, indent=1, ensure_ascii=False)`
- Validates that the file has a `.ipynb` extension
- Source lines are formatted so every line except the last ends with `\n` (notebook convention)

---

## Search Tools

### glob (`taui/tools/builtins/files.py`)

```
category:   SEARCH
parameters: pattern (required), path (optional base dir, default: working dir)
```

- Uses `Path.glob()` — supports `**/*.py`, `src/**/*.ts`, etc.
- Skips `SKIP_DIRS`: `.git`, `__pycache__`, `node_modules`, `.venv`, `venv`, `.tox`,
  `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `dist`, `build`, `.egg-info`
- Results sorted by modification time, newest first
- Max 200 results shown; remaining count appended if truncated
- Metadata: `count`, `pattern`
- Guidelines: use `**/*.py` style patterns; filter by `path` to narrow scope

### grep (`taui/tools/builtins/files.py`)

```
category:   SEARCH
parameters: pattern (required, regex), path (optional base dir), include (optional filename glob)
```

- Compiles regex via `re.compile()` — invalid pattern returns error immediately
- Skips binary files (via `is_binary()`) and `SKIP_DIRS`
- `include` filters by filename glob, e.g. `*.py`, `*.{ts,tsx}`
- Returns `file:lineno| content` format, line content capped at 200 chars
- Max 500 matches total (truncates with notice)
- Metadata: `match_count`, `file_count`
- Guidelines: use `include` to limit to specific file types

### lsp (`taui/tools/builtins/lsp.py`)

```
category:   SEARCH
parameters: action (required), file, line, character, language, query
actions:    goto_definition | find_references | hover | document_symbols | workspace_symbols
```

LSP-backed code navigation. Requires a language server installed for the target language.

Language is auto-detected from file extension (`.py` → `python`, `.ts`/`.tsx` →
`typescript`, `.js`/`.jsx` → `javascript`, `.rs` → `rust`, `.go` → `go`,
`.c`/`.h` → `c`, `.cpp`/`.hpp`/`.cc` → `cpp`). Provide `language` explicitly to
override.

| Action | Required params | Returns |
|--------|----------------|---------|
| `goto_definition` | file, line, character | JSON array of location objects |
| `find_references` | file, line, character | JSON array of location objects |
| `hover` | file, line, character | JSON hover object or null |
| `document_symbols` | file | JSON array of symbol objects |
| `workspace_symbols` | query | JSON array of symbol objects |

- `line` and `character` are 1-indexed
- `_lsp_manager` is injected by `Session.create()`; returns error if not available
- Experimental — no production consumer yet

### repo_overview (`taui/tools/builtins/repo_overview.py`)

```
category:   SEARCH
parameters: max_depth (int, default 2)
```

One-shot project survey. Useful as a first step when exploring an unfamiliar codebase.

Sections produced:
1. **Languages** — file count by extension (top 15, mapped to language names)
2. **Directory structure** — tree listing up to `max_depth` (capped at 80 lines)
3. **Likely entry points** — checks for `main.py`, `pyproject.toml`, `package.json`,
   `Cargo.toml`, `go.mod`, etc.
4. **Git** — current branch, last 5 commit messages, working tree status
5. **Config files** — presence of `pyproject.toml`, `Dockerfile`, `tsconfig.json`, etc.

Skips the same set as `glob` (`_SKIP_DIRS` in `repo_overview.py`).

---

## Shell Tool

### bash (`taui/tools/builtins/bash.py`)

```
category:   SHELL
parameters: command (required), timeout (int, default 60, max 300)
default policy: CONFIRM
```

- **Filtered environment**: only allowlisted vars passed through —
  `HOME`, `USER`, `LANG`, `LC_ALL`, `LC_CTYPE`, `PATH`, `SHELL`, `TERM`,
  `TMPDIR`, `EDITOR`, `VISUAL`, `PAGER`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`,
  `XDG_CACHE_HOME`
- **Process group isolation**: `start_new_session=True` so SIGTERM/SIGKILL reaches
  all child processes
- **Graceful kill on timeout**: SIGTERM → 1s wait → SIGKILL if still alive
- **Output cap**: 50 KB / 2000 lines (whichever is hit first), via `common.truncate()`
- Non-zero exit code → `ToolResult` with `error=True`; exit code included in content
- Metadata: `exit_code`, `command`, `truncated`
- Guidelines: prefer dedicated tools (`read` over `cat`, `grep` over shell grep);
  always pass `timeout` for long commands

---

## Git Tool

### git (`taui/tools/builtins/git.py`)

```
category:   GIT
parameters: operation (required), args (optional dict)
```

All operations run via `asyncio.create_subprocess_exec` with a 30-second timeout.
Output is capped at 50 KB.

**Read operations** (no approval needed by default):

| Operation | `args` keys | Description |
|-----------|-------------|-------------|
| `status` | — | Working tree status (porcelain v1). Metadata: `clean`, `files`, `counts` |
| `diff` | `staged: bool`, `file: str` | Full diff + stat. Metadata: `stat`, `hunks`, `files_changed` |
| `log` | `count: int` (default 10, max 100), `file: str` | One-line log |
| `show` | `ref: str` (default `HEAD`) | Commit details with `--stat` |
| `blame` | `file: str` (required), `line_start: int`, `line_end: int` | Line-by-line blame |
| `branch_list` | — | All branches with verbose info |
| `branch_current` | — | Current branch name. Metadata: `branch` |
| `stash_list` | — | All stash entries |

**Write operations** (require `CONFIRM` policy in practice):

| Operation | `args` keys | Description |
|-----------|-------------|-------------|
| `commit` | `message: str` (required) | `git commit -m <message>` |
| `add` | `files: list[str] \| str` (default: `-A`) | Stage files |
| `checkout` | `ref: str` (required) | Checkout branch or ref |
| `stash_push` | `message: str` | `git stash push [-m <message>]` |
| `stash_pop` | `index: int` | `git stash pop [stash@{N}]` |

---

## Memory Tool

### memory (`taui/tools/builtins/memory.py`)

```
category:   MEMORY
parameters: operation (required), key (str), content (str)
```

Persistent cross-session knowledge store. Entries are plain Markdown files in
`.taui/memory/` within the workspace directory.

| Operation | Required args | Description |
|-----------|--------------|-------------|
| `save` | `key`, `content` | Create or overwrite `.taui/memory/{key}.md` |
| `read` | `key` | Return entry content |
| `list` | — | All entries with sizes |
| `delete` | `key` | Remove entry |

- Keys are sanitized: `/`, `\`, `..` replaced with `_`; must not start with `.`
- Path traversal is rejected (path must stay inside `.taui/memory/`)
- On `read` miss → suggests existing keys
- Files are plain Markdown; editable by hand between sessions
- Guidelines: persist project conventions, build commands, architecture notes;
  list before saving to avoid duplicates

---

## Question Tool

### question (`taui/tools/builtins/question.py`)

```
category:   QUESTION
parameters: question (required, str), options (optional, list[str])
```

Ask the user for clarification or a decision. Blocks until the user responds.

- Uses `_ask` callback (async function injected by the TUI layer):
  `async (question: str, options: list[str] | None) -> str | None`
- TUI wires `_ask` to an inline question prompt widget
- If no callback is set → returns "Proceed with your best judgment" (`answered=False`)
- If user dismisses the prompt → same fallback
- Append `' (Recommended)'` to an option string to mark the preferred choice
- Metadata: `answered: bool`, `answer: str` (when answered)
- Guidelines: only ask when genuinely uncertain; provide 2–3 concise options

---

## Agent Tools

### session_name (`taui/tools/builtins/session_name.py`)

```
category:   AGENT
parameters: name (required, str, max 80 chars)
```

Set a short (2–6 word) descriptive label for the current session. Called once after the
user's first message. If never called, the session picker falls back to the created
timestamp.

- `_set_name` callback is injected by `Session.create()`: `async (name: str) -> None`
- Leading/trailing whitespace and extra lines stripped
- Name truncated at 80 characters
- Guidelines: call exactly once; examples: `"fix /sessions crash"`,
  `"add session_name tool"`, `"investigate flaky test"`

### skills (`taui/tools/builtins/skills.py`)

```
category:   AGENT
parameters: operation (required), skill (str, for load/unload)
operations: list | load | unload | status
```

Discover, load, and unload skill packages. Skills are reusable capability bundles with
a `SKILL.md` instruction file.

| Operation | Description |
|-----------|-------------|
| `list` | Re-discover skills and show all with scope (`project`/`global`) and load status |
| `load` | Inject a skill's `SKILL.md` as a system message via `_inject_message` |
| `unload` | Mark skill as unloaded (instructions remain in history) |
| `status` | Show loaded skills with estimated token counts |

- `_skill_registry` (a `SkillRegistry`) and `_inject_message` are injected by
  `Session.create()`
- Loading injects `[Skill: <name>]\n\n<content>` into the conversation
- Metadata: `count`, `skill`, `tokens`
- Guidelines: list first; load only what you need; unload when done to free context

### sub_agent (`taui/tools/builtins/sub_agent.py`)

```
category:   AGENT
parameters: task (required, str), tools (list[str]), max_turns (int, default 10, max 25)
```

Delegate a focused sub-task to a child agent. The child has its own conversation
context, a scoped tool subset, and a separate turn budget. It runs to completion and
returns its final text response.

- **Preferred path**: calls `session.create_sub_session(tools, system_prompt, model,
  max_turns)` then `sub.send(task)`
- **Legacy fallback** (tests): direct `AgentLoop` construction from injected `_llm` and
  `_parent_executor`
- Default tool subset: `["read", "glob", "grep", "bash"]`
- `sub_agent` is stripped from the child's tool list to prevent infinite nesting
- System prompt: `"You are a focused research agent. Complete the given task concisely
  and return your findings."`
- Metadata: `turns`, `state`
- Guidelines: use for research, code analysis, or tasks that benefit from fresh context;
  keep the task description clear and specific

### task (`taui/tools/builtins/task.py`)

```
category:   AGENT
parameters: operation (required), task_id, title, status, priority, notes
operations: list | add | update | complete | remove | clear
status values: pending | in_progress | completed | cancelled
priority values: high | medium | low
```

Persistent task list for tracking multi-step work within a session. Tasks are stored as
JSON at `.taui/sessions/<session_id>/tasks.json`.

| Operation | Required | Description |
|-----------|----------|-------------|
| `list` | — | Show all tasks with status icons |
| `add` | `title` | Create a new pending task |
| `update` | `task_id` | Change status, priority, notes, or title |
| `complete` | `task_id` | Shorthand for `update` → `status=completed` |
| `remove` | `task_id` | Delete a task |
| `clear` | — | Remove all tasks |

- Task IDs are incrementing integers as strings (`"1"`, `"2"`, ...)
- Status icons in `list` output: ⬜ pending, 🔄 in_progress, ✅ completed, ❌ cancelled
- Guidelines: break complex work into steps; update status as each step completes

### mcp (`taui/tools/builtins/mcp.py`)

```
category:   AGENT
parameters: operation (required), server (str), tool (str), arguments (object)
operations: servers | connect | disconnect | tools | call
```

Interface to external MCP (Model Context Protocol) servers and their tools.

| Operation | Description |
|-----------|-------------|
| `servers` | List configured servers and connection status |
| `connect` | Connect to a server; returns available tool names |
| `disconnect` | Disconnect from a connected server |
| `tools` | List all tools from connected servers, grouped by server |
| `call` | Invoke a tool; `server` optional (auto-detected from tool name) |

- `_manager` (an `McpManager`) is injected by `Session.create()`
- MCP servers are configured in `.taui/mcp.toml` or `~/.config/taui/mcp.toml`
- `call` extracts `content[].text` parts from the MCP response
- `isError=true` in the MCP response → `ToolResult.fail(...)`
- Metadata: `count`, `server`, `tool`, `tools`
- Guidelines: run `servers` first; connect before calling; MCP extends built-in capabilities

---

## Shared Utilities (`taui/tools/builtins/common.py`)

| Function / Constant | Purpose |
|---------------------|---------|
| `SKIP_DIRS` | `frozenset` of directories to skip: `.git`, `__pycache__`, `node_modules`, `.venv`, `venv`, `.tox`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `dist`, `build`, `.egg-info` |
| `resolve_path(working_dir, raw)` | Resolve relative or absolute path; rejects traversal outside workspace |
| `is_binary(path, sample_size=8192)` | Heuristic: null bytes or >30% non-printable chars = binary |
| `suggest_similar(path, working_dir)` | `difflib.get_close_matches` on sibling filenames |
| `truncate(text, *, max_lines, max_bytes)` | Line-aware truncation; returns `(text, was_truncated)` |

---

## Wiring in Session.create()

```python
registry = ToolRegistry()
register_builtins(registry)           # Registers all built-in tools

# Set working_dir
for name in registry.names:
    tool = registry.get(name)
    if hasattr(tool, "working_dir"):
        tool.working_dir = config.working_dir

# Wire callbacks / injected dependencies
question_tool = registry.get("question")
question_tool._ask = my_ask_function

peek_tool = registry.get("peek")
peek_tool._truncation_store = truncation_store

session_name_tool = registry.get("session_name")
session_name_tool._set_name = store.set_session_name

skills_tool = registry.get("skills")
skills_tool._skill_registry = skill_registry
skills_tool._inject_message = inject_system_message

sub_agent_tool = registry.get("sub_agent")
sub_agent_tool._session = session

mcp_tool = registry.get("mcp")
mcp_tool._manager = mcp_manager
```

---

## Summary Table

| Tool | Category | File | Default Policy |
|------|----------|------|----------------|
| `read` | FILE_READ | `files.py` | AUTO |
| `peek` | FILE_READ | `peek.py` | AUTO |
| `webfetch` | FILE_READ | `webfetch.py` | AUTO |
| `write` | FILE_WRITE | `files.py` | CONFIRM |
| `edit` | FILE_WRITE | `edit.py` | CONFIRM |
| `apply_patch` | FILE_WRITE | `apply_patch.py` | CONFIRM |
| `notebook_edit` | FILE_WRITE | `notebook_edit.py` | CONFIRM |
| `glob` | SEARCH | `files.py` | AUTO |
| `grep` | SEARCH | `files.py` | AUTO |
| `lsp` | SEARCH | `lsp.py` | AUTO |
| `repo_overview` | SEARCH | `repo_overview.py` | AUTO |
| `bash` | SHELL | `bash.py` | CONFIRM |
| `git` | GIT | `git.py` | AUTO (write ops: CONFIRM in practice) |
| `memory` | MEMORY | `memory.py` | AUTO |
| `question` | QUESTION | `question.py` | AUTO |
| `session_name` | AGENT | `session_name.py` | AUTO |
| `skills` | AGENT | `skills.py` | AUTO |
| `sub_agent` | AGENT | `sub_agent.py` | AUTO |
| `task` | AGENT | `task.py` | AUTO |
| `mcp` | AGENT | `mcp.py` | AUTO |
