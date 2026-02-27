# Copilot Provider Detailed Plan

## Objective
Add `taui/llm/providers/copilot.py` with parity to the provider protocol so model routing can support `copilot:*` identifiers.

## Scope
- `taui/llm/providers/copilot.py`
- Registry integration in `taui/llm/registry.py`

## Functional Requirements
- Must implement `Provider.complete(...)` async streaming API.
- Must emit standard `StreamEvent` types used by runtime.
- Must report capability support via `supports(...)`.
- Must be selectable by model prefix routing (`copilot:*`).

## Adapter Design
- Build provider-specific request/response translation layer.
- Normalize provider deltas into existing `text_delta` and tool-call events.
- Normalize errors to architecture-consistent `error` events.
- Reuse shared stream helpers where possible to reduce drift.

## Auth and Configuration
- Read Copilot auth/token source from configured provider settings.
- Validate auth availability at startup or first use with clear error text.
- Avoid leaking secrets in logs/errors.

## Capability Matrix
- Required parity with OpenAI path for:
  - text streaming
  - tool-calling support (if provider supports it)
  - cancellation
- If capability missing, `supports(...)` must return false and runtime should degrade gracefully.

## Error and Fallback Behavior
- Unsupported model name -> clear registry error.
- Provider temporary failure -> emit error event and allow retry at caller level.
- Capability mismatch -> fail fast before dispatch where possible.

## Test Plan
- Unit: registry routes `copilot:*` to Copilot provider.
- Unit: capability flags and unsupported capability handling.
- Integration: text-only streaming turn.
- Integration: tool-call turn (if supported by SDK).
- Integration: cancellation and transport error handling.

## Dependencies
- Depends on completed core provider protocol and stream event contracts.

## Exit Criteria
- `copilot:*` models can be selected and streamed.
- Event shapes are indistinguishable from other providers at runtime layer.
- Error and capability behavior is clearly documented and tested.
