"""SSRF egress guard unit tests.

DNS is always faked — these must never touch the network. The guard is the only
thing standing between client-supplied lead websites and the server's own
private network, so both halves are pinned: the I/O-free scheme/hostname checks
and the resolve-then-classify pass.
"""

from __future__ import annotations

import socket
import threading
from typing import Any

import pytest

from app.services.scraping import url_guard
from app.services.scraping.url_guard import (
    SAFE_MESSAGE,
    UnsafeURLError,
    is_blocked_address,
    validate_outbound_url,
)

# Hostname -> addresses returned by the faked resolver.
_FAKE_DNS: dict[str, list[str]] = {
    "example.com": ["93.184.216.34"],
    "public.test": ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"],
    "localhost": ["127.0.0.1"],
    "internal.test": ["10.4.5.6"],
    "rebind.test": ["93.184.216.34", "127.0.0.1"],  # one public + one private
    "metadata.attacker.test": ["169.254.169.254"],
    "mapped.test": ["::ffff:127.0.0.1"],
}


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace ``socket.getaddrinfo`` with a table lookup; record lookups."""
    looked_up: list[str] = []

    def _getaddrinfo(host: str, *_args: Any, **_kwargs: Any) -> list[Any]:
        looked_up.append(host)
        try:
            addresses = _FAKE_DNS[host]
        except KeyError:
            # Literal IPs resolve to themselves, like the real resolver.
            if any(ch.isdigit() for ch in host) and (":" in host or host.count(".") == 3):
                addresses = [host]
            else:
                raise socket.gaierror(socket.EAI_NONAME, "Name or service not known") from None
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, 0)) for addr in addresses]

    monkeypatch.setattr(url_guard.socket, "getaddrinfo", _getaddrinfo)
    return looked_up


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
        "http://169.254.169.254",
        "http://localhost:8000",
        "http://localhost:8000/internal/admin",
        "http://127.0.0.1",
        "http://127.0.0.1:5432/",
        "http://10.0.0.5/admin",  # RFC1918
        "http://192.168.1.1/",  # RFC1918
        "http://172.16.0.9:9200/_cluster/health",  # RFC1918
        "http://internal.test/secrets",  # resolves into RFC1918
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://metadata/computeMetadata/v1/",
        "http://metadata.google.internal./computeMetadata/v1/",  # trailing dot
        "http://METADATA.GOOGLE.INTERNAL/",  # case
        "http://metadata.attacker.test/",  # public name -> IMDS address
        "http://rebind.test/",  # one public + one private answer
        "http://mapped.test/",  # ::ffff:127.0.0.1
        "http://[::1]:8080/",
        "http://0.0.0.0:8000/",  # noqa: S104 - unspecified address must be blocked
        "http://user@127.0.0.1/",  # userinfo confusion
        "http://nonexistent.invalid/",  # unresolvable -> fail closed
    ],
)
async def test_blocks_non_public_targets(url: str) -> None:
    with pytest.raises(UnsafeURLError):
        await validate_outbound_url(url)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "file://localhost/etc/shadow",
        "gopher://example.com:70/_test",
        "ftp://example.com/secrets.txt",
        "data:text/html,<script>x</script>",
        "redis://example.com:6379/0",
        "//example.com/no-scheme",
        "not-a-url",
    ],
)
async def test_blocks_disallowed_schemes(url: str, fake_dns: list[str]) -> None:
    with pytest.raises(UnsafeURLError) as excinfo:
        await validate_outbound_url(url)
    # Scheme rejection is I/O-free: no DNS lookup should ever be issued.
    assert fake_dns == []
    assert excinfo.value.reason in {"scheme_not_allowed", "missing_host", "malformed_url"}


@pytest.mark.asyncio
async def test_error_message_is_opaque() -> None:
    with pytest.raises(UnsafeURLError) as excinfo:
        await validate_outbound_url("http://internal.test/secrets")

    message = str(excinfo.value)
    assert message == SAFE_MESSAGE
    # No hostname, address, or reason code may leak into the caller-facing text.
    assert "internal.test" not in message
    assert "10.4.5.6" not in message
    assert "non_public_address" not in message
    assert excinfo.value.reason == "non_public_address"


@pytest.mark.asyncio
async def test_dns_failure_fails_closed() -> None:
    with pytest.raises(UnsafeURLError) as excinfo:
        await validate_outbound_url("http://nonexistent.invalid/")
    assert excinfo.value.reason == "dns_resolution_failed"


# ---------------------------------------------------------------------------
# Allowances
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "https://example.com/about-us?utm=1#team",
        "http://example.com/",
        "https://public.test/team",  # public v4 + public v6
    ],
)
async def test_allows_public_urls(url: str) -> None:
    assert await validate_outbound_url(url) == url


@pytest.mark.asyncio
async def test_resolution_runs_off_the_event_loop() -> None:
    """DNS must not block the loop — it has to run in a worker thread."""
    threads: list[str] = []
    original = url_guard.socket.getaddrinfo

    def _record(host: str, *args: Any, **kwargs: Any) -> Any:
        threads.append(threading.current_thread().name)
        return original(host, *args, **kwargs)

    url_guard.socket.getaddrinfo = _record  # type: ignore[assignment]
    try:
        await validate_outbound_url("https://example.com")
    finally:
        url_guard.socket.getaddrinfo = original  # type: ignore[assignment]

    assert threads
    assert threads[0] != threading.main_thread().name


# ---------------------------------------------------------------------------
# Address classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "169.254.169.254",  # IMDS / link-local
        "fd00:ec2::254",  # IMDS over IPv6
        "127.0.0.1",  # loopback
        "::1",  # loopback v6
        "10.1.2.3",  # private
        "172.20.0.1",  # private
        "192.168.0.7",  # private
        "169.254.10.1",  # link-local
        "fe80::1",  # link-local v6
        "fc00::1",  # unique-local v6
        "224.0.0.1",  # multicast
        "240.0.0.1",  # reserved
        "0.0.0.0",  # noqa: S104 - unspecified
        "::",  # unspecified v6
        "::ffff:10.0.0.1",  # v4-mapped private
        "2002:7f00:0001::",  # 6to4 wrapping 127.0.0.1
        "not-an-ip",  # unparseable -> fail closed
    ],
)
def test_is_blocked_address_rejects_non_public(address: str) -> None:
    assert is_blocked_address(address) is True


@pytest.mark.parametrize(
    "address",
    ["93.184.216.34", "8.8.8.8", "2606:2800:220:1:248:1893:25c8:1946"],
)
def test_is_blocked_address_allows_public(address: str) -> None:
    assert is_blocked_address(address) is False
