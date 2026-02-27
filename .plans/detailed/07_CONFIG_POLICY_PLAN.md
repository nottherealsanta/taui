# Config and Policy Detailed Plan

## Objective
Implement settings and permission policy modules that make provider/model selection and tool authorization predictable across CLI and TUI.

## Scope
- `taui/config/settings.py`
- `taui/config/policies.py`
- Runtime use of `~/.config/taui/config.toml`

## Config Contract
Based on architecture:

```toml
[model]
default = "openai:codex-mini"

[providers.openai]
api_key_env = "OPENAI_API_KEY"

[providers.copilot]

[policy]
auto_approve = ["read", "glob", "grep"]
confirm = ["edit", "write", "bash"]
deny = []

[policy.bash]
restrict_workdir_to_workspace = true
allow_network = true
env_allowlist = ["PATH", "HOME", "TERM"]
max_output_bytes = 51200
default_timeout_sec = 120
```

`[policy.bash]` values are optional in config and use safe defaults when omitted.

## `settings.py` Plan
- Parse config from `~/.config/taui/config.toml`.
- Provide defaults when file is missing.
- Resolve provider credentials from env variable names declared in config.
- Expose typed settings object to other modules.
- Add command-line override merge points (for CLI/TUI launch options).

## Precedence Rules
- Highest: explicit runtime/CLI flag overrides.
- Then: environment-derived values.
- Then: user config file values.
- Lowest: built-in defaults.
- Document precedence clearly in module docs and README updates.

## `policies.py` Plan
- Implement policy class with decision outcomes: `allow`, `confirm`, `deny`.
- Evaluate with deterministic order: deny list first, then confirm list, then auto-approve.
- Provide decision reason text for UI/CLI display.
- Implement initial command-sensitive hooks for `bash` boundaries (`workdir`, env allowlist, output limit, timeout, network flag).
- Preserve extension points for additional path/command-sensitive hooks without breaking API.

## Integration Requirements
- Tools executor must call policy for every tool invocation.
- CLI and TUI must be able to satisfy `confirm` decisions interactively.
- Non-interactive mode should fail safely on confirm-required tools if no approval path exists.
- `bash` tool execution must consume policy-provided boundary settings consistently.

## Validation and Error Handling
- Invalid config keys/types produce actionable startup errors.
- Missing required provider credential surfaces clear message naming env var.
- Unknown tool names in policy arrays should warn (or fail in strict mode).

## Test Plan
- Unit: config parse with defaults, full config, malformed config.
- Unit: precedence resolution across defaults/file/env/flags.
- Unit: policy outcomes for allow/confirm/deny.
- Unit: `policy.bash` defaults and override behavior.
- Integration: executor respects policy decisions from loaded settings.
- Integration: `bash` boundary enforcement from policy config.
- Integration: non-interactive confirm-required tool behavior.

## Dependencies
- Consumed by `llm/registry.py` (default model selection) and `tools/executor.py` (tool policy checks).

## Exit Criteria
- Config loads reliably with clear override behavior.
- Policy decisions are deterministic and test-covered.
- Interfaces can surface policy prompts and denials consistently.
