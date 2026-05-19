# Providers

Providers convert Taui messages and tools into provider-specific HTTP requests, then
convert stream responses back into shared `StreamEvent` objects.

## Shared Contract

- Base provider API: `taui/llm_provider/base.py:102`
- Request builder hook: `taui/llm_provider/base.py:127`
- SSE parser hook: `taui/llm_provider/base.py:140`
- Turn creation and retry loop: `taui/llm_provider/base.py:192`
- Shared stream/result types: `taui/llm_provider/types.py:151`,
  `taui/llm_provider/types.py:212`
- Capability dataclass: `taui/llm_provider/types.py:236`

`AgentLoop` consumes the shared provider result and does not branch on provider names:
`taui/agent/loop.py:304`.

## Builtins

| Provider | Code | Auth |
| --- | --- | --- |
| GitHub Copilot | `taui/llm_provider/providers/copilot.py:33` | `taui/llm_provider/auth/copilot.py:214` |
| OpenAI Codex | `taui/llm_provider/providers/codex.py:26` | `taui/llm_provider/auth/codex.py:63` |

Both providers implement `capabilities()`, `build_request()`, `parse_stream_event()`,
and `refresh_credentials()`: `taui/llm_provider/base.py:122`.

## Models

Default model selection and cached model lists are in `taui/llm_provider/models.py:81`.
The `/model` command reads that catalog at `taui/commands/builtins.py:135`.
The manual refresh command is `/update-providers-models`:
`taui/commands/builtins.py:801`.

## Auth And Config

- Runtime config dataclass: `taui/config.py:33`
- Config loading: `taui/config.py:64`
- Provider login CLI flag: `taui/main.py:59`
- Provider switching command: `taui/commands/builtins.py:471`

Keep provider-specific token refresh and wire quirks inside provider modules. If the loop
needs a new capability, add it to `ProviderCapabilities` first.
