- # Rust UI
    Native GPUI desktop application. Renders the spec tree as the primary workflow surface. Communicates with the Python backend via WebSocket JSON-RPC 2.0.
    - {{status: draft}}
    - ## App Shell
        Root GPUI component. Owns AppState, Theme, BackendClient. Renders panes and handles global keybindings.
        - {{status: draft}}
        - {{code_ref: `ui/src/app/mod.rs`}}
    - ## State & Events
        Pure reducer-based AppState. Dispatches actions; re-hydrates node arena from backend after mutations.
        - {{status: draft}}
        - {{code_ref: `ui/src/app/mod.rs`}}
    - ## Spec Tree Pane
        Main tree view. Inline editing, collapse/expand, keyboard-driven node navigation and structural edits.
        - {{status: draft}}
    - ## Chat Pane
        Stub for future agent chat UX.
        - {{status: draft}}
    - ## Plan Status Pane
        Stub for future agent plan visualization.
        - {{status: draft}}
    - ## Execution Pane
        Stub for future run output display.
        - {{status: draft}}
    - ## Backend Integration
        WebSocket RPC client. Connects to Python backend, sends JSON-RPC requests, parses responses.
        - {{status: draft}}
    - ## Theme
        Color tokens and typography scale for GPUI rendering.
        - {{status: draft}}
    - ## Keybindings
        Global and pane-scoped keyboard shortcut definitions.
        - {{status: draft}}
