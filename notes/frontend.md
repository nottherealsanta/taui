# Frontend Architecture
{{status: done}}

The Rust GPUI frontend provides a native, GPU-accelerated user interface for interacting with the Taui spec tree and agent system.

## Directory Structure
{{status: done}}

```
ui/
├── Cargo.toml           # Dependencies: gpui, gpui-component, tokio
├── src/
│   ├── main.rs          # Binary entry (3 lines)
│   ├── lib.rs           # Module exports
│   ├── app/             # Core application
│   │   ├── mod.rs       # AppShell - root component
│   │   ├── actions.rs   # UiAction enum + reducer
│   │   ├── keybindings.rs # Key → Action mapping
│   │   ├── state.rs     # AppState domain model
│   │   ├── component_adapters.rs # Widget factories
│   │   └── typography.rs # Layout constants
│   ├── panes/           # UI panels
│   │   ├── mod.rs
│   │   ├── spec_tree.rs # Spec tree view
│   │   ├── chat.rs      # Chat interface
│   │   ├── plan_status.rs # Task DAG view
│   │   └── execution.rs # Agent event stream
│   ├── services/        # I/O layer
│   │   ├── mod.rs
│   │   ├── backend_client.rs # WebSocket client
│   │   ├── event_stream.rs   # Event subscription
│   │   └── spec_index.rs     # Markdown indexer
│   └── theme/           # Design tokens
│       ├── mod.rs
│       ├── colors.rs    # UI colors
│       ├── status_colors.rs # Status semantic colors
│       ├── syntax.rs    # Syntax highlighting
│       └── registry.rs  # Theme management
├── specs/               # Self-documenting specs
└── tests/               # Integration tests
```

## GPUI Patterns
{{status: done}}

### Application Bootstrap

```mermaid
sequenceDiagram
    participant Main as main.rs
    participant App as Application
    participant RT as Tokio Runtime
    participant Window as OS Window
    participant Shell as AppShell
    
    Main->>RT: Create runtime
    RT->>App: Application::new()
    App->>App: gpui_component::init()
    App->>App: cx.spawn(async)
    Note over App: Opens window in async context
    App->>Window: cx.open_window()
    Window->>Shell: cx.new(AppShell::new)
    Shell->>Shell: Initialize state
    Shell->>Shell: Start backend connection
    App->>App: app.run()
```

### Component Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Created: cx.new(Entity::new)
    Created --> Mounted: Added to window
    Mounted --> Rendering: cx.notify()
    Rendering --> Mounted: Render complete
    Mounted --> Updating: State mutation
    Updating --> Rendering: cx.notify()
    Mounted --> Destroyed: Entity dropped
    Destroyed --> [*]
```

### Key GPUI Concepts

| Concept | Purpose | Example |
|---------|---------|---------|
| `Entity<T>` | Reference-counted component | `Entity<AppShell>` |
| `Context<T>` | Component context for mutations | `cx: &mut Context<AppShell>` |
| `FocusHandle` | Keyboard focus tracking | `self.focus_handle` |
| `cx.spawn` | Async task spawning | Network I/O |
| `cx.notify()` | Schedule re-render | After state change |
| `cx.listener` | Event callback creation | Click handlers |
| `cx.subscribe_in` | Entity event subscription | Input blur events |

## App Shell
{{status: done}}

### Structure

```mermaid
classDiagram
    class AppShell {
        +AppState state
        +FocusHandle focus_handle
        +Theme theme
        +Option~BackendClient~ client
        +Entity~InputState~ title_input
        +Entity~InputState~ content_input
        +Option~NodeId~ editing_node_id
        +String saved_title
        +String saved_content
        +Subscription _title_subscription
        +Subscription _content_subscription
        +new(window, cx) AppShell
        +render() impl IntoElement
        +select_node(id, cx)
        +save_current_edits(cx)
        +apply_structural(action, cx)
        +handle_key_down(event, cx)
    }
    
    class AppState {
        +Vec~SpecNode~ nodes
        +Vec~NodeId~ root_nodes
        +HashMap~SpecRef,NodeId~ spec_ref_index
        +Option~NodeId~ selected_node
        +bool edit_mode
        +BackendState backend_state
    }
    
    AppShell --> AppState : owns
    AppShell --> BackendClient : uses
```

### Render Pipeline

```mermaid
flowchart TD
    A[render() called] --> B[Check BackendState]
    B -->|Loading| C[Show loading banner]
    B -->|Error| D[Show error banner]
    B -->|Ready| E[Render main UI]
    
    E --> F[Flatten tree nodes]
    F --> G[Render root header]
    G --> H[For each node]
    H --> I{Is selected?}
    I -->|Yes| J[Render with Input widgets]
    I -->|No| K[Render static div]
    J --> L[Add toolbar]
    K --> M[Add click handler]
    L --> N[Next node]
    M --> N
    N --> H
```

## State Management
{{status: done}}

### Action Dispatch Pattern

```mermaid
flowchart LR
    A[User Input] --> B[Keybinding Map]
    B --> C[UiAction]
    C --> D[dispatch]
    D --> E{State Changed?}
    E -->|Yes| F[cx.notify]
    E -->|No| G[Return]
    F --> H[Re-render]
```

### UiAction Types

```mermaid
classDiagram
    class UiAction {
        <<enumeration>>
        SelectNode(NodeId)
        SelectNext
        SelectPrevious
        AddSiblingNode
        IndentNode
        OutdentNode
        StartEditing
        StopEditing
        InsertText(String)
        ToggleCollapse
        CommitEdit
    }
```

### Tree Flattening

```mermaid
flowchart TD
    A[Tree Structure] --> B[flattened_nodes]
    B --> C[Respect collapsed state]
    C --> D[Include root node]
    
    A --> E[flattened_tree_nodes]
    E --> F[Respect collapsed state]
    F --> G[Exclude root node]
    
    subgraph Example["Example"]
        H[Root<br/>depth=0]
        H --> I[Child A<br/>depth=1]
        H --> J[Child B<br/>depth=1]
        J --> K[Grandchild<br/>depth=2]
    end
```

## Panes Module
{{status: done}}

### Pane Architecture

```mermaid
classDiagram
    class SpecTreePane {
        +render_tree(state) Vec~FlatNode~
        +select_spec_ref(state) Option~String~
        +render_node_status(status) &str
    }
    
    class ChatPane {
        +render(state) impl IntoElement
        +submit_message(msg) String
        +set_target_agent(target) String
    }
    
    class PlanStatusPane {
        +render_task_graph(state) impl IntoElement
        +render_task_node(label) String
        +highlight_active_wave(wave) String
    }
    
    class ExecutionPane {
        +bind_event_stream() &str
        +render_box_inspector(state) impl IntoElement
        +render_spec_compliance(ref) String
    }
```

### Current Pane Status

| Pane | Status | Implementation |
|------|--------|----------------|
| SpecTreePane | Live | Used in AppShell |
| ChatPane | Stub | Not mounted |
| PlanStatusPane | Stub | Not mounted |
| ExecutionPane | Stub | Not mounted |

## Services Module
{{status: done}}

### Backend Client

```mermaid
sequenceDiagram
    participant Shell as AppShell
    participant Client as BackendClient
    participant WS as WebSocket
    
    Shell->>Client: initialize(workspace)
    Client->>WS: Connect
    WS->>Client: Connected
    Client->>WS: Send JSON-RPC request
    WS->>Client: JSON-RPC response
    Client-->>Shell: InitializeResponse
    
    Shell->>Client: get_tree_detailed()
    Client->>WS: New connection per call
    WS->>Client: TreeResponse
    Client-->>Shell: Vec~TreeNode~
```

### RPC Methods

```mermaid
flowchart TD
    subgraph Client["BackendClient Methods"]
        M1[initialize]
        M2[get_tree_detailed]
        M3[update_node]
        M4[create_sibling_node]
        M5[indent_node]
        M6[outdent_node]
        M7[start_run - stub]
    end
    
    subgraph Server["JSON-RPC Methods"]
        S1["initialize"]
        S2["spec/getTreeDetailed"]
        S3["spec/updateNode"]
        S4["spec/createSiblingNode"]
        S5["spec/indentNode"]
        S6["spec/outdentNode"]
    end
    
    M1 --> S1
    M2 --> S2
    M3 --> S3
    M4 --> S4
    M5 --> S5
    M6 --> S6
```

### Connection Pattern (Current)

```mermaid
flowchart TD
    A[RPC Call] --> B[Create new WebSocket]
    B --> C[Send request]
    C --> D[Wait for response]
    D --> E[Close connection]
    E --> F[Return result]
    
    Note1[Note: Each call opens new connection]
```

## Theme System
{{status: done}}

### Theme Structure

```mermaid
classDiagram
    class ThemeColors {
        +u32 background
        +u32 panel_background
        +u32 border
        +u32 text
        +u32 text_muted
        +u32 element_background
        +taui_dark() ThemeColors
        +taui_light() ThemeColors
    }
    
    class StatusColors {
        +u32 error, warning, info, success
        +u32 spec_draft, spec_ready
        +u32 spec_in_progress, spec_done
        +u32 spec_blocked
        +u32 box_completed, box_failed
        +u32 clarification_blocking
        +u32 amendment_proposed
        +u32 verification_met
    }
    
    class Theme {
        +String name
        +Appearance appearance
        +ThemeStyles styles
    }
    
    class ThemeRegistry {
        +Vec~ThemeFamily~ families
        +default_light() Theme
        +default_dark() Theme
    }
    
    Theme --> ThemeColors : contains
    Theme --> StatusColors : contains
    ThemeRegistry --> Theme : manages
```

### Built-in Themes

```mermaid
graph LR
    subgraph TauiFamily["Taui Family"]
        TD[Taui Dark]
        TL[Taui Light]
    end
    
    subgraph ZedFamily["Zed One Family"]
        ZD[Zed One Dark]
    end
    
    TR[ThemeRegistry] --> TauiFamily
    TR --> ZedFamily
```

## Typography
{{status: done}}

### Heading Style Mapping

```mermaid
flowchart LR
    D0[Depth 0] --> S0["32px SEMIBOLD"]
    D1[Depth 1] --> S1["28px SEMIBOLD"]
    D2[Depth 2] --> S2["24px SEMIBOLD"]
    D3[Depth 3] --> S3["21px MEDIUM"]
    D4[Depth 4] --> S4["18px MEDIUM"]
    D5[Depth 5+] --> S5["16px NORMAL"]
```

### Layout Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| MAX_CONTENT_WIDTH | 960px | Document column width |
| INDENT_PER_LEVEL | 24px | Tree indent increment |

## Testing
{{status: done}}

### Test Structure

```mermaid
graph TB
    subgraph Integration["Integration Tests"]
        S1[smoke.rs]
        S2[state_reducer.rs]
    end
    
    subgraph Unit["Unit Tests"]
        U1[state.rs - 38 tests]
        U2[keybindings.rs]
        U3[typography.rs]
    end
    
    S1 --> T1[Demo state boots]
    S2 --> T2[Tab indent]
    S2 --> T3[Shift+Tab outdent]
    S2 --> T4[Add sibling]
    S2 --> T5[Edit mode lifecycle]
```
