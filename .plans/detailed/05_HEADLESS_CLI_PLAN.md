# Headless CLI Detailed Plan

## Objective
Implement `taui/cli.py` as a script-friendly interface over the shared agent runtime, supporting stdin/stdout operation and streaming output.

## Scope
- `taui/cli.py`
- CLI wiring in `taui/__main__.py` as needed

## Usage Targets
- Interactive prompt mode in terminal.
- Single-shot mode from pipe or argument.
- Deterministic output mode suitable for automation scripts.

## Command Surface (Initial)
- `taui` reads prompt from stdin when piped, otherwise from arguments/interactive input.
- Optional flags (planned):
  - `--model`
  - `--no-tools`
  - `--json-events`
  - `--session <id>`
  - `--cwd <path>`

## Runtime Integration
- Construct session + provider + tool registry from config.
- Call shared `agent.run(...)` and consume `AgentEvent` stream.
- Print `TextDelta` immediately to stdout.
- Print tool lifecycle lines (`ToolStart`, `ToolEnd`) in compact form.
- Handle `ApprovalRequired` by prompting user in interactive mode and emitting `ApprovalResolved` decisions.

## Output and Exit Code Rules
- `0`: successful turn completion.
- `1`: runtime or provider error.
- `2`: policy denied action requiring failure exit.
- `130`: user cancellation (Ctrl-C).
- In `--json-events` mode, emit one JSON object per line with stable schema.

## Interaction Rules
- Keep prompts minimal and non-verbose.
- For confirm-required tools, show tool name, arguments preview, and prompt once.
- In non-interactive mode, treat `ApprovalRequired` as denied unless explicit auto-approve policy allows execution.
- For denied tools, print reason and continue or stop based on policy mode.

## Failure Handling
- Handle broken pipe gracefully in non-interactive mode.
- Handle provider unavailable errors with concise actionable text.
- Ensure partial stream output does not corrupt JSON events mode.

## Test Plan
- Unit: argument parsing and mode selection.
- Unit: exit code mapping for major failure classes.
- Integration: stdin pipe single-shot query.
- Integration: tool call requiring confirmation.
- Integration: non-interactive approval-required tool returns deterministic denial path.
- Integration: `--json-events` schema and ordering validation.
- Integration: Ctrl-C cancellation behavior.

## Dependencies
- Depends on completed `agent`, `llm`, `tools`, and `config` modules.

## Exit Criteria
- CLI can run full turn with streaming and tool calls.
- Script mode is deterministic and machine-readable.
- Confirmation and error handling are clear and stable.
