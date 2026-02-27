# Skills System Detailed Plan

## Objective
Implement `taui.skills` as an on-demand capability layer that can inject additional instructions and optional tools into the turn context.

## Scope
- `taui/skills/loader.py`
- `taui/skills/builtins/`
- Skill discovery in user config path and package path

## Skill Contract
Required fields from architecture:
- `name`
- `description`
- `instructions`
- `tools` (optional)
- `when` (optional activation condition)

## Discovery Sources
- User-managed: `~/.config/taui/skills/`
- Built-in: `taui/skills/builtins/`

## Loader Responsibilities
- Discover and parse skill definitions from both sources.
- Validate required fields and schema consistency.
- Resolve optional tool bindings by name/reference.
- Return activated skill set for current turn context.

## Activation Strategy
- Base strategy: explicit enable list plus optional `when` matching.
- `when` matching can start simple (keyword/pattern rules) and expand later.
- Deterministic order: user skills first, then built-ins, unless explicit priority exists.

## Injection Rules
- Instructions from active skills appended to turn context in deterministic order.
- Tool sets from skills merged with global registry without name collisions.
- Collision behavior: fail fast with clear error unless one side is explicitly namespaced.

## Error Handling
- Invalid skill file should report path and validation details.
- Unknown referenced tool should disable that skill (or fail in strict mode).
- Circular imports/dependencies (if supported later) should be rejected.

## Test Plan
- Unit: discovery from both directories.
- Unit: field validation and invalid skill rejection.
- Unit: activation logic for explicit and `when`-based activation.
- Unit: instruction merge order and tool collision handling.
- Integration: active skill influences one real turn response.

## Dependencies
- Depends on tool registry for optional skill-provided tools.
- Consumed by agent runtime before provider invocation.

## Exit Criteria
- Skills can be loaded, activated, and injected consistently.
- Invalid skills fail with actionable diagnostics.
- Built-in and user skill behavior is deterministic.
