# Backend Integration

Define backend start-run and event-stream contracts for UI execution flow.

{{status: draft}}

- [specs/ui/backend_integration.md#backend-integration](backend_integration.md#backend-integration)
- [Start runs by canonical spec ref](backend_integration.md#start-runs-by-canonical-spec-ref)
- [Stream backend events with reconnect safety](backend_integration.md#stream-backend-events-with-reconnect-safety)

## Start runs by canonical spec ref

Start execution from the selected canonical spec reference.

{{status: draft}}

- [specs/ui/backend_integration.md#start-runs-by-canonical-spec-ref](backend_integration.md#start-runs-by-canonical-spec-ref)

### Start runs by canonical spec ref leaf
{{status: draft}}

- Start requests always include canonical `spec_ref` from the current selection.
{{code_ref: `taui/static/js/rpc.js`}}
{{code_ref: `taui/static/js/app.js`}}
## Stream backend events with reconnect safety

Subscribe to backend event streams and recover after disconnects.

{{status: draft}}

- [specs/ui/backend_integration.md#stream-backend-events-with-reconnect-safety](backend_integration.md#stream-backend-events-with-reconnect-safety)

### Stream backend events with reconnect safety leaf
{{status: draft}}

- Stream reconnect logic resumes updates without duplicating handled events.
{{code_ref: `taui/static/js/rpc.js`}}
{{code_ref: `taui/static/js/rpc.js`}}
