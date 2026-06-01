"""Manages LSP server lifecycles — one client per language."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from taui.lsp.client import LspClient
from taui.lsp.types import (
    Diagnostic,
    HoverResult,
    Location,
    Position,
    Range,
    SymbolInfo,
)

log = logging.getLogger(__name__)

# Default server commands keyed by language id.
# Users can override via settings later.
_DEFAULT_SERVERS: dict[str, list[str]] = {
    "python": ["pylsp"],
    "typescript": ["typescript-language-server", "--stdio"],
    "javascript": ["typescript-language-server", "--stdio"],
    "rust": ["rust-analyzer"],
    "go": ["gopls"],
    "c": ["clangd"],
    "cpp": ["clangd"],
}


class LspManager:
    """Manages multiple LSP clients, one per language."""

    def __init__(self, root_dir: str | Path) -> None:
        self._root = Path(root_dir).resolve()
        self._root_uri = self._root.as_uri()
        self._clients: dict[str, LspClient] = {}
        self._custom_servers: dict[str, list[str]] = {}

    def configure_server(self, language_id: str, cmd: list[str]) -> None:
        self._custom_servers[language_id] = cmd

    async def _get_client(self, language_id: str) -> LspClient:
        if language_id in self._clients and self._clients[language_id].alive:
            return self._clients[language_id]

        cmd = self._custom_servers.get(language_id) or _DEFAULT_SERVERS.get(language_id)
        if not cmd:
            raise ValueError(
                f"No LSP server configured for language '{language_id}'. "
                f"Known languages: {sorted(set(_DEFAULT_SERVERS) | set(self._custom_servers))}"
            )

        client = LspClient(cmd, cwd=str(self._root))
        await client.start(self._root_uri)
        self._clients[language_id] = client
        return client

    async def stop_all(self) -> None:
        if self._clients:
            results = await asyncio.gather(
                *(c.stop() for c in self._clients.values()),
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, Exception):
                    log.debug("Error stopping LSP client", exc_info=r)
            self._clients.clear()

    # ------------------------------------------------------------------
    # high-level operations
    # ------------------------------------------------------------------

    async def go_to_definition(
        self, language_id: str, file: str, line: int, character: int
    ) -> list[Location]:
        client = await self._get_client(language_id)
        uri = Path(self._root / file).resolve().as_uri()
        result = await client.request(
            "textDocument/definition",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line - 1, "character": character - 1},
            },
        )
        return _parse_locations(result)

    async def find_references(
        self, language_id: str, file: str, line: int, character: int
    ) -> list[Location]:
        client = await self._get_client(language_id)
        uri = Path(self._root / file).resolve().as_uri()
        result = await client.request(
            "textDocument/references",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line - 1, "character": character - 1},
                "context": {"includeDeclaration": True},
            },
        )
        return _parse_locations(result)

    async def hover(
        self, language_id: str, file: str, line: int, character: int
    ) -> HoverResult | None:
        client = await self._get_client(language_id)
        uri = Path(self._root / file).resolve().as_uri()
        result = await client.request(
            "textDocument/hover",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line - 1, "character": character - 1},
            },
        )
        if not result:
            return None
        contents = result.get("contents", "")
        if isinstance(contents, dict):
            contents = contents.get("value", str(contents))
        elif isinstance(contents, list):
            parts = []
            for c in contents:
                parts.append(c.get("value", str(c)) if isinstance(c, dict) else str(c))
            contents = "\n".join(parts)
        rng = _parse_range(result.get("range")) if result.get("range") else None
        return HoverResult(contents=str(contents), range=rng)

    async def document_symbols(
        self, language_id: str, file: str
    ) -> list[SymbolInfo]:
        client = await self._get_client(language_id)
        uri = Path(self._root / file).resolve().as_uri()
        result = await client.request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": uri}},
        )
        if not result:
            return []
        symbols: list[SymbolInfo] = []
        _collect_symbols(result, uri, symbols)
        return symbols

    async def workspace_symbols(
        self, language_id: str, query: str
    ) -> list[SymbolInfo]:
        client = await self._get_client(language_id)
        result = await client.request(
            "workspace/symbol",
            {"query": query},
        )
        if not result:
            return []
        return [_parse_symbol_info(s) for s in result if "location" in s]

    async def go_to_implementation(
        self, language_id: str, file: str, line: int, character: int
    ) -> list[Location]:
        client = await self._get_client(language_id)
        uri = Path(self._root / file).resolve().as_uri()
        result = await client.request(
            "textDocument/implementation",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line - 1, "character": character - 1},
            },
        )
        return _parse_locations(result)

    async def diagnostics(
        self, language_id: str, file: str
    ) -> list[Diagnostic]:
        # textDocument/diagnostic is LSP 3.17. Many servers use publishDiagnostics
        # notification instead. For now try the pull model and fall back gracefully.
        client = await self._get_client(language_id)
        uri = Path(self._root / file).resolve().as_uri()
        try:
            result = await client.request(
                "textDocument/diagnostic",
                {"textDocument": {"uri": uri}},
                timeout=10.0,
            )
        except Exception:
            return []  # server doesn't support pull diagnostics
        items = (result or {}).get("items", [])
        return [_parse_diagnostic(d) for d in items]

    async def call_hierarchy(
        self, language_id: str, file: str, line: int, character: int, *, direction: str = "incoming"
    ) -> list[dict[str, Any]]:
        client = await self._get_client(language_id)
        uri = Path(self._root / file).resolve().as_uri()
        prep = await client.request(
            "textDocument/prepareCallHierarchy",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line - 1, "character": character - 1},
            },
        )
        if not prep:
            return []
        results: list[dict[str, Any]] = []
        method = (
            "callHierarchy/incomingCalls"
            if direction == "incoming"
            else "callHierarchy/outgoingCalls"
        )
        for item in prep:
            calls = await client.request(method, {"item": item})
            for call in calls or []:
                target = call.get("from" if direction == "incoming" else "to", {})
                results.append(
                    {
                        "name": target.get("name", "?"),
                        "kind": target.get("kind", 0),
                        "file": _uri_to_path(target.get("uri", "")),
                        "line": target.get("range", {}).get("start", {}).get("line", 0) + 1,
                    }
                )
        return results


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _uri_to_path(uri: str) -> str:
    if uri.startswith("file://"):
        return uri[7:]
    return uri


def _parse_position(raw: dict[str, Any]) -> Position:
    return Position(line=raw.get("line", 0), character=raw.get("character", 0))


def _parse_range(raw: dict[str, Any]) -> Range:
    return Range(
        start=_parse_position(raw.get("start", {})),
        end=_parse_position(raw.get("end", {})),
    )


def _parse_location(raw: dict[str, Any]) -> Location:
    return Location(
        uri=raw.get("uri", ""),
        range=_parse_range(raw.get("range", {})),
    )


def _parse_locations(raw: Any) -> list[Location]:
    if not raw:
        return []
    if isinstance(raw, dict):
        return [_parse_location(raw)]
    return [_parse_location(loc) for loc in raw]


def _parse_diagnostic(raw: dict[str, Any]) -> Diagnostic:
    return Diagnostic(
        range=_parse_range(raw.get("range", {})),
        message=raw.get("message", ""),
        severity=raw.get("severity", 1),
        source=raw.get("source"),
    )


def _parse_symbol_info(raw: dict[str, Any]) -> SymbolInfo:
    loc = _parse_location(raw.get("location", {}))
    return SymbolInfo(
        name=raw.get("name", ""),
        kind=raw.get("kind", 0),
        location=loc,
        container_name=raw.get("containerName"),
    )


def _collect_symbols(
    items: list[dict[str, Any]], uri: str, out: list[SymbolInfo]
) -> None:
    """Recursively collect symbols from either SymbolInformation or DocumentSymbol."""
    for item in items:
        if "location" in item:
            out.append(_parse_symbol_info(item))
        elif "range" in item:
            # DocumentSymbol — has range but no location
            loc = Location(uri=uri, range=_parse_range(item["range"]))
            out.append(
                SymbolInfo(
                    name=item.get("name", ""),
                    kind=item.get("kind", 0),
                    location=loc,
                )
            )
            children = item.get("children", [])
            if children:
                _collect_symbols(children, uri, out)
