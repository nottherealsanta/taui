# Runtime

This page follows one user request through the current code.

## Session Creation

`Session.create()` is the wiring point: `taui/session.py:139`.

It builds:

- provider config and credentials: `taui/config.py:64`
- builtin tools: `taui/tools/builtins/__init__.py:28`
- tool policy and executor: `taui/tools/executor.py:42`,
  `taui/tools/executor.py:180`
- store and stream client: `taui/store/store.py:97`, `taui/store/stream.py:22`
- prompt from project context and tools: `taui/prompt_builder.py:123`
- extension context and hooks: `taui/extensions/__init__.py:66`
- agent loop callbacks for streaming and tools: `taui/agent/loop.py:93`

## Request Flow

1. The TUI receives input through `ChatInput`: `taui/tui/widgets/chat_input.py:35`.
2. `TauiApp` dispatches the message into `Session.send()`: `taui/session.py:330`.
3. `AgentLoop.run()` starts a stream and records the user message:
   `taui/agent/loop.py:174`.
4. The provider returns text deltas, reasoning deltas, usage, or tool calls through
   `StreamEvent`: `taui/llm_provider/types.py:151`.
5. Tool calls go through `ToolExecutor.execute()`: `taui/tools/executor.py:219`.
6. Results are appended to the stream as `TOOL_RESULT`: `taui/agent/loop.py:547`.
7. Final assistant text is stored as `ASSISTANT_MESSAGE`: `taui/agent/loop.py:320`.

## Store And Replay

The store is SQLite with streams, events, and sessions tables:
`taui/store/store.py:31`, `taui/store/store.py:39`, `taui/store/store.py:52`.

Use semantic projections instead of reading raw rows in UI code:

- conversation replay: `taui/store/stream.py:92`
- turn grouping: `taui/store/stream.py:101`
- live tailing: `taui/store/stream.py:133`

Session resume is implemented in `Session.resume_session()`: `taui/session.py:624`.

## TUI State

`TauiApp` owns rendering and user interaction: `taui/tui/app.py:206`.

- app key bindings: `taui/tui/app.py:399`
- mount/startup: `taui/tui/app.py:772`
- text streaming handler: `taui/tui/app.py:1575`
- reasoning streaming handler: `taui/tui/app.py:1594`
- tool status widget: `taui/tui/widgets/tool_status.py:49`
- turn containers: `taui/tui/widgets/turn_container.py:47`. Completed turns keep
  compact replay descriptors; collapsed turn bodies unmount their child widgets and
  remount them from those descriptors when expanded.
- approval prompt: `taui/tui/widgets/approval.py:14`
- question panel: `taui/tui/widgets/questions_panel.py:123`
- info bar: `taui/tui/widgets/info_bar.py:84`

Keep model/provider/tool behavior out of widgets unless the behavior is purely UI.

## Self-Edit And Extensions Mode

Self-edit mode swaps in a specialist prompt and executor:
`taui/session.py:920`, `taui/self_edit/factory.py:101`,
`taui/self_edit/factory.py:346`.

Extensions mode constrains write tools with a path guard:
`taui/session.py:427`, `taui/session.py:1002`, `taui/session.py:1010`.

Use these modes for extension and skill work, not for changing core runtime invariants.
