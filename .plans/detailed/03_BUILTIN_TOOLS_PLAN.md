# Built-in Tools Detailed Plan

## Objective
Deliver the MVP built-ins (`read`, `edit`, `write`, `bash`, `glob`, `grep`) with consistent safety guarantees, clear schemas, and predictable errors.

## Scope
- `taui/tools/builtins/read.py`
- `taui/tools/builtins/edit.py`
- `taui/tools/builtins/write.py`
- `taui/tools/builtins/bash.py`
- `taui/tools/builtins/glob.py`
- `taui/tools/builtins/grep.py`

## Shared Implementation Rules
- Every tool returns `ToolResult` with user-readable `content`.
- All paths resolved relative to `ToolContext.working_dir` unless absolute.
- Reject path traversal outside allowed workspace when sandboxing is active.
- Populate metadata for key details (`path`, counts, elapsed time, truncation flags).
- Avoid binary/huge payload surprises by truncating output with explicit indicators.

## Guardrails
- Read-before-edit must be enforced in `edit` via session read tracking.
- Read-before-write must be enforced in `write` for all writes (overwrite and create).
- A prior `read` attempt on the same path counts as guard satisfaction, including a read that returned "file not found".
- `edit` must require exact `old_string` matches.
- `edit` must error on zero matches and configurable multi-match conflicts.

## Tool Specifications

## `read`
- Inputs: `filePath`, optional `offset`, optional `limit`.
- Behavior: read text safely, include line numbers, and track read-attempt status in session (`success` or `missing`).
- Errors: file missing, permissions, binary decode issues.
- Tests: normal read, offset/limit read, missing file error, large file truncation.

## `edit`
- Inputs: `filePath`, `old_string`, `new_string`, optional replacement mode.
- Behavior: enforce read guard, perform exact replacement, return replacement count.
- Errors: not previously read, no match, ambiguous matches (if mode disallows).
- Tests: successful single replacement, no-match error, read-guard error, multi-match conflict.

## `write`
- Inputs: `filePath`, `content`, optional `create_if_missing`.
- Behavior: overwrite file content atomically where possible.
- Guard: require prior read attempt for target path; creating a new file requires `create_if_missing=true` and a prior missing-file read attempt.
- Tests: overwrite after read, blocked overwrite without read, create-new success after missing-file read, blocked create without prior read attempt.

## `bash`
- Inputs: `command`, optional `timeout`, optional `workdir`.
- Behavior: execute command with timeout and captured stdout/stderr.
- Safety:
  - policy-confirm by default
  - restrict execution `workdir` to workspace root or its descendants
  - run with an environment allowlist and no shell profile loading
  - enforce max output bytes with truncation marker metadata
  - terminate process group on timeout/cancellation to avoid orphaned jobs
  - route network allowance through policy/config (default explicit and documented)
- Tests: success, timeout, non-zero exit, workdir override, out-of-workspace rejection, output truncation, cancellation kills child process tree.

## `glob`
- Inputs: `pattern`, optional `path`.
- Behavior: return matched file paths, stable ordering, workspace-aware path normalization.
- Tests: basic match, recursive match, no match.

## `grep`
- Inputs: `pattern`, optional `path`, optional `include`.
- Behavior: regex search with file and line references.
- Tests: single file match, multi-file match, invalid regex error.

## Consistency Requirements
- Tool content format should be concise and machine/LLM parsable.
- Error messages must explain what failed and how to recover.
- Metadata keys should be stable across versions.

## Integration Plan
- Register all built-ins through one helper in `tools/builtins/__init__.py`.
- Validate exported schemas before runtime startup.
- Add smoke test that calls each built-in through executor.

## Exit Criteria
- All six tools executable via registry and executor.
- Read/edit/write guards behave exactly as specified.
- CLI and TUI can display tool outputs without special-case parsing.
