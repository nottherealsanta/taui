# CLI Runtime Orchestration

Define requirements for CLI startup, provider/model resolution, and tool-loop execution.

{{status: ready}}

- [specs/cli_runtime_orchestration.md#cli-runtime-orchestration](cli_runtime_orchestration.md#cli-runtime-orchestration)
- [Parse provider and model flags](cli_runtime_orchestration.md#parse-provider-and-model-flags)
- [Resolve credentials for selected provider](cli_runtime_orchestration.md#resolve-credentials-for-selected-provider)
- [Build REPL tool context before turn loop](cli_runtime_orchestration.md#build-repl-tool-context-before-turn-loop)
- [Execute bounded tool-call loop](cli_runtime_orchestration.md#execute-bounded-tool-call-loop)

## Parse provider and model flags

Parse `--provider` and `--model` while preserving configured defaults.

{{status: ready}}

- [specs/cli_runtime_orchestration.md#parse-provider-and-model-flags](cli_runtime_orchestration.md#parse-provider-and-model-flags)

### Parse provider and model flags leaf
{{status: ready}}

- Invalid provider values are rejected and defaults resolve deterministically.

#### Detailed implementation requirements
{{status: ready}}

##### Behavior
{{status: ready}}

- CLI accepts provider/model flags and falls back to configured defaults.

##### Constraints
{{status: ready}}

- Provider must be a known key from provider registry.

##### Files
{{status: ready}}
{{code_ref: `taui/__main__.py`}}
##### Tests
{{status: ready}}

- Add CLI argument parsing coverage for default and override combinations.

## Resolve credentials for selected provider

Run provider auth flow once and reuse stored credentials on subsequent runs.

{{status: ready}}

- [specs/cli_runtime_orchestration.md#resolve-credentials-for-selected-provider](cli_runtime_orchestration.md#resolve-credentials-for-selected-provider)

### Resolve credentials for selected provider leaf
{{status: ready}}

- Auth failures exit cleanly with non-zero status and message.
{{code_ref: `taui/__main__.py#L64`}}
## Build REPL tool context before turn loop

Initialize session, policy, registry, executor, and context before processing user input.

{{status: ready}}

- [specs/cli_runtime_orchestration.md#build-repl-tool-context-before-turn-loop](cli_runtime_orchestration.md#build-repl-tool-context-before-turn-loop)

### Build REPL tool context before turn loop leaf
{{status: ready}}

- Tool-enabled clients print available tool names at startup.
{{code_ref: `taui/__main__.py#L88`}}
## Execute bounded tool-call loop

Iterate model/tool exchange until completion or bounded retry exhaustion.

{{status: ready}}

- [specs/cli_runtime_orchestration.md#execute-bounded-tool-call-loop](cli_runtime_orchestration.md#execute-bounded-tool-call-loop)

### Execute bounded tool-call loop leaf
{{status: ready}}

- Loop stops after maximum retry count and returns deterministic failure.
{{code_ref: `taui/__main__.py#L177`}}
