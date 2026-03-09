# Data Models
{{status: done}}

This document covers the data models used across the Taui system, including both Python backend and Rust frontend types.

## Backend Data Models (Python)
{{status: done}}

### SpecNode Types

```mermaid
classDiagram
    class SpecNode {
        +str id
        +str spec_ref
        +str title
        +int depth
        +str file_path
        +str anchor
        +Optional~str~ intent
        +Optional~str~ status
    }
    
    class SpecNodeDetail {
        +str content
        +int line_start
        +int line_end
    }
    
    SpecNode <|-- SpecNodeDetail
```

### Tree Response Types

```mermaid
classDiagram
    class TreeResponse {
        +List~SpecNode~ nodes
    }
    
    class TreeDetailResponse {
        +List~SpecNodeDetail~ nodes
    }
    
    class NodeResponse {
        +SpecNodeDetail node
    }
```

### Mutation Response Types

```mermaid
classDiagram
    class SpecUpdateResult {
        +Optional~str~ previous_spec_ref
        +SpecNodeDetail node
        +bool tree_changed
    }
    
    class InitializeResponse {
        +str protocol_version
        +str server_name
        +Optional~str~ workspace
        +Capabilities capabilities
    }
    
    class Capabilities {
        +List~str~ methods
        +List~str~ notifications
    }
```

### Process Types

```mermaid
classDiagram
    class RunProcess {
        +int run_id
        +str spec_ref
        +str command
        +str workdir
        +str status
        +Optional~int~ exit_code
        +Optional~str~ started_at
        +Optional~str~ finished_at
    }
    
    class RunState {
        +str status
        +Optional~int~ run_id
        +Optional~str~ spec_ref
    }
```

### Code Reference Types

```mermaid
classDiagram
    class SourceRange {
        +str file_path
        +int line_start
        +int line_end
        +int preview_start
        +int preview_end
        +str content
        +bool truncated
        +Optional~str~ error
    }
    
    class CodeRef {
        +str raw_ref
        +str file_path
        +Optional~int~ line_start
        +Optional~int~ line_end
        +int preview_start
        +int preview_end
        +str content
        +bool truncated
        +Optional~str~ error
    }
```

## Frontend Data Models (Rust)
{{status: done}}

### Core Node Types

```mermaid
classDiagram
    class SpecNode {
        +usize id
        +String spec_ref
        +String title
        +String content
        +NodeStatus status
        +Option~usize~ parent
        +Vec~usize~ children
        +bool collapsed
    }
    
    class FlatNode {
        +usize id
        +usize depth
        +String title
        +String content
        +NodeStatus status
        +bool selected
        +bool collapsed
        +bool has_children
    }
    
    class NodeStatus {
        <<enumeration>>
        Draft
        Ready
        InProgress
        Done
        Blocked
        Unknown
    }
```

### AppState

```mermaid
classDiagram
    class AppState {
        +Vec~SpecNode~ nodes
        +Vec~usize~ root_nodes
        +HashMap~String,usize~ spec_ref_index
        +Option~usize~ selected_node
        +Option~String~ selected_spec_ref
        +bool edit_mode
        +Option~EditorState~ editor
        +String chat_draft
        +BackendState backend_state
    }
    
    class EditorState {
        +String title_buffer
        +String content_buffer
        +CaretPosition caret
        +EditField active_field
    }
    
    class CaretPosition {
        +usize line
        +usize column
    }
    
    class BackendState {
        <<enumeration>>
        Offline
        Loading
        Ready
        Error(String)
    }
    
    AppState --> EditorState
    AppState --> BackendState
    EditorState --> CaretPosition
```

### Backend Client Types

```mermaid
classDiagram
    class TreeNode {
        +String id
        +String spec_ref
        +String title
        +usize depth
        +Option~String~ content
        +Option~String~ intent
        +Option~String~ status
    }
    
    class TreeResponse {
        +Vec~TreeNode~ nodes
    }
    
    class InitializeResponse {
        +String protocol_version
        +String server_name
        +Option~String~ workspace
        +Capabilities capabilities
    }
    
    class UpdateNodeResponse {
        +Option~String~ previous_spec_ref
        +TreeNode node
        +bool tree_changed
    }
    
    class RunId {
        +u64 value
    }
```

### UI Action Types

```mermaid
classDiagram
    class UiAction {
        <<enumeration>>
        SelectNode(usize)
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

## JSON-RPC Types
{{status: done}}

### Request/Response

```mermaid
classDiagram
    class JsonRpcRequest {
        +str jsonrpc "2.0"
        +int|str id
        +str method
        +dict params
    }
    
    class JsonRpcResponse {
        +str jsonrpc "2.0"
        +int|str id
        +Optional~dict~ result
        +Optional~JsonRpcError~ error
    }
    
    class JsonRpcError {
        +int code
        +str message
        +Optional~dict~ data
    }
    
    JsonRpcResponse --> JsonRpcError
```

### Notification Types

```mermaid
classDiagram
    class JsonRpcNotification {
        +str jsonrpc "2.0"
        +str method
        +dict params
    }
    
    class NodeChangedNotification {
        +SpecNodeDetail node
    }
    
    class TreeChangedNotification {
        +Optional~str~ previous_spec_ref
        +str spec_ref
    }
    
    class RunOutputNotification {
        +int run_id
        +str stream
        +str line
    }
    
    class RunCompletedNotification {
        +int run_id
        +int exit_code
        +str status
        +int duration_ms
    }
    
    JsonRpcNotification <|-- NodeChangedNotification
    JsonRpcNotification <|-- TreeChangedNotification
    JsonRpcNotification <|-- RunOutputNotification
    JsonRpcNotification <|-- RunCompletedNotification
```

## Type Mappings
{{status: done}}

### Python to Rust Type Mapping

```mermaid
flowchart LR
    subgraph Python["Python Types"]
        P1[str]
        P2[int]
        P3[Optional~T~]
        P4[List~T~]
        P5[dict]
        P6[bool]
    end
    
    subgraph Rust["Rust Types"]
        R1[String]
        R2[i64/usize]
        R3[Option~T~]
        R4[Vec~T~]
        R5[HashMap~K,V~]
        R6[bool]
    end
    
    P1 --> R1
    P2 --> R2
    P3 --> R3
    P4 --> R4
    P5 --> R5
    P6 --> R6
```

### Status Mapping

```mermaid
flowchart TD
    subgraph Python["Python status"]
        S1["draft"]
        S2["ready"]
        S3["in_progress"]
        S4["done"]
        S5["blocked"]
        S6[null/unknown]
    end
    
    subgraph Rust["Rust NodeStatus"]
        R1[Draft]
        R2[Ready]
        R3[InProgress]
        R4[Done]
        R5[Blocked]
        R6[Unknown]
    end
    
    S1 --> R1
    S2 --> R2
    S3 --> R3
    S4 --> R4
    S5 --> R5
    S6 --> R6
```

## Database Schema
{{status: done}}

### Core Tables

```mermaid
erDiagram
    FILES {
        TEXT path PK
        TEXT content_hash
        INTEGER mtime_ns
    }
    
    NODES {
        TEXT spec_ref PK
        TEXT file_path FK
        TEXT anchor
        TEXT title
        INTEGER depth
        INTEGER heading_level
        INTEGER line_start
        INTEGER line_end
        TEXT intent
        TEXT status
        TEXT content
        INTEGER sort_order
    }
    
    EDGES {
        TEXT parent_ref FK
        TEXT child_ref FK
    }
    
    NODE_REFS {
        TEXT source_ref FK
        TEXT target_ref
        INTEGER line_number
    }
    
    NODE_METADATA {
        TEXT spec_ref FK
        TEXT key
        TEXT value
    }
    
    FILES ||--o{ NODES : contains
    NODES ||--o{ EDGES : "parent-child"
    NODES ||--o{ NODE_REFS : references
    NODES ||--o{ NODE_METADATA : has
```

### Agent History Tables

```mermaid
erDiagram
    SESSIONS {
        TEXT session_id PK
        TEXT spec_ref FK
        TEXT status
        TEXT started_at
        TEXT ended_at
    }
    
    MESSAGES {
        TEXT message_id PK
        TEXT session_id FK
        TEXT role
        TEXT content
        TEXT created_at
    }
    
    TOOL_CALLS {
        TEXT call_id PK
        TEXT session_id FK
        TEXT message_id FK
        TEXT tool_name
        TEXT arguments
        TEXT status
        TEXT created_at
    }
    
    TOOL_RESULTS {
        TEXT result_id PK
        TEXT call_id FK
        TEXT result
        TEXT error
        TEXT created_at
    }
    
    QUESTIONS {
        TEXT question_id PK
        TEXT session_id FK
        TEXT question_text
        TEXT options
        TEXT answer
        TEXT status
        TEXT created_at
        TEXT answered_at
    }
    
    SUBAGENT_SPAWNS {
        TEXT spawn_id PK
        TEXT parent_session_id FK
        TEXT child_session_id
        TEXT purpose
        TEXT created_at
    }
    
    SESSIONS ||--o{ MESSAGES : contains
    SESSIONS ||--o{ TOOL_CALLS : triggers
    MESSAGES ||--o{ TOOL_CALLS : "from message"
    TOOL_CALLS ||--o| TOOL_RESULTS : produces
    SESSIONS ||--o{ QUESTIONS : asks
    SESSIONS ||--o{ SUBAGENT_SPAWNS : spawns
```

## Type Aliases
{{status: done}}

### Common Type Aliases

| Alias | Type | Purpose |
|-------|------|---------|
| `NodeId` | `usize` | Index into nodes arena |
| `SpecRef` | `String` | Canonical spec reference |
| `RequestID` | `int \| str` | JSON-RPC request ID |

### SpecRef Format

```mermaid
flowchart LR
    A["specs/server.md#auth-flow"] --> B[Relative path]
    A --> C[# separator]
    A --> D[Slugified anchor]
    
    B --> E["specs/server.md"]
    D --> F["auth-flow"]
```
