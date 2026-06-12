"""Tests for the in-house Meta self-scrape provider.

All Facebook traffic is faked through an ``httpx.MockTransport`` (mirroring
``test_meta_ad_library_provider.py``) so no real network egress leaves the test
runner. Covers: LSD-token bootstrap from the Ad Library page HTML, ``for (;;);``
prefix stripping, page-name typeahead resolution, normalization parity with the
shared internal-shape normalizer, cursor pagination via the echoed
``forward_cursor``, a single 403 -> re-bootstrap self-heal, and the hard
compliance-gate raise when ``ad_library_allow_raw_scrape`` is off.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from app.services.ad_intelligence import compliance
from app.services.ad_intelligence.errors import AdLibraryProviderUnavailableError
from app.services.ad_intelligence.providers import meta_scraper
from app.services.ad_intelligence.providers._meta_internal_shape import normalize_ad
from app.services.ad_intelligence.providers.meta_scraper import MetaScraperProvider
from app.services.ad_intelligence.scraper_session import (
    HeadlessSession,
    TokenHttpSession,
    build_session,
    decode_async_payload,
    extract_lsd,
)
from app.services.ad_intelligence.types import AdSearchRequest
from app.services.lead_discovery.errors import (
    LeadDiscoveryAuthError,
    LeadDiscoveryProviderError,
)

_FIXTURES = Path(__file__).parent / "fixtures"
# HTML stub carrying an LSD token in the primary (most specific) shape.
_PAGE_HTML = '<!doctype html><html><script>["LSD",[],{"token":"lsd-token-abc123"}]</script></html>'
_PAGE_HTML_B = (
    '<!doctype html><html><script>["LSD",[],{"token":"lsd-token-xyz789"}]</script></html>'
)


def _load(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURES / name).read_text())


def _async_body(payload: dict[str, Any]) -> str:
    """Serialize a payload the way the async endpoint does: ``for (;;);`` + JSON."""
    return "for (;;);" + json.dumps(payload)


class _FakeRedis:
    """No-op Redis double: forces a fresh bootstrap, accepts cache writes."""

    async def get(self, _key: str) -> None:
        return None

    async def setex(self, _key: str, _ttl: int, _value: str) -> None:
        return None

    async def delete(self, _key: str) -> None:
        return None


@pytest.fixture(autouse=True)
def _enable_scrape(monkeypatch) -> None:
    """Default every test to the 'scraping allowed + slot granted' happy path.

    Individual tests override the compliance flag to exercise the gate.
    """
    monkeypatch.setattr(compliance.settings, "ad_library_allow_raw_scrape", True, raising=False)

    async def _allow() -> tuple[bool, int]:
        return True, 1

    monkeypatch.setattr(meta_scraper, "acquire_scrape_call_slot", _allow)

    async def _fake_redis() -> _FakeRedis:
        return _FakeRedis()

    # The session caches the token/cookies in Redis; fake it so no server is hit.
    monkeypatch.setattr("app.services.ad_intelligence.scraper_session.get_redis", _fake_redis)


def _provider(handler) -> MetaScraperProvider:  # noqa: ANN001
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    session = TokenHttpSession(client=client, proxy_url="")
    # Zero pacing so the test never really sleeps between pages.
    return MetaScraperProvider(session=session, min_delay_seconds=0, max_delay_seconds=0)


@pytest.mark.asyncio
async def test_token_bootstrap_strips_guard_and_paginates() -> None:
    calls: dict[str, int] = {"page": 0, "search": 0}
    bodies: list[dict[str, list[str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ads/library/":
            calls["page"] += 1
            return httpx.Response(200, text=_PAGE_HTML)
        if request.url.path.endswith("/async/search_ads/"):
            calls["search"] += 1
            bodies.append(parse_qs(request.content.decode(), keep_blank_values=True))
            page = _load(
                "meta_search_ads_page1.json"
                if calls["search"] == 1
                else "meta_search_ads_page2.json"
            )
            return httpx.Response(200, text=_async_body(page))
        return httpx.Response(404)

    provider = _provider(handler)
    result = await provider.search(
        AdSearchRequest(platform="meta", country="us", search_terms="ecommerce", max_results=50)
    )
    await provider.close()

    # Bootstrapped once, then followed the cursor to a second page.
    assert calls["page"] == 1
    assert calls["search"] == 2
    # The LSD token rode the POST body + the guard-prefixed JSON decoded cleanly.
    assert bodies[0]["lsd"] == ["lsd-token-abc123"]
    # Country upper-cased; keyword search shape.
    assert bodies[0]["countries[0]"] == ["US"]
    assert bodies[0]["q"] == ["ecommerce"]
    # One advertiser (same page id) carrying all three ads across both pages.
    assert result.advertiser_count == 1
    advertiser = result.advertisers[0]
    assert advertiser.advertiser_key == "20409006880"
    assert advertiser.advertiser_name == "Shopify"
    assert advertiser.ad_count == 3
    assert advertiser.website_host == "shopify.com"


@pytest.mark.asyncio
async def test_pagination_echoes_forward_cursor() -> None:
    bodies: list[dict[str, list[str]]] = []
    search_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ads/library/":
            return httpx.Response(200, text=_PAGE_HTML)
        if request.url.path.endswith("/async/search_ads/"):
            search_calls["n"] += 1
            bodies.append(parse_qs(request.content.decode(), keep_blank_values=True))
            page = _load(
                "meta_search_ads_page1.json"
                if search_calls["n"] == 1
                else "meta_search_ads_page2.json"
            )
            return httpx.Response(200, text=_async_body(page))
        return httpx.Response(404)

    provider = _provider(handler)
    await provider.search(
        AdSearchRequest(platform="meta", country="US", search_terms="x", max_results=60)
    )
    await provider.close()

    # First page is requested with an empty cursor; the second echoes page1's.
    expected_cursor = _load("meta_search_ads_page1.json")["payload"]["forwardCursor"]
    assert bodies[0]["forward_cursor"] == [""]
    assert bodies[1]["forward_cursor"] == [expected_cursor]
    # The collation token is stable across pages.
    assert bodies[0]["collation_token"] == bodies[1]["collation_token"]


@pytest.mark.asyncio
async def test_normalization_parity_with_shared_normalizer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ads/library/":
            return httpx.Response(200, text=_PAGE_HTML)
        if request.url.path.endswith("/async/search_ads/"):
            return httpx.Response(200, text=_async_body(_load("meta_search_ads_page2.json")))
        return httpx.Response(404)

    provider = _provider(handler)
    result = await provider.search(
        AdSearchRequest(platform="meta", country="US", search_terms="x", max_results=10)
    )
    await provider.close()

    # The provider must emit exactly what the shared internal-shape normalizer
    # produces for the same raw ad dict (no scraper-local drift).
    raw_ad = _load("meta_search_ads_page2.json")["payload"]["results"][0][0]
    expected = normalize_ad(raw_ad)
    got = result.advertisers[0].ads[0]
    assert got == expected
    assert got.media_type == "video"
    assert got.is_active is False
    assert got.link_host == "shopify.com"


@pytest.mark.asyncio
async def test_typeahead_resolves_page_name() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ads/library/":
            return httpx.Response(200, text=_PAGE_HTML)
        if request.url.path.endswith("/async/search_typeahead/"):
            seen["typeahead_value"] = parse_qs(request.content.decode(), keep_blank_values=True)[
                "value"
            ]
            return httpx.Response(
                200,
                text=_async_body(
                    {"payload": {"pageResults": [{"page_id": "20409006880", "name": "Shopify"}]}}
                ),
            )
        if request.url.path.endswith("/async/search_ads/"):
            seen["search_body"] = parse_qs(request.content.decode(), keep_blank_values=True)
            return httpx.Response(200, text=_async_body(_load("meta_search_ads_page2.json")))
        return httpx.Response(404)

    provider = _provider(handler)
    result = await provider.search(
        AdSearchRequest(platform="meta", country="US", page_name="Shopify")
    )
    await provider.close()

    assert seen["typeahead_value"] == ["Shopify"]
    # The resolved numeric id scopes the subsequent search to that page.
    assert seen["search_body"]["view_all_page_id"] == ["20409006880"]
    assert seen["search_body"]["search_type"] == ["page"]
    assert result.advertisers[0].advertiser_key == "20409006880"


@pytest.mark.asyncio
async def test_403_rebootstraps_once_then_succeeds() -> None:
    calls = {"page": 0, "search": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ads/library/":
            calls["page"] += 1
            # Serve a different token after re-bootstrap to prove a refresh.
            return httpx.Response(200, text=_PAGE_HTML if calls["page"] == 1 else _PAGE_HTML_B)
        if request.url.path.endswith("/async/search_ads/"):
            calls["search"] += 1
            if calls["search"] == 1:
                return httpx.Response(403, text="login required")
            body = parse_qs(request.content.decode(), keep_blank_values=True)
            # The retry must carry the freshly bootstrapped token.
            assert body["lsd"] == ["lsd-token-xyz789"]
            return httpx.Response(200, text=_async_body(_load("meta_search_ads_page2.json")))
        return httpx.Response(404)

    provider = _provider(handler)
    result = await provider.search(
        AdSearchRequest(platform="meta", country="US", search_terms="x", max_results=10)
    )
    await provider.close()

    assert calls["page"] == 2  # bootstrapped, then re-bootstrapped on the 403
    assert calls["search"] == 2  # original (403) + retry (200)
    assert result.advertiser_count == 1


@pytest.mark.asyncio
async def test_persistent_403_raises_auth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ads/library/":
            return httpx.Response(200, text=_PAGE_HTML)
        return httpx.Response(403, text="blocked")

    provider = _provider(handler)
    with pytest.raises(LeadDiscoveryAuthError):
        await provider.search(
            AdSearchRequest(platform="meta", country="US", search_terms="x", max_results=10)
        )
    await provider.close()


# ---------------------------------------------------------------------------
# Pure session-layer helpers (no transport)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "html",
    [
        '["LSD",[],{"token":"tok_a"}]',
        '"LSD",[],{"token":"tok_a"}',
        '<input type="hidden" name="lsd" value="tok_a" />',
        '"lsd":{"token":"tok_a"}',
    ],
)
def test_extract_lsd_handles_token_shapes(html: str) -> None:
    assert extract_lsd(html) == "tok_a"


def test_extract_lsd_returns_none_when_absent() -> None:
    assert extract_lsd("<html>no token here</html>") is None


def test_decode_async_payload_strips_guard() -> None:
    decoded = decode_async_payload('for (;;);{"payload": {"results": []}}')
    assert decoded == {"payload": {"results": []}}


def test_decode_async_payload_rejects_non_json() -> None:
    # A login/challenge HTML page (no JSON) must surface as a provider error.
    with pytest.raises(LeadDiscoveryProviderError):
        decode_async_payload("<!doctype html><html>login</html>")


def test_decode_async_payload_rejects_non_object() -> None:
    with pytest.raises(LeadDiscoveryProviderError):
        decode_async_payload("for (;;);[1, 2, 3]")


def test_build_session_selects_strategy() -> None:
    assert isinstance(build_session(strategy="token_http"), TokenHttpSession)
    assert isinstance(build_session(strategy="headless"), HeadlessSession)
    # Unknown strategy falls back to the browser-free default.
    assert isinstance(build_session(strategy="bogus"), TokenHttpSession)


@pytest.mark.asyncio
async def test_headless_session_missing_playwright_raises() -> None:
    # Playwright is an optional heavy dep; absent it, the headless path must
    # fail with a clear, actionable provider error (not an ImportError).
    session = HeadlessSession()
    with pytest.raises(LeadDiscoveryProviderError, match="playwright"):
        await session.post("search_ads", {"q": "x"})
    await session.close()


@pytest.mark.asyncio
async def test_compliance_gate_raises_when_flag_off(monkeypatch) -> None:
    monkeypatch.setattr(compliance.settings, "ad_library_allow_raw_scrape", False, raising=False)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never reached
        return httpx.Response(200, text=_PAGE_HTML)

    provider = _provider(handler)
    with pytest.raises(AdLibraryProviderUnavailableError):
        await provider.search(AdSearchRequest(platform="meta", country="US", search_terms="x"))
    await provider.close()
