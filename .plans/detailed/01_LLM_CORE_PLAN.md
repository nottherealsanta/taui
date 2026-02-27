# LLM Core Detailed Plan

## Objective
Implement `taui.llm` as a streaming-first, provider-agnostic primitive that can be consumed independently by other modules.

## Scope
- `taui/llm/types.py`
- `taui/llm/provider.py`
- `taui/llm/registry.py`
- `taui/llm/providers/openai.py`
- `taui/llm/stream.py`

## Contract Requirements
- `Message` supports `system`, `user`, `assistant`, `tool` roles.
- `ToolCall` carries stable `id`, `name`, and parsed `arguments`.
- `StreamEvent` supports exactly: `text_delta`, `tool_call_delta`, `tool_call_done`, `done`, `error`.
- `Usage` must include input/output token counts, optional cost.
- `Provider.complete(...)` returns `AsyncIterator[StreamEvent]`.

## File-by-File Plan

## `taui/llm/types.py`
- Define dataclasses for `Message`, `ToolCall`, `StreamEvent`, `Usage`.
- Add narrow helper constructors for common event emissions.
- Keep fields optional only where architecture requires it.
- Include serialization helpers for session persistence compatibility.

## `taui/llm/provider.py`
- Define `Provider` protocol exactly matching architecture method signature.
- Add capability constants for `tool_calling`, `vision`, `json_mode`.
- Provide optional base utilities for shared validation across providers.

## `taui/llm/registry.py`
- Route model ids by prefix (`openai:*`, `copilot:*`).
- Support registration and lookup with clear errors for unknown prefixes.
- Support default model fallback from settings layer (wired later).
- Expose helper to list available models/providers for diagnostics.

## `taui/llm/providers/openai.py`
- Implement adapter from OpenAI stream events to local `StreamEvent` dataclass.
- Normalize tool call fragments into final `tool_call_done` events.
- Capture and emit `Usage` at stream completion when available.
- Handle provider errors by emitting `error` then terminal `done` semantics.
- Preserve cancellation via native `asyncio` task cancellation.

## `taui/llm/stream.py`
- Add event assembly helpers for partial deltas.
- Add cancellation-safe wrappers for consumer shutdown.
- Add utility to collect stream into full response for tests and batch consumers.

## Implementation Tasks
- Create strict event mapping tests from provider payloads.
- Ensure tool call argument parsing is deterministic and JSON-safe.
- Validate message translation in both directions (internal <-> provider API).
- Add lightweight logging hooks for stream lifecycle events.

## Error Model
- Unknown model prefix: explicit `ValueError` with actionable message.
- Provider transport failure: emit `StreamEvent(type="error")` with details.
- Malformed tool arguments: emit error and avoid partial unsafe execution state.
- Unsupported capability requests: fail early before request dispatch.

## Test Plan
- Unit: dataclass construction and serialization.
- Unit: registry routing and unknown-prefix behavior.
- Unit: stream helper assembly for text and tool call deltas.
- Integration: OpenAI provider streaming text-only response.
- Integration: OpenAI provider tool-call response with complete argument object.
- Integration: cancellation during active stream does not deadlock.

## Dependencies
- None for initial implementation.
- Later integration dependency: settings for default model/provider config.

## Exit Criteria
- One canonical streaming path used by all consumers.
- OpenAI provider passes text + tool call + error + cancellation scenarios.
- Usage accounting available in stream completion events.
- Registry correctly routes at least `openai:*` and placeholder `copilot:*`.
