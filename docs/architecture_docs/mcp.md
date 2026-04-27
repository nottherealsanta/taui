# MCP (Model Context Protocol)

MCP connects taui to external tool servers using the JSON-RPC 2.0 protocol over stdio. Each server exposes tools that the agent can discover and invoke.

---

## Architecture

```
McpManager
  │
  ├── load_configs()     → read .taui/mcp.toml and ~/.config/taui/mcp.toml
  ├── connect(name)      → start subprocess, initialize, list tools
  ├── disconnect_all()   → terminate all subprocesses
  └── all_tools()        → aggregate tools from all connected servers
          │
          ▼
McpClient (one per server)
  │
  ├── connect()          → subprocess + JSON-RPC initialize handshake
  ├── call_tool(name, args)  → JSON-RPC tools/call
  ├── tools              → list of McpTool from tools/list
  └── disconnect()       → terminate subprocess
          │
          ▼
McpTool (agent-facing)
  │
  ├── servers    → list configured servers and connection status
  ├── connect    → connect to a server by name
  ├── disconnect → disconnect from a server
  ├── tools      → list tools from all connected servers
  └── call       → invoke a tool (auto-discovers server from tool name)
```

---

## Configuration

MCP servers are configured in TOML files:

### Project config: `.taui/mcp.toml`
### Global config: `~/.config/taui/mcp.toml`

Project config overrides global for same-named servers.

```toml
[servers.filesystem]
command = ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

[servers.github]
command = ["npx", "-y", "@modelcontextprotocol/server-github"]
enabled = true

[servers.github.env]
GITHUB_TOKEN = "ghp_..."
```

### McpServerConfig

```python
@dataclass(slots=True)
class McpServerConfig:
    name: str
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
```

---

## Protocol

The client communicates with servers via newline-delimited JSON-RPC 2.0 over stdin/stdout.

### Connection Sequence

1. Start subprocess with `command`, merge `env` into environment
2. Send `initialize` request (protocol version `2024-11-05`)
3. Wait for initialize response
4. Send `notifications/initialized` notification
5. Send `tools/list` request to discover available tools

### Tool Invocation

```
→ {"jsonrpc": "2.0", "id": N, "method": "tools/call",
   "params": {"name": "tool_name", "arguments": {...}}}
← {"jsonrpc": "2.0", "id": N, "result": {
     "content": [{"type": "text", "text": "..."}]
   }}
```

### Timeouts

- Default request timeout: 30 seconds
- Subprocess termination timeout: 5 seconds (SIGTERM → SIGKILL)

---

## McpClient

Manages a single server subprocess:

```python
class McpClient:
    connected: bool         # subprocess alive?
    tools: list[McpTool]    # discovered tools

    async def connect()     # start subprocess + initialize
    async def disconnect()  # terminate subprocess
    async def call_tool(name, arguments) -> dict
```

A background `_read_loop` task reads JSON-RPC responses from stdout and resolves pending futures by request ID.

---

## Agent-Facing McpTool

The agent interacts with MCP through a single tool:

| Operation | Args | Behavior |
|-----------|------|----------|
| `servers` | — | List configured servers with connection status |
| `connect` | `server: str` | Connect to a named server, returns available tools |
| `disconnect` | `server: str` | Disconnect from a server |
| `tools` | — | List all tools from connected servers, grouped by server |
| `call` | `tool: str`, `server?: str`, `arguments?: dict` | Invoke a tool; auto-discovers server if not specified |

### Auto-discovery

When calling a tool without specifying a server, the McpTool searches all connected servers for a matching tool name:

```python
matching = [t for t in manager.all_tools() if t.name == tool_name]
server_name = matching[0].server_name
```

---

## Wiring (Session.create)

```python
mcp_manager = McpManager(config.working_dir)
mcp_manager.load_configs()
mcp_tool = registry.get("mcp")
mcp_tool._manager = mcp_manager
```

On session close, all MCP servers are disconnected:

```python
await mcp_tool._manager.disconnect_all()
```

---

## Error Handling

- Missing command binary → `ConnectionError("not found")`
- Server not responding → 30s timeout, returns `None`
- Tool call error → MCP response with `isError: true` mapped to `ToolResult.fail()`
- Config parse errors → logged as warning, server skipped
