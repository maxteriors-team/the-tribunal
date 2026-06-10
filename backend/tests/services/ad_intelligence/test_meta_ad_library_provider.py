"""Tests for the Meta Ad Library provider.

A recorded ``/ads_archive`` payload is served through an ``httpx.MockTransport``
so no real Graph API traffic leaves the test runner. These cover normalization
(Graph list-fields -> ``NormalizedAd``/``NormalizedAdvertiser``), advertiser
grouping by page id, active-status inference from delivery stop time, the
mandatory-country param, error-class mapping (429 / auth / generic), cursor
pagination, and that the token-bearing snapshot URL is dropped from the stored
raw payload.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.services.ad_intelligence.providers.meta_ad_library import MetaAdLibraryProvider
from app.services.ad_intelligence.types import AdSearchRequest
from app.services.lead_discovery.errors import (
    LeadDiscoveryAuthError,
    LeadDiscoveryProviderError,
    LeadDiscoveryRateLimitError,
)

FUTURE = (datetime.now(UTC) + timedelta(days=30)).date().isoformat()
PAST = (datetime.now(UTC) - timedelta(days=10)).date().isoformat()


def _ad(
    ad_id: str,
    page_id: str,
    *,
    body: str,
    caption: str = "acme.example",
    titles: list[str] | None = None,
    start: str = "2025-01-01",
    stop: str | None = None,
) -> dict[str, Any]:
    ad: dict[str, Any] = {
        "id": ad_id,
        "page_id": page_id,
        "page_name": "Acme Co",
        "ad_creative_bodies": [body],
        "ad_creative_link_captions": [caption],
        "ad_delivery_start_time": start,
        "publisher_platforms": ["FACEBOOK", "INSTAGRAM"],
        "ad_snapshot_url": f"https://www.facebook.com/ads/archive/render_ad/?id={ad_id}&access_token=SECRET",
    }
    if titles is not None:
        ad["ad_creative_link_titles"] = titles
    if stop is not None:
        ad["ad_delivery_stop_time"] = stop
    return ad


def _make_provider(handler) -> MetaAdLibraryProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return MetaAdLibraryProvider(access_token="test-token", client=client)


@pytest.mark.asyncio
async def test_search_normalizes_and_groups_advertisers() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        payload = {
            "data": [
                _ad("1", "100", body="Long runner", stop=FUTURE),
                _ad("2", "100", body="Second creative", stop=PAST),
                _ad("3", "200", body="Other advertiser", stop=FUTURE),
            ],
            "paging": {"cursors": {"after": "CURSOR"}},
        }
        return httpx.Response(200, json=payload)

    provider = _make_provider(handler)
    result = await provider.search(
        AdSearchRequest(platform="meta", country="us", search_terms="roofing", max_results=50)
    )
    await provider.close()

    # Mandatory country param present and upper-cased.
    assert captured["params"]["ad_reached_countries"] == '["US"]'
    assert captured["params"]["search_terms"] == "roofing"

    assert result.advertiser_count == 2
    assert result.raw_ad_count == 3
    by_key = {a.advertiser_key: a for a in result.advertisers}
    acme = by_key["100"]
    assert acme.advertiser_name == "Acme Co"
    assert acme.ad_count == 2
    # Active inference: ad 1 (future stop) active, ad 2 (past stop) inactive.
    actives = {ad.ad_external_id: ad.is_active for ad in acme.ads}
    assert actives == {"1": True, "2": False}
    # Landing host extracted from caption.
    assert acme.website_host == "acme.example"


@pytest.mark.asyncio
async def test_snapshot_url_dropped_from_raw_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [_ad("9", "100", body="hi", stop=FUTURE)]})

    provider = _make_provider(handler)
    result = await provider.search(
        AdSearchRequest(platform="meta", country="US", search_terms="x", max_results=10)
    )
    await provider.close()
    ad = result.advertisers[0].ads[0]
    # The token-bearing snapshot URL is surfaced on the normalized ad but never
    # retained in the stored raw payload (which lands in the DB / logs).
    assert ad.snapshot_url is not None and "access_token" in ad.snapshot_url
    assert "ad_snapshot_url" not in ad.raw
    assert "access_token" not in json.dumps(ad.raw)


@pytest.mark.asyncio
async def test_carousel_media_inference() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [_ad("9", "100", body="hi", titles=["A", "B", "C"], stop=FUTURE)]},
        )

    provider = _make_provider(handler)
    result = await provider.search(
        AdSearchRequest(platform="meta", country="US", search_terms="x")
    )
    await provider.close()
    assert result.advertisers[0].ads[0].media_type == "carousel"


@pytest.mark.asyncio
async def test_rate_limit_maps_to_rate_limit_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "60"},
            json={
                "error": {"code": 613, "message": "Calls to this api have exceeded the rate limit"}
            },
        )

    provider = _make_provider(handler)
    with pytest.raises(LeadDiscoveryRateLimitError):
        await provider.search(AdSearchRequest(platform="meta", country="US", search_terms="x"))
    await provider.close()


@pytest.mark.asyncio
async def test_auth_error_maps() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"code": 190, "message": "Invalid OAuth access token"}}
        )

    provider = _make_provider(handler)
    with pytest.raises(LeadDiscoveryAuthError):
        await provider.search(AdSearchRequest(platform="meta", country="US", search_terms="x"))
    await provider.close()


@pytest.mark.asyncio
async def test_generic_error_maps() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"code": 1, "message": "Unknown"}})

    provider = _make_provider(handler)
    with pytest.raises(LeadDiscoveryProviderError):
        await provider.search(AdSearchRequest(platform="meta", country="US", search_terms="x"))
    await provider.close()


@pytest.mark.asyncio
async def test_missing_token_raises_auth_error() -> None:
    provider = MetaAdLibraryProvider(access_token="")
    with pytest.raises(LeadDiscoveryAuthError):
        await provider.search(AdSearchRequest(platform="meta", country="US", search_terms="x"))


@pytest.mark.asyncio
async def test_pagination_follows_cursor() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                200,
                json={
                    "data": [_ad(str(i), "100", body=f"b{i}", stop=FUTURE) for i in range(100)],
                    "paging": {"cursors": {"after": "NEXT"}, "next": "https://x/next"},
                },
            )
        return httpx.Response(
            200,
            json={"data": [_ad("200", "100", body="last", stop=FUTURE)]},
        )

    provider = _make_provider(handler)
    result = await provider.search(
        AdSearchRequest(platform="meta", country="US", search_terms="x", max_results=150)
    )
    await provider.close()
    assert calls["n"] == 2
    assert result.raw_ad_count == 101


@pytest.mark.asyncio
async def test_resolve_page_id_from_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        # First call is the resolve probe (fields=id,page_id,page_name).
        if params.get("fields") == "id,page_id,page_name":
            return httpx.Response(
                200,
                json={"data": [{"id": "1", "page_id": "555", "page_name": "Acme"},
                               {"id": "2", "page_id": "555", "page_name": "Acme"}]},
            )
        # Second call should now be scoped to the resolved page id.
        assert params.get("search_page_ids") == '["555"]'
        return httpx.Response(200, json={"data": [_ad("3", "555", body="hi", stop=FUTURE)]})

    provider = _make_provider(handler)
    result = await provider.search(
        AdSearchRequest(platform="meta", country="US", page_name="Acme")
    )
    await provider.close()
    assert result.advertisers[0].advertiser_key == "555"
