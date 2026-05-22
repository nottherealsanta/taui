# Plan: Fix Resume Tool Result Ordering

## Problem

After resuming a session and sending a new message, the provider can reject the
request with:

```text
messages.5: `tool_use` ids were found without `tool_result` blocks immediately after
```

The reported ID, for example `toolu_vrtx_01N8mSEz3EFdCXXw2feADVyW`, is an
Anthropic-style tool-use ID. That means the request history sent after resume
contains an assistant tool call whose matching tool result is missing, delayed,
or separated by another message. Anthropic requires every assistant `tool_use`
block to be answered by corresponding `tool_result` blocks in the immediately
following user message. Copilot's Claude proxy appears to enforce that invariant
even though Taui sends an OpenAI-compatible Chat Completions payload.

## Current Code Path

- `Session.resume_session()` rebuilds an `AgentLoop` for the saved stream:
  `taui/session.py:624`.
- `_replay_stream()` calls `StreamClient.load_conversation()` and installs the
  replayed messages into `loop._messages`: `taui/session.py:1168`.
- `StreamClient.load_conversation()` delegates to `replay_events()`:
  `taui/store/stream.py:92`.
- `replay_events()` converts persisted `ASSISTANT_MESSAGE`, `TOOL_CALL`, and
  `TOOL_RESULT` events into internal `Message` objects:
  `taui/session_replay.py:28`.
- On the next send, `AgentLoop._build_llm_messages()` serializes those internal
  messages into provider input: `taui/agent/loop.py:668`.

## Likely Root Cause

Replay is event-order driven and currently trusts the stored stream shape. It
will restore:

1. an assistant message with `tool_calls`, then
2. whatever events come next, including unrelated assistant/user/error/usage
   events, and
3. a tool result later if one exists.

That is not strong enough for provider request validation. The restored LLM
history must guarantee this invariant:

```text
assistant(tool_calls=[c1, c2, ...])
tool(tool_call_id=c1)
tool(tool_call_id=c2)
...
```

with no intervening user or assistant messages, and with every call represented
exactly once.

The code already reconstructs old streams that only contain `TOOL_CALL` /
`TOOL_RESULT` pairs, but it does not validate or repair malformed or partial
tool-call groups before a resumed request is sent.

## Investigation Steps

1. Add a failing regression test that reproduces the invalid resumed history.
   Build the stream manually in `tests/test_session.py` or
   `tests/test_resume_e2e.py` with an assistant `tool_calls` event followed by
   an intervening message before the matching `TOOL_RESULT`, then resume and
   inspect `session._loop.messages`.

2. Add a provider-facing assertion test using a mock provider that records the
   exact `messages` passed to `create_turn()`. The test should call
   `session.send("continue")` after resume and assert every assistant
   `tool_calls` message is immediately followed by matching `tool` messages.

3. Check real stored streams that triggered the bug, if available, by reading
   `.taui/store.db` events for the failing session and confirming the event
   order around the reported tool ID.

## Fix Strategy

1. Centralize history validation in `taui/session_replay.py`.
   Add a small helper such as `_normalize_tool_call_groups(messages)` that runs
   at the end of `replay_events()`.

2. For each assistant message with tool calls:
   - collect the required call IDs in assistant order;
   - look ahead only through contiguous tool messages;
   - keep matching tool messages directly after the assistant;
   - if matching results exist later in replay history, move them up into the
     required contiguous position;
   - if a result is missing, synthesize a tool message with an error-style
     content such as `Tool result was not recorded before session resume.`;
   - remove duplicate moved tool messages from their old location.

3. Preserve display replay separately from provider replay.
   `ReplayItem` ordering should continue to represent the stored event log for
   the TUI. Only `ReplayTranscript.messages` needs provider-safe normalization.

4. Add a defensive validator near request construction.
   A lightweight private helper in `AgentLoop._build_llm_messages()` can assert
   or repair the same invariant before provider serialization. This prevents
   future features, compaction, or external stream appends from reintroducing
   invalid tool history.

5. Keep the store append-only.
   Do not rewrite existing stream events. Resume should tolerate old and
   partially malformed sessions by normalizing the in-memory provider history.

## Test Plan

- Add unit tests for `replay_events()`:
  - modern stream with `ASSISTANT_MESSAGE.tool_calls` and immediate results;
  - legacy stream with only `TOOL_CALL` / `TOOL_RESULT`;
  - delayed tool result moved immediately after the assistant tool call;
  - missing tool result synthesized;
  - multiple parallel tool calls keep result order aligned to assistant call
    order.

- Add session-level regression coverage:
  - `resume_session()` restores provider-safe `loop.messages`;
  - `send()` after resume passes provider-safe history to a recording mock
    provider.

- Run focused checks:

```bash
uv run python -m pytest tests/test_session.py tests/test_resume_e2e.py -q
uv run python -m pytest tests/test_provider_scenarios.py -q
uv run ruff check .
```

## Acceptance Criteria

- Resuming any stored session cannot produce an assistant tool-call message
  without immediately following matching tool result messages.
- Existing replay rendering still shows the stored transcript in stream order.
- Legacy streams without `ASSISTANT_MESSAGE.tool_calls` still resume.
- Sending a new message after resume no longer triggers Anthropic/Copilot
  `tool_use` / `tool_result` ordering errors.
