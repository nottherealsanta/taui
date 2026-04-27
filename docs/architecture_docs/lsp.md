# LSP Manager

Manages Language Server Protocol client connections — one subprocess per language. Provides structured access to code intelligence features: go-to-definition, references, hover, document symbols, workspace symbols, diagnostics, and call hierarchy.

---

## Architecture

```
LspManager
  │
  ├── _get_client(lang)   → start LSP server if needed, cache by language
  ├── stop_all()           → terminate all server subprocesses
  ├── configure_server()   → override default command for a language
  │
  └── High-level operations:
      ├── go_to_definition(lang, file, line, char)
      ├── find_references(lang, file, line, char)
      ├── hover(lang, file, line, char)
      ├── document_symbols(lang, file)
      ├── workspace_symbols(lang, query)
      ├── go_to_implementation(lang, file, line, char)
      ├── diagnostics(lang, file)
      └── call_hierarchy(lang, file, line, char, direction)
              │
              ▼
LspClient (one per language server)
  │
  ├── start(root_uri)      → subprocess + LSP initialize handshake
  ├── stop()               → shutdown/exit + terminate
  ├── request(method, params)  → JSON-RPC request/response
  ├── notify(method, params)   → JSON-RPC notification
  └── _read_loop()         → background task reading responses
```

---

## Default Server Commands

| Language | Command |
|----------|---------|
| Python | `pylsp` |
| TypeScript | `typescript-language-server --stdio` |
| JavaScript | `typescript-language-server --stdio` |
| Rust | `rust-analyzer` |
| Go | `gopls` |
| C/C++ | `clangd` |

Custom servers can be registered at runtime:

```python
manager = LspManager("/path/to/project")
manager.configure_server("python", ["pyright-langserver", "--stdio"])
```

---

## LSP Client

Manages a single server subprocess over stdio JSON-RPC:

```python
class LspClient:
    alive: bool             # subprocess still running?

    async def start(root_uri)   # spawn + initialize handshake
    async def stop()            # shutdown + exit + terminate
    async def request(method, params, *, timeout=30.0) -> Any
    async def notify(method, params)
```

### Wire Protocol

Standard LSP framing over stdin/stdout:

```
Content-Length: <n>\r\n
\r\n
<JSON body>
```

### Initialize Handshake

1. Send `initialize` with client capabilities
2. Receive server capabilities
3. Send `initialized` notification
4. Server is ready

### Capabilities Declared

- `textDocument/definition`, `references`, `hover`, `documentSymbol`, `implementation`
- `callHierarchy`
- `workspace/symbol`
- `publishDiagnostics` with related information

---

## Data Types

### Position
```python
@dataclass(slots=True)
class Position:
    line: int      # 0-indexed
    character: int  # 0-indexed
```

### Location
```python
@dataclass(slots=True)
class Location:
    uri: str
    range: Range

    def to_dict() -> dict  # converts to 1-indexed file/line/character
```

### SymbolInfo
```python
@dataclass(slots=True)
class SymbolInfo:
    name: str
    kind: int                    # LSP SymbolKind enum
    location: Location
    container_name: str | None

    def to_dict() -> dict        # kind mapped to human name
```

### HoverResult
```python
@dataclass(slots=True)
class HoverResult:
    contents: str
    range: Range | None
```

### Diagnostic
```python
@dataclass(slots=True)
class Diagnostic:
    range: Range
    message: str
    severity: int   # 1=Error, 2=Warning, 3=Info, 4=Hint
    source: str | None

    def pretty() -> str   # formatted for display
```

---

## High-Level Operations

All operations take a `language_id` and automatically manage the server lifecycle — starting a server on first use.

| Method | Returns | Description |
|--------|---------|-------------|
| `go_to_definition` | `list[Location]` | Jump to symbol definition |
| `find_references` | `list[Location]` | All references including declaration |
| `hover` | `HoverResult \| None` | Type/doc info at position |
| `document_symbols` | `list[SymbolInfo]` | All symbols in a file |
| `workspace_symbols` | `list[SymbolInfo]` | Search symbols across workspace |
| `go_to_implementation` | `list[Location]` | Jump to implementation |
| `diagnostics` | `list[Diagnostic]` | Pull diagnostics for a file |
| `call_hierarchy` | `list[dict]` | Incoming/outgoing calls |

### Coordinate Convention

- **Input**: 1-indexed line and character (human-friendly)
- **Internal**: 0-indexed (LSP protocol)
- **Output** (`to_dict`): 1-indexed

---

## Error Handling

- Unknown language → `ValueError` listing known languages
- Server binary not found → subprocess error on start
- Request timeout → `asyncio.TimeoutError` after 30s (configurable)
- Server crash → `alive` returns False, next request restarts
- LSP error response → `LspError` exception with message

---

## Module Layout

```
taui/lsp/
├── __init__.py     # public exports
├── client.py       # LspClient, LspError
├── manager.py      # LspManager, default server configs
└── types.py        # Position, Range, Location, Diagnostic, SymbolInfo, HoverResult
```
