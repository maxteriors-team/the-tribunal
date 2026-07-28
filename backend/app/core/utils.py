"""Core utility functions."""

import ipaddress

from fastapi import Request


def get_client_ip(request: Request, trusted_proxies: list[str]) -> str:
    """Extract client IP from request with secure proxy validation.

    Only trusts X-Forwarded-For header if the request comes from a trusted proxy.
    This prevents IP spoofing attacks where malicious clients set fake headers.

    Args:
        request: FastAPI request object
        trusted_proxies: List of trusted proxy IP addresses (e.g., ["127.0.0.1", "::1"])

    Returns:
        Client IP address as a string

    Security:
        - Only accepts X-Forwarded-For from trusted proxies
        - Picks the rightmost non-proxy hop, never the forgeable leftmost one
        - Validates IP addresses to prevent injection attacks
        - Returns direct client IP if proxy is not trusted
        - Handles missing or malformed headers gracefully
    """
    # Get the direct client IP (the immediate connection)
    direct_ip = request.client.host if request.client else "unknown"

    # If direct IP is unknown, return it immediately
    if direct_ip == "unknown":
        return direct_ip

    # Validate that the direct IP is from a trusted proxy
    is_trusted_proxy = _is_trusted_proxy(direct_ip, trusted_proxies)
    if not is_trusted_proxy:
        return direct_ip

    # Only trust X-Forwarded-For if request is from a trusted proxy
    return _extract_forwarded_ip(request, direct_ip, trusted_proxies)


def _is_trusted_proxy(candidate_ip: str, trusted_proxies: list[str]) -> bool:
    """Check if an IP address belongs to a trusted proxy.

    Used both for the direct peer and for individual X-Forwarded-For hops.
    """
    try:
        candidate_ip_obj = ipaddress.ip_address(candidate_ip)
        for trusted_proxy in trusted_proxies:
            try:
                trusted_proxy_obj = ipaddress.ip_address(trusted_proxy)
                if candidate_ip_obj == trusted_proxy_obj:
                    return True
            except ValueError:
                # Invalid trusted proxy configuration - skip it
                continue
    except ValueError:
        # Not a valid IP address - cannot be a trusted proxy
        pass
    return False


def _extract_forwarded_ip(request: Request, fallback_ip: str, trusted_proxies: list[str]) -> str:
    """Extract IP from X-Forwarded-For header with validation.

    Each proxy *appends* the peer it received the request from, so the rightmost
    entries are written by infrastructure we control while the leftmost entries
    are entirely client-supplied. Trusting the leftmost entry lets any caller
    forge an IP and defeat every IP-based rate limit, so we walk the chain in
    reverse and take the first hop that is not itself a trusted proxy.
    """
    forwarded_for = request.headers.get("x-forwarded-for")
    if not forwarded_for:
        return fallback_ip

    # X-Forwarded-For can contain multiple IPs: "client, proxy1, proxy2"
    for raw_hop in reversed(forwarded_for.split(",")):
        hop = raw_hop.strip()
        if not hop:
            # Stray or trailing separator - carries no address, keep walking
            continue
        if _is_trusted_proxy(hop, trusted_proxies):
            # Our own infrastructure - keep walking left toward the client
            continue
        try:
            # This validates the IP format and prevents injection
            ipaddress.ip_address(hop)
        except ValueError:
            # Malformed hop where the real client should be - everything
            # further left is client-supplied, so fall back to the direct IP
            return fallback_ip
        return hop

    # Every hop was a trusted proxy - the direct IP is the best we have
    return fallback_ip
