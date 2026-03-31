# Tool Expansion Plan for Taui

## Research Summary

### Current Taui Tool Architecture
- **Base Protocol** (`taui/tools/base.py`): `Tool` Protocol with `name`, `description`, `schema`, `origin`, `execute(args, ctx) → ToolResult`
- **Registry** (`taui/tools/registry.py`): Simple dict-based `ToolRegistry` with `register()`, `get()`, `list_schemas()`
- **Executor** (`taui/tools/executor.py`): `ToolExecutor` with schema validation → policy evaluation → timeout execution → outcome dispatch
- **Builtins** (`taui/tools/builtins/`): `ReadTool`, `EditTool`, `WriteTool`, `BashTool`, `GlobTool`, `GrepTool` + 8 spec-tree tools
- **Context** (`ToolContext`): carries `working_dir`, `session`, `policy`

### Pi Coding Agent Pattern (Reference For Extensibility)
- **Factory pattern**: Each tool exports `createXxxToolDefinition(cwd, options?)` → `ToolDefinition` and `createXxxTool(cwd)` → `AgentTool`
- **Separation of concerns**: `ToolDefinition` (includes UI rendering) vs `AgentTool` (just execute). `wrapToolDefinition()` bridges the two
- **Pluggable operations**: Each tool (Read, Bash, Write, etc.) defines an `XxxOperations` interface (`readFile`, `access`, `detectImageMimeType`) with a `defaultXxxOperations` using local fs. Can swap for SSH, sandboxed, etc.
- **Tool sets**: `codingTools = [read, bash, edit, write]`, `readOnlyTools = [read, grep, find, ls]`, `allTools = {...}`. CLI flag `--tools read,bash` selects which
- **Extension system**: TypeScript modules that `pi.registerTool({...})` — full replacement of builtins possible
- **Skills**: On-demand capability packages as markdown SKILL.md files, loaded via `/skill:name`
- **No MCP, No sub-agents, No plan mode built-in** — all delegated to extensions/packages

### OpenCode Pattern (Reference For Agent-Tool Integration)
- **Tool.define()**: `Tool.define(id, init | definition)` — factory with validation wrapping, truncation, and error formatting
- **Separate descriptions**: Tool descriptions in `.txt` files imported alongside the `.ts` tool implementation
- **Registry with filtering**: `ToolRegistry.tools(model, agent?)` — filters tools based on model (e.g., `apply_patch` for GPT, `edit`/`write` for others)
- **Permission system**: `ctx.ask({ permission: "read", patterns: [filepath], always: ["*"], metadata: {} })` — tools request permission through context
- **LSP tool**: Operations: `goToDefinition`, `findReferences`, `hover`, `documentSymbol`, `workspaceSymbol`, `goToImplementation`, call hierarchy
- **Task tool** (subagent launcher): Creates child sessions with filtered permissions, calls `SessionPrompt.prompt()` with agent config
- **Batch tool**: Parallel execution of up to 25 tool calls in one LLM turn
- **Skill tool**: Loads SKILL.md + lists bundled files in `<skill_files>` block
- **Plan mode**: `plan_exit` tool transitions from plan agent to build agent; agents are config-defined (`build`, `plan`, `general`, `explore`, `compaction`)
- **Agent system**: Agents defined as config objects with `name`, `mode` (primary/subagent), `permission` ruleset, optional `model`, `prompt`, `steps`
- **Todo tool**: `todowrite` manages structured task tracking per session

---

## Architectural Changes

### 1. New Tool Base Class (Replaces Protocol)

The current `Tool` Protocol is fine for simple cases but doesn't support:
- Factory pattern (parameterized tool creation)
- Description loaded from files
- Metadata emission during execution
- Abort/cancellation signals
- Pluggable operations

**New design** — keep the `Tool` Protocol but add a convenience base class and a `define()` factory:

```python
# taui/tools/base.py — additions

@dataclass(slots=True)
class ToolResult:
    content: str
    error: bool = False
    metadata: dict[str, Any] | None = None
    attachments: list[dict[str, Any]] | None = None  # NEW: for images, diffs, etc.

    @classmethod
    def ok(cls, content: str, **kw) -> "ToolResult": ...
    @classmethod
    def fail(cls, content: str, **kw) -> "ToolResult": ...


@dataclass(slots=True)
class ToolContext:
    working_dir: Path
    session: Any
    policy: Policy
    abort: asyncio.Event | None = None       # NEW: cancellation signal
    session_id: str | None = None            # NEW: for session scoped data
    agent_name: str | None = None            # NEW: which agent is calling
    messages: list[Any] | None = None        # NEW: conversation context (read-only)
    metadata_callback: Callable | None = None  # NEW: emit metadata mid-execution

```

### 2. Tool Definition Pattern (Pi-Inspired)

Add a `define()` helper for declaratively creating tools:

```python
# taui/tools/define.py

def define_tool(
    name: str,
    description: str | Path,   # string or path to .md/.txt file
    schema: dict[str, Any],
    execute: Callable[[dict, ToolContext], Awaitable[ToolResult]],
    *,
    origin: str = "builtin",
) -> Tool:
    """Create a Tool from a simple function. Description can be a file path."""
    ...
```

### 3. Tool Categories & Filtering (OpenCode-Inspired)

```python
# taui/tools/categories.py

class ToolCategory(str, Enum):
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    SEARCH = "search"
    SHELL = "shell"
    LSP = "lsp"
    GIT = "git"
    PLAN = "plan"
    SKILL = "skill"
    AGENT = "agent"
    SPEC = "spec"

# Registry gains category-based filtering
class ToolRegistry:
    def tools_for_agent(self, agent_name: str, categories: set[ToolCategory] | None = None) -> list[Tool]: ...
```

---

## Tool Implementation Plan

### Tool 1: Read Files (`read`)
**Status**: Already exists at `taui/tools/builtins/read.py`

**Enhancements needed**:
- [ ] Directory listing support (when path is a dir, list entries like OpenCode)
- [ ] Binary file detection (check for null bytes / high non-printable ratio)
- [ ] Image file support (return as base64 attachment in `ToolResult.attachments`)
- [ ] Byte-level truncation (not just line count — cap at 50KB like OpenCode)
- [ ] "File not found" suggestions (fuzzy match nearby filenames)
- [ ] 1-indexed offset (currently 0-indexed, switch to 1-indexed for LLM clarity)

**File**: `taui/tools/builtins/read.py` (modify existing)

---

### Tool 2: Search (`search`, `grep`, `glob`)
**Status**: `GrepTool` and `GlobTool` exist

**Enhancements needed**:
- [ ] Add `CodeSearchTool` — semantic/indexed search using the existing `taui/symbols/` module
  - Search by symbol name, kind (function, class, variable), file pattern
  - Returns symbol locations with context snippets
- [ ] Add `FindTool` — `find`-like recursive file search with type/name/size/mtime filters
- [ ] Enhance `GrepTool` — add context lines (before/after), max results limit, file type filter
- [ ] Enhance `GlobTool` — add depth limit, exclude patterns, follow symlinks option

**New files**:
- `taui/tools/builtins/codesearch.py` — wraps `taui/symbols/resolver.py`
- `taui/tools/builtins/find.py` — recursive file finder

---

### Tool 3: Write File (Provider-Aware) (`write`, `edit`, `apply_patch`)
**Status**: `WriteTool` and `EditTool` exist

**Key insight from research**: Different LLM providers work better with different write strategies:
- **Anthropic/Claude**: Prefers `edit` (old_string → new_string replacement)
- **OpenAI/GPT**: Prefers `apply_patch` (unified diff format)
- **Google/Gemini**: Works with both but benefits from `write` (full file) for small files

**Enhancements needed**:
- [ ] Add `ApplyPatchTool` — unified diff application for GPT models
  - Parse unified diff format
  - Apply hunks with fuzzy matching (like OpenCode's replacer chain)
  - Fall back gracefully on failed hunks
- [ ] Add `MultiEditTool` — batch multiple edits in one call (reduces round trips)
  - Array of `{file, old_string, new_string}` operations
  - Atomic: all succeed or all fail per file
- [ ] Provider-aware tool selection in registry
  - Registry method: `tools_for_model(provider_id, model_id)` filters edit vs apply_patch
- [ ] Enhance `EditTool` with fuzzy matching chain (Pi/OpenCode pattern):
  1. Exact match
  2. Line-trimmed match (ignore leading/trailing whitespace per line)
  3. Block anchor match (first+last line anchors with similarity scoring)
  4. Whitespace-normalized match
  5. Indentation-flexible match
- [ ] LSP diagnostics after edit (report new errors introduced)
- [ ] File format detection for line endings (CRLF vs LF preservation)

**New files**:
- `taui/tools/builtins/apply_patch.py`
- `taui/tools/builtins/multiedit.py`
- `taui/tools/builtins/fuzzy_match.py` — shared fuzzy matching utilities

---

### Tool 4: LSP (`lsp`)
**Status**: Not implemented. Taui has `taui/symbols/` (tree-sitter based) but no LSP client.

**Design** (modeled after OpenCode's LSP tool):

```
LSP operations:
  - goToDefinition(file, line, character)
  - findReferences(file, line, character)
  - hover(file, line, character)
  - documentSymbol(file)
  - workspaceSymbol(query)
  - goToImplementation(file, line, character)
  - diagnostics(file?)          — get current errors/warnings
  - prepareCallHierarchy(file, line, character)
  - incomingCalls(file, line, character)
  - outgoingCalls(file, line, character)
```

**Implementation approach**:
- [ ] Create `taui/lsp/` module:
  - `client.py` — LSP client using `pygls` or subprocess stdio transport
  - `manager.py` — manages LSP server lifecycles per language
  - `types.py` — position, location, diagnostic types
- [ ] Create `taui/tools/builtins/lsp.py` — the agent-facing tool
- [ ] Language server discovery: config-based mapping of file extensions → LSP server commands
- [ ] Lazy initialization: start LSP server on first use for a language
- [ ] File touch/sync: notify LSP when files are edited by other tools
- [ ] Diagnostics integration: `EditTool` and `WriteTool` call LSP.diagnostics() after writes

**Config** (in settings):
```json
{
  "lsp": {
    "servers": {
      "python": {"command": ["pyright-langserver", "--stdio"]},
      "typescript": {"command": ["typescript-language-server", "--stdio"]},
      "rust": {"command": ["rust-analyzer"]}
    }
  }
}
```

**New files**:
- `taui/lsp/__init__.py`
- `taui/lsp/client.py`
- `taui/lsp/manager.py`
- `taui/lsp/types.py`
- `taui/tools/builtins/lsp.py`

---

### Tool 5: Git (`git`)
**Status**: Not implemented

**Design**: A single tool with an `operation` parameter (like LSP tool pattern):

```
Git operations:
  - status()                     — working tree status
  - diff(file?, staged?)         — show changes
  - log(count?, file?, oneline?) — commit history
  - show(ref)                    — show commit details
  - blame(file, line_start?, line_end?) — line attribution
  - branch_list()                — list branches
  - branch_current()             — current branch name
  - stash_list()                 — list stashes
  - commit(message)              — commit staged changes  [requires approval]
  - add(files)                   — stage files             [requires approval]
  - checkout(ref)                — switch branch            [requires approval]
  - stash_push(message?)         — stash changes            [requires approval]
  - stash_pop(index?)            — pop stash                [requires approval]
```

**Implementation approach**:
- [ ] Create `taui/tools/builtins/git.py`
- [ ] Use `asyncio.create_subprocess_exec` for git commands (not a git library — keeps it simple and always matches installed git)
- [ ] Read-only operations auto-approved; mutating operations require confirmation via policy
- [ ] Output formatting: line-numbered diffs, truncated log output
- [ ] Snapshot integration: auto-checkpoint before destructive operations

**New files**:
- `taui/tools/builtins/git.py`

---

### Tool 6: Plan / TODOs (`plan`, `todowrite`)
**Status**: Not implemented

**Design** (inspired by OpenCode's todo + plan tools):

#### 6a. TodoWrite Tool
Manages a structured todo list scoped to the agent session.

```
Parameters:
  - todos: list[{id, title, status}]
  - status values: "not-started" | "in-progress" | "completed"
```

- [ ] Create `taui/tools/builtins/todo.py`
- [ ] Store todos in SpecDB (new `todos` table: id, session_id, title, status, created_at, updated_at)
- [ ] Expose via RPC notification: `agent/todosChanged` with current todo list
- [ ] Frontend: display in AgentDetailPanel

#### 6b. Plan Tool
Manages plan files for multi-step workflows.

```
Operations:
  - create(title, steps)     — create a plan file in .taui/plans/
  - read(plan_ref?)          — read current or specified plan
  - update(plan_ref, steps)  — update plan steps
  - complete(plan_ref)       — mark plan as complete
```

- [ ] Create `taui/tools/builtins/plan.py`
- [ ] Plans stored as markdown files in `.taui/plans/<session-id>.md`
- [ ] Plan format: numbered steps with checkbox status `- [x]` / `- [ ]`
- [ ] Agent can transition between plan and build modes (like OpenCode's plan_enter/plan_exit)

**New files**:
- `taui/tools/builtins/todo.py`
- `taui/tools/builtins/plan.py`

---

### Tool 7: Question Tool (`question`)
**Status**: Partially implemented (spec_ask_question exists in spec_tree.py, AgentRunner has `ask_question()`)

**Enhancements needed**:
- [ ] Standalone `QuestionTool` that doesn't require spec context
- [ ] Support structured questions with options (like OpenCode's `Question.ask()`)
- [ ] Support multiple questions in one call
- [ ] Timeout handling: auto-answer or resume without answer after configurable period

**File**: `taui/tools/builtins/question.py` (new)

---

### Tool 8: Skills (`skill`)
**Status**: Not implemented

**Design** (modeled after OpenCode's SkillTool + Pi's skill system):

#### Skill Loading Tool
```
Parameters:
  - name: str — skill name to load
```

**Skill discovery**:
1. `~/.taui/skills/` — user-global skills
2. `.taui/skills/` — project-local skills
3. Walk parent directories for `.taui/skills/`
4. Built-in skills shipped with taui

**Skill format** (Agent Skills standard):
```
<skill_dir>/
  SKILL.md       — main instructions
  scripts/       — bundled scripts
  templates/     — file templates
  reference/     — reference docs
```

#### Skill Import Tool
```
Parameters:
  - source: str — git URL, local path, or PyPI package name
  - scope: "user" | "project"  — where to install
```

**Implementation**:
- [ ] Create `taui/skills/` module:
  - `loader.py` — discover and load skills from directories
  - `registry.py` — in-memory skill registry
  - `installer.py` — install from git/local/pip
- [ ] Create `taui/tools/builtins/skill.py` — the skill loading tool
- [ ] Create `taui/tools/builtins/skill_import.py` — the skill installer tool
- [ ] Skills injected into system prompt as `<skill_content>` blocks
- [ ] Skill files listed in output for model awareness

**New files**:
- `taui/skills/__init__.py`
- `taui/skills/loader.py`
- `taui/skills/registry.py`
- `taui/skills/installer.py`
- `taui/tools/builtins/skill.py`
- `taui/tools/builtins/skill_import.py`

---

### Tool 9: Programmatic Tool Usage (Monty)
**Status**: Not implemented

**Concept**: Allow the agent to define and execute tools programmatically via Python code (like Pi's extension system but Python-native).

**Design**:

```python
# Agent writes Python code that gets executed as a tool
class MontyTool:
    """Execute Python code with access to the Taui API."""

    Parameters:
      - code: str       — Python code to execute
      - description: str — what the code does

    Available in scope:
      - taui.read(path) → str
      - taui.write(path, content)
      - taui.edit(path, old, new)
      - taui.search(query) → list[Result]
      - taui.bash(command) → str
      - taui.spec.get_tree() → list[Node]
      - taui.spec.update(ref, content)
```

**Implementation**:
- [ ] Create `taui/tools/builtins/monty.py`
- [ ] Sandboxed execution: restricted imports, no network, timeout
- [ ] API object injected into execution scope with typed helpers
- [ ] Output captured from return value and stdout
- [ ] Error handling: stack traces returned as tool result

**Security considerations**:
- Allowlisted imports only (os.path, json, re, math, collections, etc.)
- No exec/eval of nested code
- Working directory sandboxed to project
- Requires `confirm` policy by default

**New files**:
- `taui/tools/builtins/monty.py`
- `taui/tools/builtins/monty_api.py` — the API exposed to code

---

### Tool 10: Launch Agents (`task`)
**Status**: `AgentManager` and `AgentRunner` exist but not as a tool

**Design** (modeled after OpenCode's TaskTool):

#### Agent Tiers
1. **Prime Agent** — top-level, user-facing, full permissions. Only one active.
2. **Root Agent** — launched by prime or other root agents. Has most permissions but may be restricted from launching prime-level agents.
3. **Minion Agent** — launched by root agents. Restricted permissions (e.g., read-only, no sub-agent spawning, no destructive ops).

#### Task Tool (for launching sub-agents)
```
Parameters:
  - description: str         — 3-5 word task summary
  - prompt: str              — detailed task instructions
  - agent_type: str          — "root" | "minion" | specific named agent
  - task_id: str? (optional) — resume a previous task
```

**Agent definitions** (config-driven, like OpenCode):
```python
BUILTIN_AGENTS = {
    "build": Agent(
        name="build",
        mode="primary",
        description="Default agent for development work",
        permission=Permission(auto_approve={"read", "glob", "grep", "spec_*", "lsp", "git_status", "git_diff"}),
    ),
    "plan": Agent(
        name="plan",
        mode="primary",
        description="Read-only agent for analysis and planning",
        permission=Permission(auto_approve={"read", "glob", "grep", "spec_get_*", "lsp", "git_status"},
                            deny={"write", "edit", "bash", "apply_patch"}),
    ),
    "explore": Agent(
        name="explore",
        mode="subagent",
        description="Fast codebase exploration agent",
        permission=Permission(auto_approve={"read", "glob", "grep", "codesearch", "lsp"},
                            deny={"write", "edit", "bash", "spec_update*"}),
    ),
    "general": Agent(
        name="general",
        mode="subagent",
        description="General-purpose sub-agent for complex tasks",
        permission=Permission(auto_approve={"read", "glob", "grep", "edit", "write", "bash"}),
    ),
}
```

**Implementation**:
- [ ] Create `taui/tools/builtins/task.py` — the sub-agent launcher tool
- [ ] Create `taui/agent/agents.py` — agent definitions and config merging
- [ ] Modify `AgentRunner` to support child sessions
- [ ] Permission inheritance: minion agents cannot escalate beyond parent permissions
- [ ] Task resumption: pass `task_id` to continue an existing sub-agent session
- [ ] Result streaming: parent agent sees sub-agent's final summary
- [ ] Concurrency: optionally run multiple minion agents in parallel

**New files**:
- `taui/tools/builtins/task.py`
- `taui/agent/agents.py`

---

## Registry & Filtering Enhancements

### Provider-Aware Tool Selection

```python
# taui/tools/registry.py — enhanced

class ToolRegistry:
    def tools_for_context(
        self,
        *,
        provider_id: str | None = None,
        model_id: str | None = None,
        agent_name: str | None = None,
        categories: set[ToolCategory] | None = None,
    ) -> list[Tool]:
        """Return filtered tool list based on model, agent, and categories."""
        tools = list(self._tools.values())

        # Provider-specific filtering
        if provider_id and model_id:
            is_gpt = "gpt" in model_id
            tools = [t for t in tools if self._model_compatible(t, is_gpt)]

        # Agent permission filtering
        if agent_name:
            tools = [t for t in tools if self._agent_allowed(t, agent_name)]

        # Category filtering
        if categories:
            tools = [t for t in tools if getattr(t, 'category', None) in categories]

        return tools
```

### Dynamic Tool Registration

Support runtime tool registration (for programmatic tools, MCP, extensions):

```python
class ToolRegistry:
    def register_dynamic(self, tool: Tool, source: str = "dynamic") -> None:
        """Register a tool from an external source (MCP, extension, monty)."""
        tool.origin = f"dynamic:{source}"
        self._tools[tool.name] = tool

    def unregister_by_origin(self, origin_prefix: str) -> int:
        """Remove all tools matching an origin prefix."""
        to_remove = [n for n, t in self._tools.items() if t.origin.startswith(origin_prefix)]
        for name in to_remove:
            del self._tools[name]
        return len(to_remove)
```

---

## Implementation Priority & Phases

### Phase 1: Foundation (Week 1)
1. Enhance `ToolContext` with abort signal, metadata callback, session_id, agent_name
2. Add `ToolResult.attachments` field
3. Add `ToolCategory` enum and category-based filtering to registry
4. Add `define_tool()` convenience factory
5. Enhance `ReadTool` (directory listing, binary detection, 1-indexed, truncation)
6. Enhance `EditTool` (fuzzy matching chain)

### Phase 2: Search & Write (Week 2)
7. `CodeSearchTool` (wrapping symbols module)
8. `FindTool` (recursive file finder)
9. `ApplyPatchTool` (unified diff for GPT models)
10. `MultiEditTool` (batch edits)
11. Provider-aware tool selection in registry

### Phase 3: Git & Plan (Week 3)
12. `GitTool` (all git operations)
13. `TodoWriteTool` (structured task tracking)
14. `PlanTool` (plan file management)
15. `QuestionTool` (standalone, structured)

### Phase 4: Advanced (Week 4)
16. `LspTool` + `taui/lsp/` module
17. `SkillTool` + `taui/skills/` module
18. `TaskTool` (sub-agent launcher) + agent definitions
19. `MontyTool` (programmatic tool execution)

### Phase 5: Polish
20. Skill import/install system
21. Dynamic tool registration API
22. Agent tier system (prime/root/minion)
23. Batch tool (parallel tool execution in one turn)
24. RPC notifications for all new tools
25. Frontend integration for todos, plans, agent status

---

## File Structure (Final)

```
taui/
  tools/
    __init__.py              # exports
    base.py                  # Tool Protocol, ToolResult, ToolContext
    define.py                # define_tool() factory
    categories.py            # ToolCategory enum
    registry.py              # ToolRegistry with filtering
    executor.py              # ToolExecutor with outcomes
    builtins/
      __init__.py            # register_builtin_tools()
      _common.py             # shared helpers
      read.py                # enhanced ReadTool
      edit.py                # enhanced EditTool with fuzzy matching
      write.py               # WriteTool
      bash.py                # BashTool
      glob.py                # enhanced GlobTool
      grep.py                # enhanced GrepTool
      find.py                # NEW: FindTool
      codesearch.py          # NEW: CodeSearchTool (symbols)
      apply_patch.py         # NEW: ApplyPatchTool (unified diff)
      multiedit.py           # NEW: MultiEditTool
      fuzzy_match.py         # NEW: shared fuzzy matching
      git.py                 # NEW: GitTool
      todo.py                # NEW: TodoWriteTool
      plan.py                # NEW: PlanTool
      question.py            # NEW: QuestionTool
      lsp.py                 # NEW: LspTool
      skill.py               # NEW: SkillTool
      skill_import.py        # NEW: SkillImportTool
      task.py                # NEW: TaskTool (sub-agents)
      monty.py               # NEW: MontyTool (programmatic)
      monty_api.py           # NEW: Monty API helpers
      spec_tree.py           # existing spec tools
  lsp/
    __init__.py              # NEW module
    client.py                # LSP client
    manager.py               # Server lifecycle
    types.py                 # LSP types
  skills/
    __init__.py              # NEW module
    loader.py                # Skill discovery/loading
    registry.py              # Skill registry
    installer.py             # Install from git/pip
  agent/
    __init__.py
    agents.py                # NEW: Agent definitions & config
    manager.py               # AgentManager (enhanced)
    runner.py                # AgentRunner (enhanced)
    session.py               # Session
```

---

## Key Design Principles

1. **Protocol-first**: Every tool implements the `Tool` Protocol. No inheritance required.
2. **Factory pattern** (Pi-inspired): `define_tool()` for simple tools, dataclass for complex ones.
3. **Descriptions in files**: Long descriptions can live in `.md` or `.txt` files alongside implementations.
4. **Category-tagged**: Each tool declares its `ToolCategory` for agent-driven filtering.
5. **Provider-aware**: Registry can filter tools based on LLM provider/model.
6. **Permission-gated**: Write/execute tools go through policy evaluation. Read tools auto-approve.
7. **Independently testable**: Each tool is a standalone unit with no implicit dependencies.
8. **Composable**: Tools can call other tools via the API (MontyTool) or spawn sub-agents (TaskTool).
