"""Tests for ``app.core.utils.get_client_ip``.

Every IP-based control in the API (login brute-force lockout, demo and
lead-form telephony spend caps) and every audit record keys off this helper,
so a caller who can choose their own IP defeats all of them at once.

``X-Forwarded-For`` is append-only: each proxy adds the peer it received the
request from, so the *rightmost* entries are written by infrastructure we
control and the *leftmost* entries are entirely client-supplied. The helper
must therefore return the rightmost hop that is not itself a trusted proxy,
and must ignore the header outright when the direct peer is untrusted.
"""

from fastapi import Request

from app.core.utils import get_client_ip

# Mirrors the ``trusted_proxies`` default in app.core.config.
TRUSTED: list[str] = ["127.0.0.1", "::1"]


def _make_request(client: tuple[str, int] | None, headers: dict[str, str]) -> Request:
    """Build a minimal ASGI ``Request`` with the given peer and headers."""
    encoded = [
        (key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in headers.items()
    ]
    scope: dict[str, object] = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": encoded,
    }
    if client is not None:
        scope["client"] = client
    return Request(scope=scope)


class TestSpoofedForwardedFor:
    """A forged leftmost entry must never win."""

    def test_multi_hop_resolves_to_rightmost_untrusted_hop(self) -> None:
        """The classic spoof: attacker prepends a victim IP, the edge proxy
        appends the real peer. The appended value is the only trustworthy one."""
        request = _make_request(
            ("127.0.0.1", 51000),
            {"x-forwarded-for": "1.2.3.4, 5.6.7.8, 203.0.113.7"},
        )
        assert get_client_ip(request, TRUSTED) == "203.0.113.7"

    def test_single_forged_entry_is_still_used_when_edge_appends_nothing(self) -> None:
        """With one hop there is nothing to the right of it, so it is the peer
        the trusted proxy actually observed."""
        request = _make_request(("127.0.0.1", 51000), {"x-forwarded-for": "203.0.113.7"})
        assert get_client_ip(request, TRUSTED) == "203.0.113.7"

    def test_trusted_proxy_hops_on_the_right_are_skipped(self) -> None:
        """Internal hops append themselves; walk left past them to the client."""
        request = _make_request(
            ("127.0.0.1", 51000),
            {"x-forwarded-for": "1.2.3.4, 203.0.113.7, 127.0.0.1, ::1"},
        )
        assert get_client_ip(request, TRUSTED) == "203.0.113.7"

    def test_attacker_cannot_pin_a_constant_ip_across_requests(self) -> None:
        """Two requests forging the same leftmost IP must land on different
        buckets, otherwise a shared rate-limit key can be poisoned at will."""
        first = _make_request(("127.0.0.1", 51000), {"x-forwarded-for": "9.9.9.9, 198.51.100.1"})
        second = _make_request(("127.0.0.1", 51001), {"x-forwarded-for": "9.9.9.9, 198.51.100.2"})
        assert get_client_ip(first, TRUSTED) != get_client_ip(second, TRUSTED)

    def test_all_hops_trusted_falls_back_to_direct_peer(self) -> None:
        request = _make_request(("127.0.0.1", 51000), {"x-forwarded-for": "127.0.0.1, ::1"})
        assert get_client_ip(request, TRUSTED) == "127.0.0.1"

    def test_ipv6_client_behind_trusted_proxy(self) -> None:
        request = _make_request(("::1", 51000), {"x-forwarded-for": "1.2.3.4, 2001:db8::1234"})
        assert get_client_ip(request, TRUSTED) == "2001:db8::1234"


class TestUntrustedDirectPeer:
    """When the peer is not a trusted proxy the header is pure attacker input."""

    def test_direct_peer_returned_and_header_ignored(self) -> None:
        request = _make_request(("198.51.100.23", 44444), {"x-forwarded-for": "1.2.3.4, 127.0.0.1"})
        assert get_client_ip(request, TRUSTED) == "198.51.100.23"

    def test_header_ignored_even_when_it_names_a_trusted_proxy(self) -> None:
        request = _make_request(("198.51.100.23", 44444), {"x-forwarded-for": "127.0.0.1"})
        assert get_client_ip(request, TRUSTED) == "198.51.100.23"

    def test_empty_trusted_proxy_list_disables_the_header(self) -> None:
        request = _make_request(("127.0.0.1", 51000), {"x-forwarded-for": "1.2.3.4"})
        assert get_client_ip(request, []) == "127.0.0.1"


class TestMalformedAndMissingHeaders:
    """Bad input must fail closed onto the direct peer, never onto the header."""

    def test_missing_header_falls_back_to_direct_peer(self) -> None:
        request = _make_request(("127.0.0.1", 51000), {})
        assert get_client_ip(request, TRUSTED) == "127.0.0.1"

    def test_empty_header_falls_back_to_direct_peer(self) -> None:
        request = _make_request(("127.0.0.1", 51000), {"x-forwarded-for": ""})
        assert get_client_ip(request, TRUSTED) == "127.0.0.1"

    def test_whitespace_only_header_falls_back_to_direct_peer(self) -> None:
        request = _make_request(("127.0.0.1", 51000), {"x-forwarded-for": "   "})
        assert get_client_ip(request, TRUSTED) == "127.0.0.1"

    def test_comma_only_header_falls_back_to_direct_peer(self) -> None:
        request = _make_request(("127.0.0.1", 51000), {"x-forwarded-for": ",,,"})
        assert get_client_ip(request, TRUSTED) == "127.0.0.1"

    def test_malformed_rightmost_hop_does_not_promote_leftmost_entry(self) -> None:
        """Garbage where the real client should be must not make us reach
        further left into attacker-controlled territory."""
        request = _make_request(("127.0.0.1", 51000), {"x-forwarded-for": "1.2.3.4, not-an-ip"})
        assert get_client_ip(request, TRUSTED) == "127.0.0.1"

    def test_injection_payload_is_rejected(self) -> None:
        request = _make_request(
            ("127.0.0.1", 51000),
            {"x-forwarded-for": "203.0.113.7'; DROP TABLE users;--"},
        )
        assert get_client_ip(request, TRUSTED) == "127.0.0.1"

    def test_host_port_form_is_not_accepted_as_an_address(self) -> None:
        request = _make_request(("127.0.0.1", 51000), {"x-forwarded-for": "203.0.113.7:8080"})
        assert get_client_ip(request, TRUSTED) == "127.0.0.1"

    def test_trailing_separator_is_tolerated(self) -> None:
        request = _make_request(("127.0.0.1", 51000), {"x-forwarded-for": "1.2.3.4, 203.0.113.7, "})
        assert get_client_ip(request, TRUSTED) == "203.0.113.7"

    def test_missing_client_returns_unknown(self) -> None:
        request = _make_request(None, {"x-forwarded-for": "1.2.3.4"})
        assert get_client_ip(request, TRUSTED) == "unknown"

    def test_invalid_entries_in_trusted_proxy_config_are_skipped(self) -> None:
        request = _make_request(("127.0.0.1", 51000), {"x-forwarded-for": "1.2.3.4, 203.0.113.7"})
        assert get_client_ip(request, ["not-an-ip", "127.0.0.1"]) == "203.0.113.7"
