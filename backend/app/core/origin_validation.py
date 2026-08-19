"""Origin validation utility for public endpoints."""

from urllib.parse import urlparse

from fastapi import Request


def is_allowed_origin(origin: str | None, allowed_domains: list[str]) -> bool:
    """Return whether an origin URL's hostname matches the configured allowlist."""
    if not origin or not allowed_domains:
        return False

    try:
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"}:
            return False
        host = (parsed.hostname or "").lower()
    except (TypeError, ValueError):
        return False

    for configured_domain in allowed_domains:
        domain = configured_domain.lower().strip()

        if host == domain:
            return True

        if domain.startswith("*."):
            base_domain = domain[2:]
            if host == base_domain or host.endswith(f".{base_domain}"):
                return True

    return False


def validate_origin(request: Request, allowed_domains: list[str]) -> bool:
    """Validate the request's browser-controlled ``Origin`` header.

    The ``Referer`` header is intentionally not a fallback: it is frequently
    omitted and is not a dependable browser security boundary.
    """
    return is_allowed_origin(request.headers.get("origin"), allowed_domains)
