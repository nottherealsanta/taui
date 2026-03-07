# Tool Registry and Execution Pipeline

Define requirements for registration safety, policy gating, schema checks, and normalized outcomes.

{{status: ready}}

- [specs/tool_registry_execution_pipeline.md#tool-registry-and-execution-pipeline](tool_registry_execution_pipeline.md#tool-registry-and-execution-pipeline)
- [Register tools with unique names](tool_registry_execution_pipeline.md#register-tools-with-unique-names)
- [Publish model-compatible function schemas](tool_registry_execution_pipeline.md#publish-model-compatible-function-schemas)
- [Gate execution through policy decisions](tool_registry_execution_pipeline.md#gate-execution-through-policy-decisions)
- [Validate tool arguments and normalize failures](tool_registry_execution_pipeline.md#validate-tool-arguments-and-normalize-failures)

## Register tools with unique names

Prevent duplicate tool names in registry state.

{{status: ready}}

- [specs/tool_registry_execution_pipeline.md#register-tools-with-unique-names](tool_registry_execution_pipeline.md#register-tools-with-unique-names)

### Register tools with unique names leaf
{{status: ready}}

- Registering an existing name raises a descriptive `ValueError`.
{{code_ref: `taui/tools/registry.py#L12`}}
## Publish model-compatible function schemas

Expose registered tools in function-call schema format for LLM clients.

{{status: ready}}

- [specs/tool_registry_execution_pipeline.md#publish-model-compatible-function-schemas](tool_registry_execution_pipeline.md#publish-model-compatible-function-schemas)

### Publish model-compatible function schemas leaf
{{status: ready}}

- Schema list includes tool name, description, and parameter schema.
{{code_ref: `taui/tools/registry.py#L28`}}
## Gate execution through policy decisions

Enforce allow/confirm/deny decisions before any tool execution.

{{status: ready}}

- [specs/tool_registry_execution_pipeline.md#gate-execution-through-policy-decisions](tool_registry_execution_pipeline.md#gate-execution-through-policy-decisions)

### Gate execution through policy decisions leaf
{{status: ready}}

- Confirm policies return `approval_required` when explicit approval is absent.
{{code_ref: `taui/tools/executor.py#L69`}}
## Validate tool arguments and normalize failures

Validate schema contract and convert timeout/exception paths into normalized failures.

{{status: ready}}

- [specs/tool_registry_execution_pipeline.md#validate-tool-arguments-and-normalize-failures](tool_registry_execution_pipeline.md#validate-tool-arguments-and-normalize-failures)

### Validate tool arguments and normalize failures leaf
{{status: ready}}

- Timeout and exception outcomes include tool metadata and digest.

#### Detailed implementation requirements
{{status: ready}}

##### Behavior
{{status: ready}}

- Required fields and type checks run before execution.

##### Constraints
{{status: ready}}

- Unsupported top-level schema types fail with deterministic message.

##### Files
{{status: ready}}
{{code_ref: `taui/tools/executor.py`}}
##### Tests
{{status: ready}}

- Add coverage for missing required field, type mismatch, timeout, and exception branches.
