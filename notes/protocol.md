# IPC Protocol
{{status: done}}

Taui uses JSON-RPC 2.0 over WebSocket for all communication between the Python backend and Rust frontend.

## Protocol Overview
{{status: done}}

```mermaid
graph LR
    subgraph Frontend["Rust Frontend"]
        C[BackendClient]
    end
    
    subgraph Transport["WebSocket Transport"]
        WS[ws://127.0.0.1:port/ws]
    end
    
    subgraph Backend["Python Backend"]
        S[FastAPI Server]
        H[Method Handlers]
    end
    
    C <-->|JSON-RPC 2.0| WS
    WS <--> S
    S --> H
```

## Message Formats
{{status: done}}

### Request Format

```json
{
  "jsonrpc": "2.0",
  "id": 42,
  "method": "spec/getTree",
  "params": {}
}
```

### Success Response

```json
{
  "jsonrpc": "2.0",
  "id": 42,
  "result": { ... }
}
```

### Error Response

```json
{
  "jsonrpc": "2.0",
  "id": 42,
  "error": {
    "code": -32601,
    "message": "Method not found",
    "data": { "code": "spec_not_found" }
  }
}
```

### Notification (Server → Client)

```json
{
  "jsonrpc": "2.0",
  "method": "spec/nodeChanged",
  "params": { "node": { ... } }
}
```

## Error Codes
{{status: done}}

```mermaid
flowchart TD
    E[-32700] --> PE[PARSE_ERROR]
    E2[-32600] --> IR[INVALID_REQUEST]
    E3[-32601] --> MNF[METHOD_NOT_FOUND]
    E4[-32602] --> IP[INVALID_PARAMS]
    E5[-32603] --> IE[INTERNAL_ERROR]
    E6[-32001] --> SSE[SPEC_SERVICE_ERROR]
```

| Code | Name | Description |
|------|------|-------------|
| -32700 | PARSE_ERROR | Malformed JSON |
| -32600 | INVALID_REQUEST | Bad jsonrpc version/id |
| -32601 | METHOD_NOT_FOUND | Unknown method |
| -32602 | INVALID_PARAMS | Validation failure |
| -32603 | INTERNAL_ERROR | Server error |
| -32001 | SPEC_SERVICE_ERROR | Domain error |

## RPC Methods
{{status: done}}

### Session Lifecycle

```mermaid
sequenceDiagram
    participant C as Client
    participant S as Server
    
    C->>S: initialize(workspace)
    S-->>C: capabilities, version
    
    Note over C,S: Normal operation...
    
    C->>S: shutdown()
    S-->>C: {ok: true}
    
    C->>S: exit (notification)
```

### Spec Tree Reads

```mermaid
flowchart TD
    subgraph Methods["Read Methods"]
        M1[spec/getTree]
        M2[spec/getTreeDetailed]
        M3[spec/getNode]
        M4[spec/getNodeSourceRange]
        M5[spec/getNodeCodeRefs]
    end
    
    M1 --> R1[Flat tree, no content]
    M2 --> R2[Full tree with content]
    M3 --> R3[Single node detail]
    M4 --> R4[Source file slice]
    M5 --> R5[Resolved code refs]
```

### Spec Tree Mutations

```mermaid
stateDiagram-v2
    [*] --> Unchanged
    Unchanged --> Modified: updateNode
    Modified --> StructureChanged: createSibling/indent/outdent
    StructureChanged --> Notifications: treeChanged + nodeChanged
    Notifications --> [*]
    
    state Notifications {
        [*] --> treeChanged
        treeChanged --> nodeChanged
        nodeChanged --> [*]
    }
```

### Process Execution

```mermaid
sequenceDiagram
    participant C as Client
    participant S as Server
    participant P as Process
    
    C->>S: run/start(spec_ref, command)
    S->>P: Launch process
    S-->>C: RunProcess info
    
    loop Output lines
        P->>S: stdout/stderr line
        S->>C: run/output notification
    end
    
    P->>S: Exit
    S->>C: run/completed notification
```

## Notifications
{{status: done}}

### Notification Types

```mermaid
mindmap
  root((Notifications))
    Spec Changes
      spec/nodeChanged
      spec/treeChanged
    Process Events
      run/output
      run/completed
    Agent Events
      agent/event
      agent/token
    Approval Flow
      approval/request
      clarificationRequired
      amendmentProposed
```

### Notification Flow

```mermaid
flowchart TD
    A[RPC Mutation] --> B[Dispatch]
    B --> C[Apply changes]
    C --> D[Generate notifications]
    D --> E[Send result]
    E --> F[Send notifications in order]
    
    subgraph Order["Notification Order"]
        F1[1. Result message]
        F2[2. treeChanged]
        F3[3. nodeChanged]
    end
```

## Data Types
{{status: done}}

### SpecNode

```mermaid
classDiagram
    class SpecNode {
        +String id
        +String spec_ref
        +String title
        +int depth
        +String file_path
        +String anchor
        +String intent
        +String status
    }
    
    class SpecNodeDetail {
        +String content
        +int line_start
        +int line_end
    }
    
    SpecNode <|-- SpecNodeDetail : extends
```

### SpecUpdateResult

```mermaid
classDiagram
    class SpecUpdateResult {
        +String previous_spec_ref
        +SpecNodeDetail node
        +bool tree_changed
    }
```

### Process Types

```mermaid
classDiagram
    class RunProcess {
        +int run_id
        +String spec_ref
        +String command
        +String workdir
        +String status
        +int exit_code
        +String started_at
        +String finished_at
    }
    
    class RunState {
        +String status
        +int run_id
        +String spec_ref
    }
```

## State Synchronization
{{status: done}}

### Hydration Flow

```mermaid
sequenceDiagram
    participant UI as Frontend
    participant BC as BackendClient
    participant BS as Backend Server
    participant DB as SQLite
    
    UI->>BC: Apply structural change
    BC->>BS: RPC (indentNode, etc.)
    BS->>DB: Update tree
    BS-->>BC: SpecUpdateResult
    BC->>BS: getTreeDetailed
    BS->>DB: Query all nodes
    BS-->>BC: Full tree
    BC-->>UI: Vec~BackendNode~
    UI->>UI: hydrate_from_backend()
```

### Selection Persistence

```mermaid
flowchart TD
    A[Before hydration] --> B[Store selected_spec_ref]
    B --> C[Hydrate new nodes]
    C --> D[Lookup spec_ref in new index]
    D --> E{Found?}
    E -->|Yes| F[Restore selection]
    E -->|No| G[Clear selection]
```

### Collapsed State

```mermaid
flowchart LR
    A[User toggles collapse] --> B[Update content]
    B --> C["Add {{collapsed: true}}"]
    C --> D[Send to backend]
    D --> E[Parse on next hydration]
```

## Current Limitations
{{status: done}}

### Known Gaps

```mermaid
graph TB
    subgraph Issues["Current Limitations"]
        I1[New WS per RPC call]
        I2[Notifications not consumed]
        I3[start_run is stub]
        I4[Some endpoints unused]
    end
    
    I1 --> S1[Connection overhead]
    I2 --> S2[Re-fetch after mutations]
    I3 --> S3[Always returns RunId 1]
    I4 --> S4[getNodeSourceRange not called]
```

### Notification Handling Gap

```mermaid
flowchart TD
    A[Server emits notification] --> B{Client handling?}
    B -->|spec/nodeChanged| C[Not processed]
    B -->|spec/treeChanged| C
    B -->|run/output| C
    B -->|run/completed| C
    
    C --> D[Frontend uses pull-based sync]
    D --> E[Explicit getTreeDetailed calls]
```
