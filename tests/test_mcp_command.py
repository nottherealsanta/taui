"""Tests for the /mcp slash command."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from taui.commands.builtins import McpCommand
from taui.commands.registry import CommandContext


# ── Fakes ──────────────────────────────────────────────────────────────────


@dataclass
class _FakeTool:
    name: str


@dataclass
class _FakeClient:
    _tools: list[_FakeTool] = field(default_factory=list)
    _connected: bool = True

    @property
    def tools(self) -> list[_FakeTool]:
        return list(self._tools)

    @property
    def connected(self) -> bool:
        return self._connected

    async def disconnect(self) -> None:
        self._connected = False


class _FakeMcpManager:
    def __init__(
        self,
        configs: dict[str, list[str]] | None = None,
        connected: list[str] | None = None,
    ) -> None:
        self._configs = configs or {}
        self._connected = set(connected or [])
        self._clients: dict[str, _FakeClient] = {}
        for name, tools in self._configs.items():
            client = _FakeClient(
                _tools=[_FakeTool(t) for t in tools],
                _connected=(name in self._connected),
            )
            self._clients[name] = client

    @property
    def server_names(self) -> list[str]:
        return sorted(self._configs)

    @property
    def connected_servers(self) -> list[str]:
        return [n for n in self._clients if self._clients[n].connected]

    def get_client(self, name: str) -> _FakeClient | None:
        client = self._clients.get(name)
        if client and client.connected:
            return client
        return None

    async def connect(self, name: str) -> _FakeClient:
        if name not in self._configs:
            raise ValueError(f"Unknown MCP server: {name!r}")
        client = self._clients[name]
        client._connected = True
        return client

    async def connect_all(self) -> list[str]:
        connected: list[str] = []
        for name in self._configs:
            client = self._clients[name]
            client._connected = True
            connected.append(name)
        return connected


def _make_cmd(
    mgr: _FakeMcpManager | None = None,
) -> McpCommand:
    cmd = McpCommand()
    session = SimpleNamespace(_mcp_manager=mgr)
    cmd._get_session = lambda: session
    return cmd


def _ctx(*args: str) -> CommandContext:
    return CommandContext(
        raw_input=" ".join(["mcp", *args]),
        args=list(args),
    )


# ── /mcp list ──────────────────────────────────────────────────────────────


class TestMcpList:
    async def test_list_default_no_args(self):
        mgr = _FakeMcpManager(
            configs={"github": ["search", "clone"], "fs": ["read"]},
            connected=["github"],
        )
        cmd = _make_cmd(mgr)
        result = await cmd.execute(_ctx())
        assert not result.error
        assert "github" in result.output
        assert "[connected]" in result.output
        assert "fs" in result.output
        # fs should not say connected
        for line in result.output.splitlines():
            if "fs" in line and "github" not in line:
                assert "[connected]" not in line

    async def test_list_explicit(self):
        mgr = _FakeMcpManager(configs={"demo": ["tool1"]}, connected=["demo"])
        cmd = _make_cmd(mgr)
        result = await cmd.execute(_ctx("list"))
        assert not result.error
        assert "demo" in result.output

    async def test_list_no_servers(self):
        cmd = _make_cmd(_FakeMcpManager())
        result = await cmd.execute(_ctx())
        assert not result.error
        assert "No MCP servers configured" in result.output


# ── /mcp connect ───────────────────────────────────────────────────────────


class TestMcpConnect:
    async def test_connect_single(self):
        mgr = _FakeMcpManager(
            configs={"github": ["search"]}, connected=[],
        )
        cmd = _make_cmd(mgr)
        result = await cmd.execute(_ctx("connect", "github"))
        assert not result.error
        assert "Connected" in result.output
        assert result.metadata.get("action") == "mcp_refresh"

    async def test_connect_all(self):
        mgr = _FakeMcpManager(
            configs={"a": ["t1"], "b": ["t2"]}, connected=[],
        )
        cmd = _make_cmd(mgr)
        result = await cmd.execute(_ctx("connect"))
        assert not result.error
        assert "a" in result.output and "b" in result.output
        assert result.metadata.get("action") == "mcp_refresh"

    async def test_connect_unknown(self):
        cmd = _make_cmd(_FakeMcpManager())
        result = await cmd.execute(_ctx("connect", "nope"))
        assert result.error
        assert "Unknown" in result.output


# ── /mcp disconnect ────────────────────────────────────────────────────────


class TestMcpDisconnect:
    async def test_disconnect(self):
        mgr = _FakeMcpManager(
            configs={"github": ["search"]}, connected=["github"],
        )
        cmd = _make_cmd(mgr)
        result = await cmd.execute(_ctx("disconnect", "github"))
        assert not result.error
        assert "Disconnected" in result.output
        assert result.metadata.get("action") == "mcp_refresh"

    async def test_disconnect_not_connected(self):
        mgr = _FakeMcpManager(
            configs={"github": ["search"]}, connected=[],
        )
        cmd = _make_cmd(mgr)
        result = await cmd.execute(_ctx("disconnect", "github"))
        assert result.error
        assert "not connected" in result.output

    async def test_disconnect_missing_name(self):
        cmd = _make_cmd(_FakeMcpManager())
        result = await cmd.execute(_ctx("disconnect"))
        assert result.error
        assert "Usage" in result.output


# ── Error cases ────────────────────────────────────────────────────────────


class TestMcpErrors:
    async def test_no_session(self):
        cmd = McpCommand()
        result = await cmd.execute(_ctx())
        assert result.error
        assert "No session" in result.output

    async def test_no_manager(self):
        cmd = McpCommand()
        session = SimpleNamespace()  # no _mcp_manager
        cmd._get_session = lambda: session
        result = await cmd.execute(_ctx())
        assert result.error
        assert "not configured" in result.output

    async def test_unknown_subcommand(self):
        cmd = _make_cmd(_FakeMcpManager())
        result = await cmd.execute(_ctx("bogus"))
        assert result.error
        assert "Unknown subcommand" in result.output
