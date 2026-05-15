"""Tests for ``app.core.origin_validation.validate_origin``.

The validator must rely solely on the ``Origin`` header. The ``Referer``
header is trivially spoofable by non-browser clients and is intentionally
*not* consulted as a fallback, so requests that arrive with only a
``Referer`` (and no ``Origin``) must be rejected — even when the referer
points at an otherwise allow-listed domain.
"""

from fastapi import Request

from app.core.origin_validation import validate_origin


def _make_request(headers: dict[str, str]) -> Request:
    """Build a minimal ASGI ``Request`` carrying the given headers."""
    encoded = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in headers.items()
    ]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": encoded,
    }
    return Request(scope=scope)


class TestOriginHeaderRequired:
    """Only the ``Origin`` header may authorize a request."""

    def test_origin_header_exact_match_allowed(self) -> None:
        request = _make_request({"origin": "https://example.com"})
        assert validate_origin(request, ["example.com"]) is True

    def test_origin_header_wildcard_subdomain_allowed(self) -> None:
        request = _make_request({"origin": "https://app.example.com"})
        assert validate_origin(request, ["*.example.com"]) is True

    def test_origin_header_mismatch_rejected(self) -> None:
        request = _make_request({"origin": "https://evil.com"})
        assert validate_origin(request, ["example.com"]) is False

    def test_missing_origin_rejected(self) -> None:
        request = _make_request({})
        assert validate_origin(request, ["example.com"]) is False

    def test_empty_allowed_domains_rejected(self) -> None:
        request = _make_request({"origin": "https://example.com"})
        assert validate_origin(request, []) is False


class TestRefererNotAFallback:
    """``Referer`` must never substitute for ``Origin``."""

    def test_referer_only_rejected_even_for_allowed_domain(self) -> None:
        request = _make_request({"referer": "https://example.com/page"})
        assert validate_origin(request, ["example.com"]) is False

    def test_referer_only_rejected_for_wildcard_match(self) -> None:
        request = _make_request({"referer": "https://app.example.com/page"})
        assert validate_origin(request, ["*.example.com"]) is False

    def test_origin_takes_precedence_over_referer(self) -> None:
        # Spoofed referer pointing at an allowed domain must not rescue
        # a request whose Origin is on a disallowed domain.
        request = _make_request(
            {
                "origin": "https://evil.com",
                "referer": "https://example.com/page",
            }
        )
        assert validate_origin(request, ["example.com"]) is False

    def test_origin_allowed_regardless_of_referer(self) -> None:
        request = _make_request(
            {
                "origin": "https://example.com",
                "referer": "https://anywhere.test/page",
            }
        )
        assert validate_origin(request, ["example.com"]) is True
