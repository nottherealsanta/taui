"""MCP tool — manage and invoke MCP server tools.

Provides the agent with access to external MCP servers.
The agent can list servers, connect/disconnect, browse available
tools, and invoke tools on connected servers.  The ``tools``, ``call``,
``inspect``, and ``search`` operations auto-connect configured servers
on demand so an explicit ``connect`` step is never required.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from taui.tools.base import ToolCategory, ToolResult


@dataclass
class McpTool:
    """Interface to external MCP servers and their tools.

    Operations:
        servers    — list configured MCP servers and their status
        connect    — connect to a server
        disconnect — disconnect from a server
        tools      — list tools (optionally for one server; auto-connects)
        call       — invoke a tool on a server (auto-connects)
        inspect    — show full schema for a single tool (auto-connects)
        search     — keyword search across tool names/descriptions (auto-connects)
    """

    name: str = "mcp"
    description: str = (
        "Manage external MCP servers and invoke their tools. "
        "Operations: servers (list configured), connect, disconnect, "
        "tools (list available, optionally for one server; auto-connects), "
        "call (invoke a tool on a server), "
        "inspect (full schema for one tool; requires server+tool), "
        "search (keyword search over tool names/descriptions; optionally scoped to server)."
    )
    category: ToolCategory = ToolCategory.AGENT
    guidelines: str = (
        "Use `mcp servers` to see what external tools are available. "
        "You can call tools directly — servers are auto-connected on demand. "
        "Use `inspect` to get the full input schema for a specific tool before calling it. "
        "Use `search` to find tools by keyword across all connected servers. "
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
                        "enum": [
                            "servers",
                            "connect",
                            "disconnect",
                            "tools",
                            "call",
                            "inspect",
                            "search",
                        ],
                        "description": (
                            "Operation: servers, connect, disconnect, tools, call, "
                            "inspect (full schema for one tool), "
                            "search (keyword search over tool names/descriptions)."
                        ),
                    },
                    "server": {
                        "type": "string",
                        "description": (
                            "Server name (for connect/disconnect/call/inspect, "
                            "or to filter tools/search)."
                        ),
                    },
                    "tool": {
                        "type": "string",
                        "description": "Tool name (for call and inspect operations).",
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Arguments for the tool call.",
                    },
                    "query": {
                        "type": "string",
                        "description": (
                            "Keyword query for the search operation "
                            "(case-insensitive match against tool names and descriptions)."
                        ),
                    },
                },
                "required": ["operation"],
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        op = arguments.get("operation")
        if not isinstance(op, str):
            return ToolResult.fail(
                "'operation' is required "
                "(servers, connect, disconnect, tools, call, inspect, search)."
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
                return await self._tools(arguments)
            case "call":
                return await self._call(arguments)
            case "inspect":
                return await self._inspect(arguments)
            case "search":
                return await self._search(arguments)
            case _:
                return ToolResult.fail(
                    f"Unknown operation '{op}'. "
                    "Use: servers, connect, disconnect, tools, call, inspect, search."
                )

    # ── helpers ────────────────────────────────────────────────────────────

    async def _ensure_connected(self, server: str) -> str | None:
        """Connect a configured server on demand.

        Returns an error string, or ``None`` on success.
        """
        if server in self._manager.connected_servers:
            return None
        if server not in self._manager.server_names:
            return f"Unknown MCP server: {server!r}"
        try:
            await self._manager.connect(server)
            return None
        except ValueError as e:  # disabled / unknown
            return str(e)
        except ConnectionError as e:
            return f"Connection failed for '{server}': {e}"
        except Exception as e:
            return f"Failed to connect to '{server}': {e}"

    # ── operations ─────────────────────────────────────────────────────────

    def _servers(self) -> ToolResult:
        """List configured MCP servers."""
        names = self._manager.server_names
        if not names:
            return ToolResult.ok(
                "No MCP servers configured.\n"
                "Add servers to .taui/mcp.toml or ~/.taui/mcp.toml"
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

    async def _tools(self, arguments: dict[str, Any]) -> ToolResult:
        """List tools — optionally filtered to a single server.

        Auto-connects configured servers on demand so no prior ``connect``
        is needed.
        """
        server = arguments.get("server")

        if server:
            # Single-server mode: auto-connect that one server.
            err = await self._ensure_connected(server)
            if err:
                return ToolResult.fail(err)

            client = self._manager.get_client(server)
            if client is None:
                return ToolResult.fail(f"Server '{server}' is not connected.")

            tools = client.tools
            if not tools:
                return ToolResult.ok(f"Server '{server}' exposes no tools.")

            lines = [f"MCP tools from [{server}] ({len(tools)}):"]
            for t in tools:
                desc = (
                    t.description[:60] + "..."
                    if len(t.description) > 60
                    else t.description
                )
                lines.append(f"  - {t.name}: {desc}")
            return ToolResult.ok("\n".join(lines), count=len(tools))

        # All-servers mode: bring up every configured server.
        names = self._manager.server_names
        if not names:
            return ToolResult.ok(
                "No MCP servers configured.\n"
                "Add servers to .taui/mcp.toml or ~/.taui/mcp.toml"
            )

        await self._manager.connect_all()

        tools = self._manager.all_tools()
        if not tools:
            if not self._manager.connected_servers:
                return ToolResult.fail(
                    "Failed to connect to any configured MCP servers."
                )
            return ToolResult.ok("Connected servers expose no tools.")

        lines = [f"MCP tools ({len(tools)}):"]
        by_server: dict[str, list] = {}
        for t in tools:
            by_server.setdefault(t.server_name, []).append(t)

        for srv, server_tools in sorted(by_server.items()):
            lines.append(f"\n  [{srv}]")
            for t in server_tools:
                desc = (
                    t.description[:60] + "..."
                    if len(t.description) > 60
                    else t.description
                )
                lines.append(f"    - {t.name}: {desc}")

        return ToolResult.ok("\n".join(lines), count=len(tools))

    async def _call(self, arguments: dict[str, Any]) -> ToolResult:
        """Call a tool on an MCP server (auto-connects on demand)."""
        server_name = arguments.get("server")
        tool_name = arguments.get("tool")
        tool_args = arguments.get("arguments", {})

        if not isinstance(tool_name, str) or not tool_name.strip():
            return ToolResult.fail("'tool' name is required for call.")

        # If server specified, auto-connect it.
        if server_name:
            err = await self._ensure_connected(server_name)
            if err:
                return ToolResult.fail(err)
        else:
            # No server specified — connect all, then resolve by tool name.
            await self._manager.connect_all()
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

    async def _inspect(self, arguments: dict[str, Any]) -> ToolResult:
        """Return the full schema for a single tool on a given server."""
        server = arguments.get("server")
        tool_name = arguments.get("tool")

        if not isinstance(server, str) or not server.strip():
            return ToolResult.fail("'server' name is required for inspect.")
        if not isinstance(tool_name, str) or not tool_name.strip():
            return ToolResult.fail("'tool' name is required for inspect.")

        err = await self._ensure_connected(server)
        if err:
            return ToolResult.fail(err)

        client = self._manager.get_client(server)
        if client is None:
            return ToolResult.fail(f"Server '{server}' is not connected.")

        tools = client.tools
        match = next((t for t in tools if t.name == tool_name), None)
        if match is None:
            available = ", ".join(t.name for t in tools) if tools else "(none)"
            return ToolResult.fail(
                f"Tool '{tool_name}' not found on server '{server}'. "
                f"Available tools: {available}"
            )

        schema_str = json.dumps(match.input_schema, indent=2)
        lines = [
            f"Tool: {match.name}",
            f"Server: {server}",
            f"Description: {match.description}",
            "Input schema:",
            schema_str,
        ]
        return ToolResult.ok("\n".join(lines), server=server, tool=tool_name)

    async def _search(self, arguments: dict[str, Any]) -> ToolResult:
        """Case-insensitive keyword search over tool names and descriptions.

        Auto-connects all configured servers (or just the specified server).
        Returns matching tools as ``server/tool — first line of description``.
        """
        query = arguments.get("query")
        server = arguments.get("server")

        if not isinstance(query, str) or not query.strip():
            return ToolResult.fail("'query' string is required for search.")

        needle = query.lower()

        if server:
            # Scope to one server.
            err = await self._ensure_connected(server)
            if err:
                return ToolResult.fail(err)
            client = self._manager.get_client(server)
            if client is None:
                return ToolResult.fail(f"Server '{server}' is not connected.")
            candidates = client.tools
        else:
            # All servers — mirror the behaviour of the `tools` operation.
            names = self._manager.server_names
            if not names:
                return ToolResult.ok(
                    "No MCP servers configured.\n"
                    "Add servers to .taui/mcp.toml or ~/.taui/mcp.toml"
                )
            await self._manager.connect_all()
            candidates = self._manager.all_tools()
            if not candidates and not self._manager.connected_servers:
                return ToolResult.fail(
                    "Failed to connect to any configured MCP servers."
                )

        matches = [
            t
            for t in candidates
            if needle in t.name.lower() or needle in t.description.lower()
        ]

        if not matches:
            scope = f" on server '{server}'" if server else ""
            return ToolResult.ok(f"No tools matching '{query}'{scope}.")

        lines = [f"Tools matching '{query}' ({len(matches)}):"]
        for t in matches:
            first_line = t.description.split("\n")[0]
            lines.append(f"  {t.server_name}/{t.name} — {first_line}")
        return ToolResult.ok("\n".join(lines), count=len(matches))
