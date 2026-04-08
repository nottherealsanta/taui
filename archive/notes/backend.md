# Backend Architecture
{{status: done}}

The Python backend is built on FastAPI and provides a WebSocket-based JSON-RPC 2.0 API for spec management and agent orchestration.

## Directory Structure
{{status: done}}

```
taui/
├── __init__.py
├── __main__.py          # CLI entry point
├── agent/               # Agent orchestration
│   ├── loop.py          # Main agent loop
│   ├── state.py         # Agent state machine
│   └── tool_policy.py   # Tool execution policies
├── auth/                # Authentication
├── config/              # Configuration management
├── llm/                 # LLM abstraction
│   └── base.py          # LLM interface
├── llms/                # LLM provider implementations
│   ├── anthropic.py
│   ├── openai.py
│   └── ...
├── logging.py           # Logging utilities
├── server/              # HTTP/WebSocket server
│   ├── __main__.py      # Server entry point
│   ├── app.py           # FastAPI app
│   └── protocol.py      # JSON-RPC protocol
├── specs/               # Spec management
│   ├── db.py            # SQLite database
│   ├── markdown.py      # Markdown parsing
│   ├── service.py       # Spec business logic
│   └── sync.py          # File synchronization
└── tools/               # Tool implementations
    ├── base.py
    ├── fs.py
    └── ...
```

## Server Layer
{{status: done}}

### Startup Sequence

```mermaid
sequenceDiagram
    participant CLI as CLI/Runner
    participant Server as Uvicorn Server
    participant Socket as OS Socket
    participant WS as WebSocket Handler
    participant App as FastAPI App
    
    CLI->>Socket: Bind to 127.0.0.1:0 (random port)
    Socket-->>CLI: Returns assigned port
    CLI->>Server: Start with bound socket
    Server->>Server: Override startup()
    Server->>App: Initialize routes
    Server->>CLI: Print "PORT:<n>" to stdout
    CLI->>WS: Connect to ws://127.0.0.1:<port>/ws
    WS->>WS: Accept connection (single-client)
```

### Connection Management

```mermaid
stateDiagram-v2
    [*] --> Listening: Server Start
    Listening --> Connected: Client Connects
    Connected --> Connected: More clients rejected (1013)
    Connected --> Disconnected: Client closes
    Disconnected --> Listening: Ready for new client
```

### Key Components

#### Port Binding Pattern
{{status: done}}

The server uses a deliberate port-binding race-prevention pattern:

1. A raw `socket.socket` is bound to `127.0.0.1:0`
2. OS assigns a free port, socket kept open
3. Uvicorn started with pre-bound socket
4. `PORT:<n>` printed only after Uvicorn enters accept loop

{{code_ref: `taui/server/__main__.py`}}

#### Single-Client Enforcement
{{status: done}}

```mermaid
flowchart TD
    A[New WebSocket Connection] --> B{Active Connection?}
    B -->|Yes| C[Accept WebSocket]
    C --> D[Close with code 1013]
    D --> E[Log warning]
    E --> F[Return without register]
    B -->|No| G[Accept WebSocket]
    G --> H[Register connection]
    H --> I[Process messages]
```

## Spec Management Layer
{{status: done}}

### Database Schema

```mermaid
erDiagram
    FILES {
        text path PK
        text content_hash
        integer mtime_ns
    }
    
    NODES {
        text spec_ref PK
        text file_path FK
        text anchor
        text title
        integer depth
        integer heading_level
        integer line_start
        integer line_end
        text intent
        text status
        text content
        integer sort_order
    }
    
    EDGES {
        text parent_ref FK
        text child_ref FK
    }
    
    NODE_REFS {
        text source_ref FK
        text target_ref
        integer line_number
    }
    
    NODE_METADATA {
        text spec_ref FK
        text key
        text value
    }
    
    FILES ||--o{ NODES : contains
    NODES ||--o{ EDGES : parent
    NODES ||--o{ EDGES : child
    NODES ||--o{ NODE_REFS : references
    NODES ||--o{ NODE_METADATA : has
```

### Spec Synchronization Flow

```mermaid
flowchart TD
    subgraph Init["Initialization"]
        A[Load from ~/.cache/taui/hash/spec.db] --> B{DB Exists?}
        B -->|Yes| C[Load into memory]
        B -->|No| D[Create in-memory DB]
        D --> E[Scan markdown files]
        E --> F[Parse headings]
        F --> G[Build tree structure]
    end
    
    subgraph Runtime["Runtime"]
        C --> H[Serve requests]
        G --> H
        H --> I[Apply mutations]
        I --> J[Update DB]
        J --> K[Debounced write 500ms]
        K --> L[Regenerate markdown]
        L --> M[Write to file]
    end
    
    subgraph Snapshot["Periodic Snapshot"]
        N[Every 30 seconds] --> O[Snapshot to disk]
    end
```

## Agent Layer
{{status: done}}

### Agent Loop Architecture

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Running: Start Run
    Running --> Thinking: Send to LLM
    Thinking --> ToolExecution: Tool call needed
    ToolExecution --> Thinking: Tool result ready
    Thinking --> Clarification: Ambiguity detected
    Clarification --> Thinking: User answers
    Thinking --> Blocked: Unresolved ambiguity
    Blocked --> Thinking: Resolution provided
    Thinking --> Done: Task complete
    Done --> Idle
    Running --> Error: Failure
    Error --> Idle
```

### Tool Policy System

```mermaid
flowchart TD
    A[Tool Call Request] --> B{Policy Check}
    B -->|Auto-approve| C[Execute immediately]
    B -->|Requires Approval| D{User Approval}
    D -->|Approved| C
    D -->|Rejected| E[Return error]
    B -->|Forbidden| F[Block execution]
    
    subgraph PolicyTypes["Policy Types"]
        PT1[Read-only: Auto-approve]
        PT2[Write: Require approval]
        PT3[Destructive: Forbidden]
    end
```

### LLM Integration

```mermaid
classDiagram
    class LLMInterface {
        <<interface>>
        +complete(messages) Response
        +stream(messages) AsyncIterator
    }
    
    class AnthropicLLM {
        +complete(messages) Response
        +stream(messages) AsyncIterator
    }
    
    class OpenAILLM {
        +complete(messages) Response
        +stream(messages) AsyncIterator
    }
    
    class OllamaLLM {
        +complete(messages) Response
        +stream(messages) AsyncIterator
    }
    
    LLMInterface <|.. AnthropicLLM
    LLMInterface <|.. OpenAILLM
    LLMInterface <|.. OllamaLLM
```

## Tool System
{{status: done}}

### Available Tools

```mermaid
mindmap
  root((Tools))
    File System
      Read file
      Write file
      Edit file
      Glob search
      Grep content
    Process
      Run command
      Shell execution
    Spec Operations
      Get node
      Update node
      Create sibling
      Structural edits
    Code Analysis
      Parse AST
      Find references
```

### Tool Execution Flow

```mermaid
sequenceDiagram
    participant Agent as Agent Loop
    participant Policy as Tool Policy
    participant Tool as Tool Implementation
    participant FS as File System
    
    Agent->>Policy: Request tool execution
    Policy->>Policy: Check policy rules
    alt Auto-approved
        Policy->>Tool: Execute
        Tool->>FS: Perform operation
        FS-->>Tool: Result
        Tool-->>Agent: Tool result
    else Requires approval
        Policy->>Agent: Request approval
        Agent->>Agent: Wait for user
        Agent->>Policy: User decision
        Policy->>Tool: Execute (if approved)
    end
```

## Error Handling
{{status: done}}

### Error Propagation

```mermaid
flowchart TD
    A[Error Occurs] --> B{Error Type}
    B -->|Validation| C[INVALID_PARAMS -32602]
    B -->|Not Found| D[METHOD_NOT_FOUND -32601]
    B -->|Parse Error| E[PARSE_ERROR -32700]
    B -->|Domain Error| F[SPEC_SERVICE_ERROR -32001]
    
    C --> G[Return JSON-RPC error]
    D --> G
    E --> G
    F --> G
    
    G --> H[Client receives error]
    H --> I[Update BackendState]
    I --> J[Display error banner]
```
