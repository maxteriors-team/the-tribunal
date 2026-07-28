"""SSRF regression tests for :class:`WebsiteScraperService`.

All HTTP goes through an ``httpx.MockTransport`` installed on the *real* client
the service builds, so the production client config (notably
``follow_redirects=False``) is exercised rather than a stand-in. DNS is faked;
nothing here touches the network.
"""

from __future__ import annotations

import socket
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.services.scraping import url_guard
from app.services.scraping.url_guard import SAFE_MESSAGE
from app.services.scraping.website_scraper import (
    BlockedURLError,
    WebsiteScraperError,
    WebsiteScraperService,
)

_FAKE_DNS: dict[str, list[str]] = {
    "example.com": ["93.184.216.34"],
    "evil.test": ["93.184.216.34"],  # public host that redirects inward
    "internal.test": ["10.0.0.9"],
}

_PAGE = """
<html><head>
  <title>Acme Plumbing</title>
  <meta name="description" content="Emergency plumbing in Austin, TX">
</head><body>
  <a href="https://www.linkedin.com/company/acme-plumbing">LinkedIn</a>
</body></html>
"""


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake resolver: table lookup, literal IPs resolve to themselves."""

    def _getaddrinfo(host: str, *_args: Any, **_kwargs: Any) -> list[Any]:
        addresses = _FAKE_DNS.get(host)
        if addresses is None:
            if any(ch.isdigit() for ch in host) and (":" in host or host.count(".") == 3):
                addresses = [host]
            else:
                raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, 0)) for addr in addresses]

    monkeypatch.setattr(url_guard.socket, "getaddrinfo", _getaddrinfo)


async def _install_transport(
    scraper: WebsiteScraperService,
    handler: Callable[[httpx.Request], httpx.Response],
) -> list[str]:
    """Swap the live transport of the service's real client for a mock.

    Returns a list that records every URL the transport was actually asked for,
    which is how we assert a blocked hop never reached the wire.
    """
    requested: list[str] = []

    def _record(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return handler(request)

    client = await scraper._get_client()
    client._transport = httpx.MockTransport(_record)
    return requested


@pytest.mark.asyncio
async def test_client_does_not_follow_redirects_itself() -> None:
    """The guard depends on httpx not chasing redirects behind its back."""
    scraper = WebsiteScraperService()
    try:
        client = await scraper._get_client()
        assert client.follow_redirects is False
    finally:
        await scraper.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://10.0.0.5/admin",
        "file:///etc/passwd",
        "internal.test",  # bare host normalizes to https:// then resolves private
    ],
)
async def test_blocked_urls_never_reach_the_wire(url: str) -> None:
    scraper = WebsiteScraperService()
    try:
        requested = await _install_transport(scraper, lambda _r: httpx.Response(200, text="SECRET"))
        with pytest.raises(BlockedURLError) as excinfo:
            await scraper.scrape_website(url)
        assert str(excinfo.value) == SAFE_MESSAGE
        assert requested == []
    finally:
        await scraper.close()


@pytest.mark.asyncio
async def test_redirect_from_public_to_private_is_blocked() -> None:
    """A public host 302'ing to the IMDS address must not be followed."""
    metadata = "http://169.254.169.254/latest/meta-data/iam/security-credentials/"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "evil.test":
            return httpx.Response(302, headers={"location": metadata})
        return httpx.Response(200, text="AWS_SECRET_ACCESS_KEY=leaked")

    scraper = WebsiteScraperService()
    try:
        requested = await _install_transport(scraper, handler)
        with pytest.raises(BlockedURLError) as excinfo:
            await scraper.scrape_website("https://evil.test/start")
        assert str(excinfo.value) == SAFE_MESSAGE
        # The redirect target must never have been fetched.
        assert requested == ["https://evil.test/start"]
    finally:
        await scraper.close()


@pytest.mark.asyncio
async def test_relative_redirect_to_public_host_is_followed() -> None:
    """Legitimate redirects still work, and are resolved relative to the hop."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(301, headers={"location": "/final"})
        return httpx.Response(200, text=_PAGE)

    scraper = WebsiteScraperService()
    try:
        requested = await _install_transport(scraper, handler)
        result = await scraper.scrape_website("https://example.com/start")
        assert result["website_meta"]["title"] == "Acme Plumbing"
        assert requested == ["https://example.com/start", "https://example.com/final"]
    finally:
        await scraper.close()


@pytest.mark.asyncio
async def test_redirect_loop_is_bounded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://example.com/loop"})

    scraper = WebsiteScraperService(max_retries=1, max_redirects=2)
    try:
        await _install_transport(scraper, handler)
        with pytest.raises(WebsiteScraperError) as excinfo:
            await scraper.scrape_website("https://example.com/loop")
        assert "Too many redirects" in str(excinfo.value)
    finally:
        await scraper.close()


@pytest.mark.asyncio
async def test_public_url_still_scrapes() -> None:
    scraper = WebsiteScraperService()
    try:
        await _install_transport(scraper, lambda _r: httpx.Response(200, text=_PAGE))
        result = await scraper.scrape_website("example.com")

        assert result["website_meta"]["title"] == "Acme Plumbing"
        assert result["website_meta"]["description"] == "Emergency plumbing in Austin, TX"
        assert (
            result["social_links"]["linkedin"] == "https://www.linkedin.com/company/acme-plumbing"
        )
        assert "Acme Plumbing" in result["html_content"]
    finally:
        await scraper.close()


@pytest.mark.asyncio
async def test_upstream_error_text_is_not_echoed() -> None:
    """Transport failures must not hand upstream/network text to callers."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[Errno 111] Connection refused to 10.0.0.9:6379")

    scraper = WebsiteScraperService(max_retries=1)
    try:
        await _install_transport(scraper, handler)
        with pytest.raises(WebsiteScraperError) as excinfo:
            await scraper.scrape_website("https://example.com")
        message = str(excinfo.value)
        assert "10.0.0.9" not in message
        assert "Connection refused" not in message
    finally:
        await scraper.close()
