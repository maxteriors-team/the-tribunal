"""Tests for the Google Ads Transparency (SerpApi) provider."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.services.ad_intelligence.providers.google_ads_transparency import (
    GoogleAdsTransparencyProvider,
)
from app.services.ad_intelligence.types import AdSearchRequest
from app.services.lead_discovery.errors import LeadDiscoveryAuthError

RECENT = int((datetime.now(UTC) - timedelta(days=2)).timestamp())
OLD_START = int((datetime.now(UTC) - timedelta(days=120)).timestamp())


@pytest.mark.asyncio
async def test_disabled_without_key_raises() -> None:
    provider = GoogleAdsTransparencyProvider(api_key="")
    with pytest.raises(LeadDiscoveryAuthError):
        await provider.search(AdSearchRequest(platform="google", country="US", page_id="AR1"))


@pytest.mark.asyncio
async def test_normalizes_ad_creatives() -> None:
    payload: dict[str, Any] = {
        "search_metadata": {"status": "Success"},
        "search_information": {"total_results": 2},
        "ad_creatives": [
            {
                "advertiser_id": "AR17828074650563772417",
                "advertiser": "Tesla Inc.",
                "ad_creative_id": "CR1",
                "format": "video",
                "target_domain": "tesla.com",
                "first_shown": OLD_START,
                "last_shown": RECENT,
                "total_days_shown": 46,
                "details_link": "https://adstransparency.google.com/advertiser/AR1/creative/CR1",
            },
            {
                "advertiser_id": "AR17828074650563772417",
                "advertiser": "Tesla Inc.",
                "ad_creative_id": "CR2",
                "format": "text",
                "target_domain": "tesla.com",
                "first_shown": OLD_START,
                "last_shown": OLD_START,
            },
        ],
    }

    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    provider = GoogleAdsTransparencyProvider(api_key="k", client=client)
    result = await provider.search(
        AdSearchRequest(platform="google", country="US", page_id="AR17828074650563772417")
    )
    await provider.close()

    assert captured["params"]["engine"] == "google_ads_transparency_center"
    assert captured["params"]["region"] == "2840"  # US geo target id
    assert captured["params"]["advertiser_id"] == "AR17828074650563772417"

    assert result.advertiser_count == 1
    adv = result.advertisers[0]
    assert adv.advertiser_name == "Tesla Inc."
    assert adv.website_host == "tesla.com"
    assert adv.ad_count == 2
    actives = {ad.ad_external_id: ad.is_active for ad in adv.ads}
    # CR1 last shown recently -> active; CR2 last shown 120d ago -> inactive.
    assert actives == {"CR1": True, "CR2": False}
    assert adv.ads[0].media_type == "video"


@pytest.mark.asyncio
async def test_nested_advertiser_object() -> None:
    payload = {
        "ad_creatives": [
            {
                "id": "CR9",
                "advertiser": {"id": "AR999", "name": "Acme"},
                "format": "image",
                "target_domain": "acme.com",
                "first_shown_datetime": "2025-01-01T00:00:00Z",
                "last_shown_datetime": "2025-01-20T00:00:00Z",
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    provider = GoogleAdsTransparencyProvider(api_key="k", client=client)
    result = await provider.search(
        AdSearchRequest(platform="google", country="US", page_id="AR999")
    )
    await provider.close()
    adv = result.advertisers[0]
    assert adv.advertiser_key == "AR999"
    assert adv.advertiser_name == "Acme"
    assert adv.ads[0].media_type == "image"
