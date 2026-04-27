"""MCP tool — manage and invoke MCP server tools.

Provides the agent with access to external MCP servers.
The agent can list servers, connect/disconnect, browse available
tools, and invoke tools on connected servers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from taui.tools.base import ToolCategory, ToolResult


@dataclass
class McpTool:
    """Interface to external MCP servers and their tools.

    Operations:
        servers  — list configured MCP servers and their status
        connect  — connect to a server
        disconnect — disconnect from a server
        tools    — list tools from connected servers
        call     — invoke a tool on a connected server
    """

    name: str = "mcp"
    description: str = (
        "Manage external MCP servers and invoke their tools. "
        "Operations: servers (list configured), connect, disconnect, "
        "tools (list available), call (invoke a tool on a server)."
    )
    category: ToolCategory = ToolCategory.AGENT
    guidelines: str = (
        "Use `mcp servers` to see what external tools are available. "
        "Connect to a server before calling its tools. "
        "MCP tools extend your capabilities beyond built-in tools."
    )
    schema: dict[str, Any] = field(default=None)  # type: ignore[assignment]

    # Injected by Session.create()
    _manager: Any = None  # McpManager

    def __post_init__(self):
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "description": (
                            "Operation: servers, connect, disconnect, tools, call."
                        ),
                    },
                    "server": {
                        "type": "string",
                        "description": "Server name (for connect/disconnect/call).",
                    },
                    "tool": {
                        "type": "string",
                        "description": "Tool name (for call operation).",
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Arguments for the tool call.",
                    },
                },
                "required": ["operation"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        op = arguments.get("operation")
        if not isinstance(op, str):
            return ToolResult.fail(
                "'operation' is required (servers, connect, disconnect, tools, call)."
            )

        if self._manager is None:
            return ToolResult.fail("MCP system not configured.")

        match op:
            case "servers":
                return self._servers()
            case "connect":
                return await self._connect(arguments)
            case "disconnect":
                return await self._disconnect(arguments)
            case "tools":
                return self._tools()
            case "call":
                return await self._call(arguments)
            case _:
                return ToolResult.fail(
                    f"Unknown operation '{op}'. "
                    "Use: servers, connect, disconnect, tools, call."
                )

    def _servers(self) -> ToolResult:
        """List configured MCP servers."""
        names = self._manager.server_names
        if not names:
            return ToolResult.ok(
                "No MCP servers configured.\n"
                "Add servers to .taui/mcp.toml or ~/.config/taui/mcp.toml"
            )

        connected = set(self._manager.connected_servers)
        lines = [f"MCP servers ({len(names)}):"]
        for name in names:
            status = " [connected]" if name in connected else ""
            lines.append(f"  - {name}{status}")
        return ToolResult.ok("\n".join(lines), count=len(names))

    async def _connect(self, arguments: dict[str, Any]) -> ToolResult:
        """Connect to an MCP server."""
        server = arguments.get("server")
        if not isinstance(server, str) or not server.strip():
            return ToolResult.fail("'server' name is required for connect.")

        try:
            client = await self._manager.connect(server)
            tool_count = len(client.tools)
            tool_names = [t.name for t in client.tools]
            return ToolResult.ok(
                f"Connected to '{server}' — {tool_count} tools available: "
                f"{', '.join(tool_names)}",
                server=server,
                tools=tool_names,
            )
        except ValueError as e:
            return ToolResult.fail(str(e))
        except ConnectionError as e:
            return ToolResult.fail(f"Connection failed: {e}")
        except Exception as e:
            return ToolResult.fail(f"Failed to connect to '{server}': {e}")

    async def _disconnect(self, arguments: dict[str, Any]) -> ToolResult:
        """Disconnect from an MCP server."""
        server = arguments.get("server")
        if not isinstance(server, str) or not server.strip():
            return ToolResult.fail("'server' name is required for disconnect.")

        client = self._manager.get_client(server)
        if client is None:
            return ToolResult.fail(f"Server '{server}' is not connected.")

        try:
            await client.disconnect()
            return ToolResult.ok(f"Disconnected from '{server}'.", server=server)
        except Exception as e:
            return ToolResult.fail(f"Error disconnecting from '{server}': {e}")

    def _tools(self) -> ToolResult:
        """List tools from all connected servers."""
        tools = self._manager.all_tools()
        if not tools:
            connected = self._manager.connected_servers
            if not connected:
                return ToolResult.ok(
                    "No MCP servers connected. Use 'connect' first."
                )
            return ToolResult.ok("Connected servers have no tools.")

        lines = [f"MCP tools ({len(tools)}):"]
        by_server: dict[str, list] = {}
        for t in tools:
            by_server.setdefault(t.server_name, []).append(t)

        for server, server_tools in sorted(by_server.items()):
            lines.append(f"\n  [{server}]")
            for t in server_tools:
                desc = t.description[:60] + "..." if len(t.description) > 60 else t.description
                lines.append(f"    - {t.name}: {desc}")

        return ToolResult.ok("\n".join(lines), count=len(tools))

    async def _call(self, arguments: dict[str, Any]) -> ToolResult:
        """Call a tool on a connected MCP server."""
        server_name = arguments.get("server")
        tool_name = arguments.get("tool")
        tool_args = arguments.get("arguments", {})

        if not isinstance(tool_name, str) or not tool_name.strip():
            return ToolResult.fail("'tool' name is required for call.")

        # If server not specified, find it from tool name
        if not server_name:
            all_tools = self._manager.all_tools()
            matching = [t for t in all_tools if t.name == tool_name]
            if not matching:
                return ToolResult.fail(
                    f"Tool '{tool_name}' not found on any connected server."
                )
            server_name = matching[0].server_name

        client = self._manager.get_client(server_name)
        if client is None:
            return ToolResult.fail(f"Server '{server_name}' is not connected.")

        try:
            result = await client.call_tool(tool_name, tool_args)

            # Extract text content from MCP response
            content_parts = result.get("content", [])
            if isinstance(content_parts, list):
                texts = []
                for part in content_parts:
                    if isinstance(part, dict) and part.get("type") == "text":
                        texts.append(part.get("text", ""))
                output = "\n".join(texts) if texts else str(result)
            else:
                output = str(result)

            is_error = result.get("isError", False)
            if is_error:
                return ToolResult.fail(output, server=server_name, tool=tool_name)
            return ToolResult.ok(output, server=server_name, tool=tool_name)

        except Exception as e:
            return ToolResult.fail(
                f"MCP tool call failed: {e}",
                server=server_name,
                tool=tool_name,
            )
