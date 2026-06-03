"""Tests for WebfetchTool."""

from __future__ import annotations

import ipaddress
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import taui.tools.builtins.webfetch as _wf_mod
from taui.tools.builtins.webfetch import WebfetchTool, _blocked_reason


@contextmanager
def _no_dns(ip: str = "93.184.216.34"):
    """Avoid real DNS: literal IPs resolve to themselves, names to a public IP."""

    def fake(host: str):
        try:
            return [ipaddress.ip_address(host)]
        except ValueError:
            return [ipaddress.ip_address(ip)]

    with patch.object(_wf_mod, "_resolve_host_ips", fake):
        yield


def _make_mock_httpx(
    response_text: str = "Hello World", url: str = "https://example.com"
) -> MagicMock:
    mock_response = MagicMock()
    mock_response.text = response_text
    mock_response.url = url
    mock_response.raise_for_status = lambda: None

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    mock_httpx = MagicMock()
    mock_httpx.AsyncClient.return_value = mock_client
    return mock_httpx


class TestWebfetchTool:
    async def test_cache_miss_and_hit(self, tmp_path):
        tool = WebfetchTool()
        tool.working_dir = tmp_path

        with patch.object(_wf_mod, "_httpx", _make_mock_httpx()), _no_dns():
            result = await tool.execute({"url": "https://example.com"})
            assert not result.error
            assert "Hello World" in result.content

            # Second call should hit cache (no httpx needed)
            result2 = await tool.execute({"url": "https://example.com"})
            assert not result2.error
            assert "[cached]" in result2.content

    async def test_missing_url(self, tmp_path):
        tool = WebfetchTool()
        tool.working_dir = tmp_path
        result = await tool.execute({})
        assert result.error

    async def test_cache_dir_created(self, tmp_path):
        tool = WebfetchTool()
        tool.working_dir = tmp_path
        tool._set_cached("https://example.com", "data")
        assert (tmp_path / ".taui" / "cache" / "web").is_dir()

    async def test_expired_cache_returns_none(self, tmp_path):
        import json
        import time

        tool = WebfetchTool()
        tool.working_dir = tmp_path
        tool._cache_ttl = 1

        cache_dir = tmp_path / ".taui" / "cache" / "web"
        cache_dir.mkdir(parents=True)
        key = tool._cache_key("https://example.com")
        old_data = {"url": "https://example.com", "content": "old", "fetched_at": time.time() - 10}
        (cache_dir / f"{key}.json").write_text(json.dumps(old_data))

        assert tool._get_cached("https://example.com") is None

    async def test_max_bytes_truncates(self, tmp_path):
        tool = WebfetchTool()
        tool.working_dir = tmp_path
        tool._set_cached("https://example.com", "A" * 1000)

        result = await tool.execute({"url": "https://example.com", "max_bytes": 10})
        assert not result.error
        # Content after header should be truncated
        assert len(result.content) < 200  # much less than 1000

    async def test_fetch_error_returns_fail(self, tmp_path):
        tool = WebfetchTool()
        tool.working_dir = tmp_path

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch.object(_wf_mod, "_httpx", mock_httpx), _no_dns():
            result = await tool.execute({"url": "https://example.com"})
            assert result.error
            assert "connection refused" in result.content


class TestWebfetchSSRF:
    def test_blocked_reason_link_local_metadata(self):
        # AWS/GCP/Azure instance metadata — credential theft vector.
        reason = _blocked_reason("http://169.254.169.254/latest/meta-data/")
        assert reason is not None
        assert "link-local" in reason

    def test_blocked_reason_non_http_scheme(self):
        assert _blocked_reason("file:///etc/passwd") is not None
        assert _blocked_reason("gopher://x/") is not None

    def test_blocked_reason_allows_loopback_and_private(self):
        # Dev use: fetching a local server stays allowed.
        assert _blocked_reason("http://127.0.0.1:8080/") is None
        assert _blocked_reason("http://192.168.1.10/") is None

    async def test_execute_blocks_link_local(self, tmp_path):
        tool = WebfetchTool()
        tool.working_dir = tmp_path
        # No httpx call should happen — the guard fires first.
        with patch.object(_wf_mod, "_httpx", _make_mock_httpx()):
            result = await tool.execute(
                {"url": "http://169.254.169.254/latest/meta-data/"}
            )
        assert result.error
        assert "link-local" in result.content

    async def test_execute_blocks_redirect_to_link_local(self, tmp_path):
        tool = WebfetchTool()
        tool.working_dir = tmp_path
        # Initial host is public, but the response landed on a link-local host.
        mock_httpx = _make_mock_httpx(url="http://169.254.169.254/")
        with patch.object(_wf_mod, "_httpx", mock_httpx), _no_dns():
            result = await tool.execute({"url": "https://innocent.example"})
        assert result.error
        assert "link-local" in result.content
