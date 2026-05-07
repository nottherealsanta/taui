# LLM Provider System

## Status

Two providers implemented and tested. All 6 probe tests pass for both.

| Provider | Default Model | Wire Format | Tests |
|---|---|---|---|
| **Copilot** | `claude-sonnet-4.5` | Chat Completions | 6/6 pass |
| **Codex** | `gpt-5.3-codex` | Responses API | 6/6 pass |

### Model Names (verified working)

**Copilot** (via `models.dev/api.json` github-copilot):
- `claude-sonnet-4.5`, `claude-sonnet-4.6`, `claude-opus-4.5`, `claude-opus-4.6`, `claude-opus-4.7`, `claude-opus-41`
- `gpt-4.1`, `gpt-4o`, `gpt-5`, `gpt-5-mini`, `gpt-5.1`, `gpt-5.2`, `gpt-5.4`
- `gemini-2.5-pro`, `gemini-3-flash-preview`, `gemini-3-pro-preview`
- `grok-code-fast-1`

**Codex** (ChatGPT OAuth account — restricted set, most older models rejected):
- `gpt-5.3-codex` — only model confirmed working with ChatGPT account
- Other codex models (`gpt-5.1-codex`, `gpt-5.2-codex`) rejected with "not supported when using Codex with a ChatGPT account"
- Model availability depends on plan tier; OpenAI API key accounts get broader access

---

## File Layout

```
taui/llm_provider/
├── __init__.py              # package docstring
├── types.py                 # shared types: StreamEvent, ProviderTurnResult, ProviderCapabilities, etc
├── base.py                  # BaseLLMProvider ABC: retry, SSE parsing, error classification
├── config.py                # TOML config persistence (~/.config/taui/config.toml)
├── provider_probe.py        # interactive test runner (python -m taui.llm_provider.provider_probe)
├── README.md                # usage docs
├── auth/
│   ├── __init__.py          # re-exports: get_credentials(), CopilotCredentials, CodexCredentials
│   ├── pkce.py              # shared PKCE: generate_pkce(), wait_for_callback(), race_callback_or_paste()
│   ├── copilot.py           # GitHub device flow auth
│   └── codex.py             # OpenAI PKCE OAuth auth
└── providers/
    ├── __init__.py           # re-exports: CopilotProvider, CodexProvider
    ├── copilot.py            # CopilotProvider (Chat Completions)
    └── codex.py              # CodexProvider (Responses API)
```

---

## types.py — Shared Types

The contract between providers and the agent loop. Providers produce these types; the agent loop only consumes them.

### ApiFormat

```python
ApiFormat = Literal["chat_completions", "responses", "messages", "genai"]
```

Only `chat_completions` and `responses` are active. `messages` (Anthropic) and `genai` (Gemini) are forward declarations.

### ReasoningFormat

```python
class ReasoningFormat(str, Enum):
    NONE = "none"
    OPAQUE = "opaque"          # Copilot: reasoning_opaque + reasoning_text in deltas
    ENCRYPTED = "encrypted"    # Codex: reasoning.encrypted_content
    EFFORT_LEVELS = "effort_levels"   # (future) OpenAI direct
    THINKING_BLOCKS = "thinking_blocks"  # (future) Anthropic
    THOUGHT_PARTS = "thought_parts"      # (future) Gemini
```

Only `OPAQUE` and `ENCRYPTED` are active.

### ToolIdFormat + normalize_tool_call_id

**DEAD CODE.** `normalize_tool_call_id()` has zero call sites. `_TOOL_ID_MAX_LENGTHS` maps each format to max length but nothing reads it. `ToolIdFormat` enum is set on capabilities but never branched on.

opencode handles this with per-provider inline `scrub` functions in `transform.ts`. pi-mono doesn't normalize at all.

**Decision:** Remove `normalize_tool_call_id`, `_TOOL_ID_MAX_LENGTHS`, and `ToolIdFormat`. If we hit an actual ID mismatch when adding a provider, add a per-provider scrub then.

### StreamEvent

8 event types with factory methods. This is the core streaming abstraction — all providers emit these, the agent loop consumes them uniformly.

```python
StreamEventType = Literal[
    "text_delta", "reasoning_delta",
    "tool_call_start", "tool_call_delta", "tool_call_done",
    "usage", "done", "error",
]
```

Tool call streaming differs by wire format:
- **Chat Completions**: `tool_call_start` + N × `tool_call_delta` + finalized in `_accumulate_turn` (base class)
- **Responses API**: single `tool_call_done` with complete arguments (no streaming)

### Usage

Token counts per turn. `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens` fields exist but are never populated by either provider currently. `cost_usd` field exists but is never set.

### ProviderToolCall

```python
@dataclass(slots=True)
class ProviderToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]
```

Has two serialization methods:
- `to_chat_completions_format()` — used by probe's tool_roundtrip test
- `to_responses_format()` — unused currently

### ProviderTurnResult

```python
@dataclass(slots=True)
class ProviderTurnResult:
    response_id: str | None    # always None currently (never set in _accumulate_turn)
    text: str
    tool_calls: list[ProviderToolCall]
    usage: Usage | None
    assistant_metadata: dict[str, Any] | None   # reasoning_text, token counts
    stop_reason: str           # "stop" | "tool_use"
```

`response_id` is declared but never populated — `_accumulate_turn` initializes it as `None` and never writes to it. Codex's `response.completed` event has a response ID but `parse_stream_event` doesn't extract it.

### ProviderCapabilities

```python
@dataclass(frozen=True)
class ProviderCapabilities:
    supports_tools: bool               # ✓ checked by probe tests
    supports_streaming: bool           # ✓ always True, never checked
    supports_reasoning: bool           # ✓ checked by probe reasoning test
    supports_images: bool              # set but never checked
    supports_cache_control: bool       # set but never checked
    supports_response_id: bool         # set but never checked
    supports_developer_role: bool      # DEAD — for future OpenAI reasoning models
    reasoning_format: ReasoningFormat  # ✓ reported in probe
    tool_call_id_format: ToolIdFormat  # DEAD — nothing branches on it
    requires_streaming_for_tools: bool # set but never checked (Copilot quirk)
    requires_tool_result_name: bool    # DEAD — for future Anthropic
    requires_assistant_after_tool_result: bool  # DEAD — for future Anthropic
    supports_parallel_tool_calls: bool # ✓ checked by probe multi_tool test
    supports_strict_tool_schema: bool  # DEAD — for future OpenAI strict mode
```

**Actually checked at runtime:** `supports_tools`, `supports_reasoning`, `supports_parallel_tool_calls`
**Reported but not branched on:** `reasoning_format`, `tool_call_id_format`, `requires_streaming_for_tools`
**Dead (set to False, never read):** `supports_developer_role`, `requires_tool_result_name`, `requires_assistant_after_tool_result`, `supports_strict_tool_schema`

**Decision:** Remove dead capability flags. Keep forward-declared ones only when we add the provider that needs them.

### Cost Tracking

`estimate_cost_usd()` and `_PRICING` table have zero call sites. The archive had cost tracking in `agent/cost_tracker.py`, not in provider types. Pricing table is stale (old model names, missing current models).

**Decision:** Remove from types.py. Cost tracking belongs in the agent layer, not provider types.

---

## base.py — BaseLLMProvider

### Abstract Interface

4 abstract methods + 2 optional overrides:

| Method | Required | Purpose |
|---|---|---|
| `capabilities` (property) | ✓ | Declare provider capabilities |
| `build_request()` | ✓ | Build HTTP request descriptor |
| `parse_stream_event()` | ✓ | Parse one SSE line → StreamEvent |
| `refresh_credentials()` | ✓ | Token refresh before each request |
| `convert_tools()` | optional | Convert tool schemas (default: passthrough) |
| `convert_messages()` | optional | Convert messages (default: passthrough) |

`convert_messages()` is declared but **never called** by the base class. Codex uses its own private `_convert_messages()` inside `build_request()`. The base `create_turn()` passes raw messages to `build_request()`.

**Decision:** Remove `convert_messages()` from base class. Providers that need message conversion do it privately in `build_request()`.

### High-Level API

Two entry points:
- `create_turn()` — full turn with retry, tool accumulation, reasoning capture. Primary API.
- `stream_text()` — simple text streaming, no tool accumulation. Not used by any caller currently.

`create_turn()` accepts `thinking_level` param but **never applies it** to the request. It's threaded through to `build_request()` via `**kwargs` but neither provider's `build_request()` uses it.

**Decision:** Remove `thinking_level` from base `create_turn()`. Add it back per-provider when reasoning effort is actually wired in.

### Error Classification

Three classifiers, all overridable:

| Method | Patterns | Action |
|---|---|---|
| `is_context_overflow()` | 14 regex patterns across all known providers | Fail immediately |
| `is_usage_limit()` | 5 patterns, requires status 429 | Fail immediately with reset time |
| `is_retryable()` | Status {429, 500, 502, 503, 504} + 6 body patterns | Retry |

The overflow patterns cover providers we don't have yet (Anthropic "prompt is too long", Bedrock, Gemini). This is fine — the patterns are cheap and defensive.

### Retry Logic

```
MAX_RETRIES = 3
BASE_RETRY_DELAY = 1.0s
MAX_SERVER_DELAY = 60.0s

Loop: attempt 0..3
  → PermissionError (401): never retry
  → context overflow: fail immediately
  → usage limit: fail immediately
  → not retryable: raise RuntimeError with body[:1000]
  → retryable: compute delay, sleep, retry
  → transport/OS error: exponential backoff, retry
```

Retry delay resolution order:
1. `Retry-After` header
2. `x-ratelimit-reset` header (Unix timestamp)
3. `x-ratelimit-reset-after` header (seconds)
4. Body patterns: `"retry in Ns"`, `"retryDelay": "Ns"`
5. Exponential backoff: `1.0 * 2^attempt`

If server requests > 60s delay, fail immediately.

### SSE Streaming

`_do_stream()` handles the HTTP connection and SSE parsing:
- Opens `httpx.AsyncClient` with 120s timeout
- 401 → `PermissionError`
- 400+ → read body, `raise_for_status()` (triggers retry classification)
- Parse `data: ` prefix lines, stop on `[DONE]`
- Each line → `parse_stream_event()` → yield `StreamEvent`

### Tool Call Accumulation

`_accumulate_turn()` collects the full turn from the stream:
- Text deltas → concatenated
- Reasoning deltas → concatenated, stored in `assistant_metadata["reasoning_text"]`
- Tool calls: two paths:
  - **Streaming** (Chat Completions): `tool_call_start` creates `_ToolCallAccumulator`, `tool_call_delta` appends argument JSON, finalized after stream ends
  - **Complete** (Responses API): `tool_call_done` adds directly to `completed_tool_calls`
- Both paths merge into final `ProviderTurnResult.tool_calls`

`response_id` is initialized as `None` but never written to. Should be populated from Codex `response.completed` event.

---

## providers/copilot.py — CopilotProvider

### Wire Format

OpenAI Chat Completions (`/chat/completions`) via GitHub's proxy.

### URL Resolution

Base URL derived from the Copilot token's `proxy-ep` field:
```
token contains: proxy-ep=proxy.individual.githubcopilot.com
→ replace proxy. with api.
→ https://api.individual.githubcopilot.com
```

Enterprise: `https://copilot-api.{enterprise_domain}`
Fallback: `https://api.individual.githubcopilot.com`

### Headers

Two header sets:
- **Standard** (`COPILOT_HEADERS`): `Copilot-Integration-Id: vscode-chat`
- **Agent** (`COPILOT_AGENT_HEADERS`): `Copilot-Integration-Id: copilot-chat`

Agent headers used when tools are present. Also varies:
- `Openai-Intent: conversation-panel` (with tools)
- `Openai-Intent: conversation-edits` (without tools)

### Model Fallback

`create_turn()` overrides base to handle enterprise model name fallback:
- If model contains `/` (e.g., `enterprise/claude-sonnet-4`), try full name first
- On 400 with `model_not_supported` in body, retry with stripped name
- Catches both `httpx.HTTPStatusError` and `RuntimeError` (base class wraps 400s as RuntimeError)

### Stream Parsing

Parses `choices[0].delta`:
- `delta.content` → `text_delta`
- `delta.reasoning_text` → `reasoning_delta`
- `delta.tool_calls[0]` with `.id` + `.function.name` → `tool_call_start`
- `delta.tool_calls[0].function.arguments` → `tool_call_delta`

Does NOT capture `delta.reasoning_opaque` — this is encrypted reasoning needed for multi-turn replay. **Known gap.**

---

## providers/codex.py — CodexProvider

### Wire Format

OpenAI Responses API at `https://chatgpt.com/backend-api/codex/responses`.

### Message Conversion

`_convert_messages()` converts Chat Completions format to Responses API:
- `role: system` → extracted to top-level `instructions` field
- `role: user` → `{role: "user", content: [{type: "input_text", text: ...}]}`
- `role: assistant` with content → `{role: "assistant", content: [{type: "output_text", text: ...}]}`
- `role: assistant` with `tool_calls` → emits `{type: "function_call", call_id, name, arguments}` items
- `role: tool` → `{type: "function_call_output", call_id, output}`

The assistant→function_call conversion was a bug fix: without it, `tool_roundtrip` test failed because the Responses API couldn't match `function_call_output` to its originating call.

### Tool Schema Normalization

`_normalize_tools()` flattens Chat Completions tool format:
```
{type: "function", function: {name, description, parameters}}
→ {type: "function", name, description, parameters}
```

### Request Body

```python
{
    "model": model,
    "stream": True,
    "store": False,
    "input": input_items,
    "instructions": system_prompt,
    "text": {"verbosity": "medium"},
    "tools": normalized_tools,
    "tool_choice": "auto",
    "parallel_tool_calls": False,
    "include": ["reasoning.encrypted_content"],
}
```

Headers include `chatgpt-account-id` (extracted from JWT during auth) and `OpenAI-Beta: responses=experimental`.

### Stream Parsing

Event-type based:
- `response.output_text.delta` → `text_delta`
- `response.output_item.done` with `function_call` item → `tool_call_done` (complete, not streamed)
- `response.completed` → `usage_event` (extracts `input_tokens`, `output_tokens`)
- `error` with `usage_limit_reached` code → `RuntimeError` with reset time

Does NOT extract `response_id` from `response.completed`. **Known gap.**

---

## provider_probe.py — Test Runner

Run: `python -m taui.llm_provider.provider_probe copilot`

### Tests

| Test | What it does |
|---|---|
| `capabilities` | Reports declared capabilities (always passes) |
| `streaming` | "What is 2+2?" — verifies non-empty text response |
| `tools` | "Weather in SF?" with `get_weather` tool — verifies tool call with location arg |
| `multi_tool` | "Weather in SF and NY?" — verifies 2+ parallel tool calls (skipped if not supported) |
| `reasoning` | Math problem with `thinking_level="medium"` — checks if reasoning captured |
| `tool_roundtrip` | Two-turn: get tool call → send result → verify text response |

### Default Models

```python
copilot → "claude-sonnet-4.5"
codex   → "gpt-5.3-codex"
```

### Command Line

```
python -m taui.llm_provider.provider_probe <provider> [--model MODEL] [--test TEST] [-v]
```

---

## config.py — TOML Persistence

Config file: `~/.config/taui/config.toml`

```toml
[providers.copilot]
api_key = "ghu_..."          # long-lived GitHub OAuth token

[providers.codex]
refresh_token = "rt_..."     # long-lived refresh token
account_id = "cf995405-..."  # chatgpt_account_id from JWT
```

Uses `tomllib` (stdlib) for reading, custom `_dict_to_toml()` for writing. The custom serializer handles strings, ints, bools, lists, and nested dicts. No third-party TOML writer dependency.

---

## Known Gaps

1. **`response_id` never populated** — `_accumulate_turn` initializes it as `None`, Codex's `response.completed` has the ID but `parse_stream_event` doesn't extract it. Needed for `previous_response_id` multi-turn.

2. **Copilot `reasoning_opaque` not captured** — `parse_stream_event` captures `reasoning_text` but not `reasoning_opaque`. The opaque field is encrypted and needed for multi-turn reasoning replay. Without it, reasoning context is lost between turns.

3. **`thinking_level` is a no-op** — accepted in `create_turn()` but neither provider applies it to the request body. Copilot reasoning is automatic (no knob). Codex could use `reasoning_effort` but doesn't.

4. **Reasoning test shows `[NO REASONING CAPTURED]`** — both providers pass the reasoning test but show no captured reasoning. Copilot claude-sonnet-4.5 may not emit `reasoning_text` deltas for simple prompts. Codex returns encrypted reasoning in `response.completed` but we don't parse it.

5. **Codex model availability** — with ChatGPT OAuth, most models are rejected. Only `gpt-5.3-codex` confirmed working. API key auth would give broader access.

---

## Cleanup Backlog

Items to remove (zero call sites, over-engineered for current state):

| Item | Location | Reason |
|---|---|---|
| `normalize_tool_call_id()` | types.py:68 | Zero call sites. Add per-provider scrub when needed. |
| `_TOOL_ID_MAX_LENGTHS` | types.py:59 | Only used by dead normalize function. |
| `ToolIdFormat` enum | types.py:52 | Set on capabilities but never branched on. |
| `estimate_cost_usd()` + `_PRICING` | types.py:281-315 | Zero call sites. Cost tracking belongs in agent layer. |
| `supports_developer_role` | types.py:251 | For future OpenAI reasoning models. |
| `requires_tool_result_name` | types.py:258 | For future Anthropic. |
| `requires_assistant_after_tool_result` | types.py:259 | For future Anthropic. |
| `supports_strict_tool_schema` | types.py:261 | For future OpenAI strict mode. |
| `convert_messages()` on base | base.py:152 | Never called. Codex uses private method. |
| `thinking_level` param | base.py:189 | Threaded through but never applied. |
| `ThinkingLevel` type alias | types.py:47 | Only used by dead thinking_level param. |

Keeping:
- `ReasoningFormat` enum — two values active, others harmless
- `ApiFormat` — same
- `assistant_metadata` dict — works as catch-all for reasoning replay
- All of `base.py` infrastructure (retry, SSE, error classification)
- Both providers, both auth modules, config, probe

---

## Reference Projects

### opencode (TypeScript, /tmp/opencode/)

- Copilot Responses API provider at `packages/opencode/src/provider/sdk/copilot/responses/`
- Codex plugin at `packages/opencode/src/plugin/codex.ts`
  - Same `CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"`
  - Same `CODEX_API_ENDPOINT = "https://chatgpt.com/backend-api/codex/responses"`
  - Allowed Codex models: `gpt-5.1-codex`, `gpt-5.1-codex-max`, `gpt-5.1-codex-mini`, `gpt-5.2`, `gpt-5.2-codex`, `gpt-5.3-codex`, `gpt-5.4`, `gpt-5.4-mini`
- Tool ID scrub is per-provider in `transform.ts`:
  - Claude: `id.replace(/[^a-zA-Z0-9_-]/g, "_")`
  - Mistral: strip to alphanumeric, truncate to 9, pad with zeros
- `ProviderCapabilities` is minimal: `temperature`, `reasoning`, `attachment`, `toolcall`, `input`/`output` modalities
- No `ToolIdFormat`, no `max_tool_call_id_length`, no `normalize_tool_call_id`

### pi-mono (TypeScript, /tmp/pi-mono/)

- No tool call ID normalization at all — passes IDs through opaquely
- No `ProviderCapabilities` struct — ad-hoc checks
- Tools receive `toolCallId` as a parameter but don't transform it
- Thinking level clamped to model capabilities in `agent-session.ts`

### Archive (Python, /Users/santa/repos/taui/archive/)

- `taui/llms/codex.py` — same `BASE_URL = "https://chatgpt.com/backend-api"`, same endpoint
- `taui/llms/__init__.py` — `DEFAULT_MODELS = {"copilot": "claude-sonnet-4.6"}`, no codex default
- `taui/config/settings.py` — model default: `"copilot:claude-sonnet-4.6"`
- `taui/agent/cost_tracker.py` — cost tracking in agent layer, not provider types
- Copilot/Codex auth in `taui/auth/`, same patterns as current implementation
