"""Webfetch tool — retrieve and cache web content."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from taui.tools.base import ToolCategory, ToolResult

try:
    import httpx as _httpx
except ImportError:  # pragma: no cover
    _httpx = None  # type: ignore[assignment]


def _resolve_host_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve a host to IP addresses. Returns [] if resolution fails."""
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []
    out: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        try:
            out.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            pass
    return out


def _blocked_reason(url: str) -> str | None:
    """Return a reason if ``url`` must not be fetched (SSRF guard), else None.

    Blocks non-http(s) schemes and link-local targets — the cloud metadata
    range (169.254.0.0/16, fe80::/10), e.g. 169.254.169.254, which would leak
    instance credentials. Loopback and private addresses are intentionally
    allowed so the dev use of fetching a local server keeps working.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Only http(s) URLs may be fetched (got scheme {parsed.scheme or 'none'!r})."
    host = parsed.hostname
    if not host:
        return "URL has no host."
    for ip in _resolve_host_ips(host):
        if ip.is_link_local:
            return (
                f"Refusing to fetch link-local address {ip} (host {host!r}); "
                "this is the cloud-metadata range."
            )
    return None


@dataclass
class WebfetchTool:
    """Fetch and cache web content for context gathering."""

    name: str = "webfetch"
    description: str = (
        "Fetch content from a URL. Results are cached locally. "
        "Use to read documentation, API references, or other web content."
    )
    category: ToolCategory = ToolCategory.FILE_READ
    schema: dict[str, Any] = field(default=None)
    working_dir: Path | None = field(default=None, repr=False)
    _cache_ttl: int = 3600  # 1 hour default

    def __post_init__(self) -> None:
        if self.schema is None:
            self.schema = {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch.",
                    },
                    "max_bytes": {
                        "type": "integer",
                        "description": "Max response bytes to return. Default 32768.",
                    },
                },
                "required": ["url"],
            }

    def _cache_dir(self) -> Path:
        base = self.working_dir or Path(".")
        return base / ".taui" / "cache" / "web"

    def _cache_key(self, url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    def _get_cached(self, url: str) -> str | None:
        cache_dir = self._cache_dir()
        key = self._cache_key(url)
        cache_file = cache_dir / f"{key}.json"
        if not cache_file.exists():
            return None
        try:
            data = json.loads(cache_file.read_text())
            if time.time() - data.get("fetched_at", 0) > self._cache_ttl:
                return None
            return data.get("content", "")
        except (json.JSONDecodeError, OSError):
            return None

    def _set_cached(self, url: str, content: str) -> None:
        cache_dir = self._cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        key = self._cache_key(url)
        cache_file = cache_dir / f"{key}.json"
        data = {"url": url, "content": content, "fetched_at": time.time()}
        cache_file.write_text(json.dumps(data))

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        url = arguments.get("url", "")
        if not url:
            return ToolResult.fail("URL is required.")

        max_bytes = arguments.get("max_bytes", 32768)

        # Check cache
        cached = self._get_cached(url)
        if cached is not None:
            content = cached[:max_bytes]
            return ToolResult.ok(
                f"[cached] {url}\n\n{content}",
                cached=True,
            )

        # SSRF guard — only on an actual fetch (cache hits are already vetted).
        if (blocked := _blocked_reason(url)) is not None:
            return ToolResult.fail(blocked)

        # Fetch
        try:
            if _httpx is None:
                return ToolResult.fail("httpx not available for web fetching.")
            async with _httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(url)
                # A redirect may have landed on a blocked host; don't return its
                # body to the agent even though the request was already made.
                if (blocked := _blocked_reason(str(resp.url))) is not None:
                    return ToolResult.fail(blocked)
                resp.raise_for_status()
                content = resp.text[:max_bytes]
        except Exception as exc:
            return ToolResult.fail(f"Failed to fetch {url}: {exc}")

        # Cache and return
        self._set_cached(url, content)
        return ToolResult.ok(f"{url}\n\n{content}")
