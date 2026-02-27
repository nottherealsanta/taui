# Tools Core Detailed Plan

## Objective
Implement `taui.tools` as a safe, schema-driven execution layer that normalizes tool behavior and policy enforcement.

## Scope
- `taui/tools/base.py`
- `taui/tools/registry.py`
- `taui/tools/executor.py`

## Contract Requirements
- `Tool` exposes `name`, `description`, `schema`, and async `execute(...)`.
- `ToolResult` returns `content`, `error` flag, and optional metadata.
- `ToolContext` always includes `working_dir`, `session`, `policy`.
- Execution path must include validation, policy check, approval handshake, timeout, and error normalization.

## `taui/tools/base.py` Plan
- Define protocol and dataclasses exactly matching architecture.
- Add type aliases for schema and executor return types.
- Keep result payload text-first for consistent LLM reinjection.
- Include helper constructors for common success/error results.

## `taui/tools/registry.py` Plan
- Provide registration API with duplicate-name protection.
- Implement lookup by tool name with clear missing-tool errors.
- Export provider-facing schema list for tool-calling requests.
- Support built-in registration helper for startup wiring.

## `taui/tools/executor.py` Plan
- Pipeline order:
  1) Resolve tool from registry.
  2) Validate arguments against schema.
  3) Evaluate policy (`deny` -> `confirm` -> `auto_approve`).
  4) If `confirm`, emit approval-required outcome and pause execution.
  5) Execute with timeout wrapper after approval (or immediately if auto-approved).
  6) Normalize result and emit tool events.
- Catch unexpected exceptions and convert to `ToolResult(error=True)`.
- Include per-tool timeout defaults with optional override.
- Attach metadata (`duration_ms`, `tool_name`, `arguments_digest`).

## Approval Handshake Contract
- Executor returns a typed outcome state: `completed`, `approval_required`, or `denied`.
- `approval_required` outcome must include stable payload fields: `tool_call_id`, `tool_name`, `arguments_preview`, `reason`.
- Agent loop drives approval resolution and calls executor resume path with `approved=true|false`.
- Denied-at-approval path must emit deterministic user-visible reason and never run tool side effects.

## Policy Integration Requirements
- Central policy object handles allow/confirm/deny decisions.
- Executor must be the only enforcement point for runtime tool calls.
- Confirm-required outcome must be represented in event flow for CLI/TUI.
- Denied actions return explicit, user-visible reason.

## Error Normalization
- Validation failure -> structured error text with field-level hints.
- Tool missing -> deterministic error text, no stack trace leakage.
- Timeout -> clear timeout message and elapsed value.
- Runtime exception -> generic safe message + diagnostic metadata for logs.

## Observability Requirements
- Emit start/end events with stable correlation id (tool call id).
- Record elapsed time and result status.
- Maintain event shape compatibility with `agent/events.py`.

## Test Plan
- Unit: registry register/list/duplicate/missing lookup.
- Unit: schema validation pass/fail behavior.
- Unit: policy decision branches (allow, confirm, deny).
- Unit: approval-required outcome shape and resume behavior.
- Unit: approval denied after confirm returns no side effects.
- Unit: timeout handling and exception normalization.
- Integration: executor running a fake tool through full pipeline.
- Integration: metadata fields populated consistently.

## Dependencies
- Depends on policy object contract from `config/policies.py`.
- Depends on session object contract for read guards used by built-ins.

## Exit Criteria
- Any tool can be executed through one deterministic executor pathway.
- All errors returned as `ToolResult` without uncaught exceptions.
- Policy outcomes observable and enforceable by interfaces.
- Schema export works for LLM provider tool declarations.
