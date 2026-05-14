"""Webfetch tool — retrieve and cache web content."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taui.tools.base import ToolCategory, ToolResult

try:
    import httpx as _httpx
except ImportError:  # pragma: no cover
    _httpx = None  # type: ignore[assignment]


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

        # Fetch
        try:
            if _httpx is None:
                return ToolResult.fail("httpx not available for web fetching.")
            async with _httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                content = resp.text[:max_bytes]
        except Exception as exc:
            return ToolResult.fail(f"Failed to fetch {url}: {exc}")

        # Cache and return
        self._set_cached(url, content)
        return ToolResult.ok(f"{url}\n\n{content}")
