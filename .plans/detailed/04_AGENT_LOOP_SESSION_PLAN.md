# Agent Loop and Session Detailed Plan

## Objective
Implement `taui.agent` as the orchestrator that runs think-act-observe cycles, executes tool calls, persists session state, and emits a unified event stream for all interfaces.

## Scope
- `taui/agent/loop.py`
- `taui/agent/session.py`
- `taui/agent/events.py`

## Runtime Contract
- Agent loop consumes `Session`, `Provider`, `ToolRegistry`, and `system_prompt`.
- Provider stream is the only source of model output events.
- Tool calls are executed through tools executor (with approval handshake when required), then appended as tool messages.
- Loop terminates when last assistant turn has no tool calls.

## `taui/agent/events.py` Plan
- Define typed events for:
  - `TextDelta`
  - `ToolStart`
  - `ToolEnd`
  - `ApprovalRequired`
  - `ApprovalResolved`
  - `TurnComplete`
  - `Error`
  - `Done`
- Include correlation fields (`turn_id`, `tool_call_id`) for traceability.
- Keep payloads minimal and interface-neutral.

## `taui/agent/session.py` Plan
- Maintain ordered message history for provider requests.
- Track read attempts for read-before-edit/write guard integration, including per-path status (`success`, `missing`).
- Persist sessions under `~/.local/share/taui/sessions/`.
- Track token usage budget and cumulative usage per session.
- Include version field in persistence schema for migration safety.

## Token Budget Strategy
- Define budget controls: `max_input_tokens`, `max_output_tokens`, and `reserved_output_tokens`.
- Apply soft limit compaction at 85 percent of input budget by dropping oldest non-system turns first.
- Apply hard limit strategy at 95 percent by inserting a deterministic summary message and trimming again.
- Preserve these message classes during compaction: latest system prompt, most recent user turn, unresolved tool call/result pairs.
- If request still cannot fit after compaction, emit explicit `Error` event and terminate turn safely.

## `taui/agent/loop.py` Plan
- Main cycle:
  1) Request completion from provider with current messages and schemas.
  2) Stream text/tool events to consumers immediately.
  3) For each completed tool call, request executor outcome.
  4) If outcome is `approval_required`, emit `ApprovalRequired` and wait for interface decision.
  5) Emit `ApprovalResolved`, then execute or deny based on decision.
  6) Append tool result message to session.
  7) Repeat until no new tool calls in last model turn.
- Ensure cancellation safely unwinds provider stream and running tool task.
- Emit terminal `Done` event after successful completion.

## Tool Handling Details
- Tool execution should happen after `tool_call_done` emission.
- Multiple tool calls in one turn can run sequentially initially; document future parallel option.
- Always preserve tool call ids when appending tool messages.
- On tool failure, continue turn unless policy requires hard stop.
- Approval decisions must be idempotent and correlated to a single pending tool call id.

## Session Persistence Details
- Persistence format: JSON file per session at `~/.local/share/taui/sessions/<session_id>.json`.
- Required top-level fields: `schema_version`, `session_id`, `messages`, `read_attempts`, `usage`, `timestamps`.
- Save on turn completion and explicit checkpoints using atomic write (`tmp` file then rename).
- Use advisory lock file (`<session_id>.lock`) to avoid concurrent writer corruption.
- Load should reconstruct messages, read attempts, usage counters, and metadata.
- Corrupt session files should produce recoverable errors and optional fallback to new session.

## Error Handling
- Provider errors become `Error` events plus safe loop termination.
- Executor errors are represented as tool result errors and continue unless fatal.
- Persistence failures are surfaced but should not crash live stream unless unrecoverable.
- Lock acquisition timeout and stale lock scenarios return clear recovery guidance.

## Test Plan
- Unit: event dataclass construction and serialization.
- Unit: session message append/read-attempt tracking/persistence round-trip.
- Unit: loop break condition when no tool calls.
- Unit: token compaction and hard-limit summarization behavior.
- Unit: approval-required and approval-resolved event sequencing.
- Integration: one turn with tool call and reinjected result.
- Integration: cancellation during provider stream and during tool execution.
- Integration: token budget threshold handling.
- Integration: concurrent session save attempts respect lock and atomic write guarantees.

## Dependencies
- Depends on `llm` provider contracts and tools executor.
- Consumed by both `cli.py` and `app.py` without interface-specific branching.

## Exit Criteria
- Loop can execute multi-turn tool workflows deterministically.
- Session persistence round-trip is stable.
- Event stream supports both interface modes with no adapter translation.
