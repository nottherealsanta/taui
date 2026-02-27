# Textual TUI Integration Detailed Plan

## Objective
Integrate `taui/app.py` with the same core agent event stream used by CLI, while providing a responsive and safe interaction model for tool-using conversations.

## Scope
- `taui/app.py`
- Any TUI-local view/state helpers required by Textual integration

## UX Principles
- Preserve architecture parity: TUI is a consumer, not an alternate runtime.
- Prioritize stream visibility (tokens and tool actions) over post-hoc snapshots.
- Keep approval flows explicit for confirm-gated tools.

## Core UI Regions (Initial)
- Conversation panel for user and assistant messages.
- Streaming panel for token deltas during active turn.
- Tool activity panel for start/end results and errors.
- Input composer with submit and cancel controls.
- Optional status/footer for model, session id, token usage.

## Event Mapping Plan
- `TextDelta` -> append to active assistant message bubble.
- `ToolStart` -> add pending row in tool activity panel.
- `ToolEnd` -> finalize row with success/error state and summary.
- `ApprovalRequired` -> open approval modal with tool name, arguments preview, and policy reason.
- `ApprovalResolved` -> update tool row state (`approved` or `denied`) before execution/result handling.
- `Error` -> show non-blocking error banner plus transcript entry.
- `TurnComplete`/`Done` -> close streaming state and re-enable input.

## Interaction Flows
- User submits prompt -> app starts agent stream task.
- Confirm-required tool -> modal/dialog with approve/deny actions tied to the active `tool_call_id`.
- Cancel current turn -> propagate cancellation to running task.
- Session switch/load (post-MVP optional): maintain clear state boundary.

## Performance and Responsiveness
- Render stream updates incrementally without full transcript reflow.
- Throttle high-frequency deltas to avoid UI stutter.
- Ensure long tool output is truncated in panel with expandable detail.

## Error and Recovery
- Provider stream failure should keep app alive and input usable.
- Tool errors should appear inline without forcing session restart.
- Failed persistence should warn user and continue current in-memory turn.

## Test Plan
- Unit: event-to-view mapping for each event type.
- Unit: approval modal state transitions.
- Unit: stale approval response for old `tool_call_id` is ignored safely.
- Integration: full turn with at least one tool call.
- Integration: cancellation mid-stream.
- Integration: high-volume text delta stream handling.

## Dependencies
- Requires stable `agent/events.py` contracts.
- Requires policy integration for tool approvals.

## Exit Criteria
- TUI executes end-to-end turns with feature parity to CLI.
- Streaming and tool events are readable and reliable.
- Approval and cancellation flows are robust.
