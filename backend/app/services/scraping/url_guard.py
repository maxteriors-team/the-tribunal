"""SSRF egress guard for outbound scraping requests.

Scrape targets reach this backend as free-form client input — the AI Find Leads
import body (``BusinessResult.website``), the people-discovery ``domain`` param,
a prospect's stored ``website_host`` — and are never re-validated against the
upstream provider that supposedly produced them. Anything handed to
:class:`~app.services.scraping.website_scraper.WebsiteScraperService` is
therefore attacker-controlled, and the fetched body flows back to the caller via
``business_intel.website_meta``, the AI website summary, and error strings. That
is a read-capable SSRF primitive unless every URL is checked first.

Rules enforced by :func:`validate_outbound_url`:

* scheme must be ``http`` / ``https`` (no ``file``, ``gopher``, ``ftp``, ...);
* the hostname must not be a known cloud-metadata alias;
* **every** address the hostname resolves to must be public, routable unicast —
  a single private/loopback/link-local/reserved/multicast/unspecified answer
  rejects the URL (a hostname with one public and one private A record is a
  standard DNS-based bypass).

Callers must validate **every redirect hop**, not just the initial URL: a public
host can 302 into link-local space, which defeats a validate-once check. See
``WebsiteScraperService._get_with_guarded_redirects``.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Final
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger()

ALLOWED_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})

# Hostnames that must never be fetched regardless of what DNS says about them.
# The cloud metadata services are the high-value SSRF target (instance
# credentials); ``localhost`` is listed for defence in depth even though it also
# resolves into loopback space.
BLOCKED_HOSTNAMES: Final[frozenset[str]] = frozenset(
    {
        "metadata.google.internal",  # GCP instance metadata
        "metadata.goog",  # GCP alias
        "metadata",  # GCP short alias (search-domain completion)
        "instance-data",  # AWS/OpenStack alias
        "localhost",
        "localhost.localdomain",
    }
)

# Literal addresses rejected by name as well as by classification. These are
# already link-local/unique-local, but an explicit deny keeps the intent obvious
# and survives any future loosening of the classification rules.
BLOCKED_ADDRESSES: Final[frozenset[str]] = frozenset(
    {
        "169.254.169.254",  # AWS/GCP/Azure/DigitalOcean IMDS
        "fd00:ec2::254",  # AWS IMDS over IPv6
    }
)

_BLOCKED_IPS: Final[frozenset[ipaddress.IPv4Address | ipaddress.IPv6Address]] = frozenset(
    ipaddress.ip_address(address) for address in BLOCKED_ADDRESSES
)

# Single, category-free message. The caller-facing string must not reveal
# whether a host resolved privately, or which address it resolved to, otherwise
# the guard itself becomes an internal-network oracle. Detail goes to the log.
SAFE_MESSAGE: Final[str] = "URL rejected by outbound request policy"


class UnsafeURLError(ValueError):
    """Raised when a URL fails the SSRF egress guard.

    ``str(exc)`` is deliberately opaque (:data:`SAFE_MESSAGE`) and safe to
    surface to an API caller: it never echoes the URL, hostname, resolved
    addresses, or the reason. The machine-readable :attr:`reason` is for
    server-side structured logging only.
    """

    def __init__(self, reason: str) -> None:
        """Initialize with a short reason code kept out of the public message."""
        self.reason = reason
        super().__init__(SAFE_MESSAGE)


def _normalize_hostname(hostname: str) -> str:
    """Lower-case a hostname and drop the FQDN root dot.

    ``metadata.google.internal.`` and ``METADATA`` must not slip past the
    hostname deny-list on punctuation/case alone.
    """
    return hostname.strip().rstrip(".").lower()


def _unwrap_ipv6(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Return the embedded IPv4 address for mapped/6to4 forms, else the input.

    ``::ffff:127.0.0.1`` and ``2002:7f00:1::`` are loopback in disguise; classify
    the embedded v4 address rather than the wrapper.
    """
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    return ip


def is_blocked_address(address: str) -> bool:
    """Return ``True`` when ``address`` is not public, routable unicast.

    Fails closed: an address that cannot be parsed is treated as blocked.
    """
    try:
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(address)
    except ValueError:
        return True
    if isinstance(ip, ipaddress.IPv6Address):
        ip = _unwrap_ipv6(ip)
    if ip in _BLOCKED_IPS:
        return True
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve_addresses(hostname: str) -> list[str]:
    """Resolve ``hostname`` to every A/AAAA answer.

    Blocking call — always invoke it off the event loop (see
    :func:`validate_outbound_url`).
    """
    infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    return [str(info[4][0]) for info in infos]


def validate_url_scheme_and_host(url: str) -> tuple[str, str]:
    """Run the I/O-free half of the guard: scheme + hostname deny-list.

    Args:
        url: Absolute URL to check.

    Returns:
        Tuple of ``(scheme, normalized_hostname)``.

    Raises:
        UnsafeURLError: If the URL is malformed, host-less, uses a scheme other
            than http/https, or names a blocked host.
    """
    try:
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        hostname = parsed.hostname
        parsed.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError as exc:
        raise UnsafeURLError("malformed_url") from exc

    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError("scheme_not_allowed")
    if not hostname:
        raise UnsafeURLError("missing_host")

    host = _normalize_hostname(hostname)
    if not host or host in BLOCKED_HOSTNAMES:
        raise UnsafeURLError("blocked_hostname")
    return scheme, host


async def validate_outbound_url(url: str) -> str:
    """Validate ``url`` before it is fetched by a server-side HTTP client.

    DNS resolution runs in the default executor so the event loop is never
    blocked by ``socket.getaddrinfo``.

    Args:
        url: Absolute URL about to be requested (initial target or redirect hop).

    Returns:
        The URL unchanged, so callers can write ``url = await
        validate_outbound_url(url)``.

    Raises:
        UnsafeURLError: If the URL fails any egress rule. The message is safe to
            return to an API caller.
    """
    _scheme, host = validate_url_scheme_and_host(url)

    loop = asyncio.get_running_loop()
    try:
        addresses = await loop.run_in_executor(None, _resolve_addresses, host)
    except (OSError, UnicodeError) as exc:
        # gaierror (unresolvable) / UnicodeError (IDNA blow-up). Fail closed:
        # a host we cannot classify is a host we do not fetch.
        logger.warning("ssrf_guard_dns_failed", host=host, error=str(exc))
        raise UnsafeURLError("dns_resolution_failed") from exc

    if not addresses:
        logger.warning("ssrf_guard_dns_empty", host=host)
        raise UnsafeURLError("dns_resolution_failed")

    for address in addresses:
        if is_blocked_address(address):
            logger.warning("ssrf_guard_blocked", host=host, address=address)
            raise UnsafeURLError("non_public_address")

    return url
