# Session and Context Management

Define requirements for session persistence, usage accounting, and token-budget compaction.

{{status: ready}}

- [specs/session_context_management.md#session-and-context-management](session_context_management.md#session-and-context-management)
- [Initialize session identity and timestamps](session_context_management.md#initialize-session-identity-and-timestamps)
- [Record usage counters from model responses](session_context_management.md#record-usage-counters-from-model-responses)
- [Compact context under token budget pressure](session_context_management.md#compact-context-under-token-budget-pressure)
- [Persist read-attempt ledger](session_context_management.md#persist-read-attempt-ledger)

## Initialize session identity and timestamps

Create stable session identity and UTC timestamps for lifecycle tracking.

{{status: ready}}

- [specs/session_context_management.md#initialize-session-identity-and-timestamps](session_context_management.md#initialize-session-identity-and-timestamps)

### Initialize session identity and timestamps leaf
{{status: ready}}

- Session id is always non-empty and timestamps are updated on mutation.
{{code_ref: `taui/agent/session.py#L24`}}
## Record usage counters from model responses

Aggregate input and output tokens into cumulative session usage.

{{status: ready}}

- [specs/session_context_management.md#record-usage-counters-from-model-responses](session_context_management.md#record-usage-counters-from-model-responses)

### Record usage counters from model responses leaf
{{status: ready}}

- `record_usage(None)` is a no-op and valid usage increments totals.
{{code_ref: `taui/agent/session.py#L41`}}
## Compact context under token budget pressure

Trim old messages while preserving critical context and unresolved tool call pairs.

{{status: ready}}

- [specs/session_context_management.md#compact-context-under-token-budget-pressure](session_context_management.md#compact-context-under-token-budget-pressure)

### Compact context under token budget pressure leaf
{{status: ready}}

- Compaction inserts summary marker exactly once per compaction cycle.

#### Detailed implementation requirements
{{status: ready}}

##### Behavior
{{status: ready}}

- Apply soft and hard limits while preserving critical indexes.

##### Constraints
{{status: ready}}

- Context must not exceed available budget after compaction.

##### Files
{{status: ready}}
{{code_ref: `taui/agent/session.py`}}
##### Tests
{{status: ready}}

- Cover soft-limit compaction, hard-limit compaction, and unresolved tool-call preservation.

## Persist read-attempt ledger

Track read attempt statuses by canonical absolute path across serialization.

{{status: ready}}

- [specs/session_context_management.md#persist-read-attempt-ledger](session_context_management.md#persist-read-attempt-ledger)

### Persist read-attempt ledger leaf
{{status: ready}}

- Read status survives `to_dict` and `from_dict` round-trips.
{{code_ref: `taui/agent/session.py#L119`}}
