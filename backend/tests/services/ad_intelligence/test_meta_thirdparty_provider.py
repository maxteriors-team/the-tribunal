"""Tests for the config-gated third-party Meta provider.

Covers graceful disable when no key is present, and normalization of an
Adyntel/ScrapeCreators-style envelope (nested ``data.results`` with epoch
dates, ``snapshot.cards``, ``is_active``, ``display_format``).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.services.ad_intelligence.providers.meta_thirdparty import MetaThirdPartyProvider
from app.services.ad_intelligence.types import AdSearchRequest
from app.services.lead_discovery.errors import LeadDiscoveryAuthError


@pytest.mark.asyncio
async def test_disabled_without_key_raises_auth_error() -> None:
    provider = MetaThirdPartyProvider(api_key="", base_url="")
    assert provider.is_configured is False
    with pytest.raises(LeadDiscoveryAuthError):
        await provider.search(AdSearchRequest(platform="meta", country="US", page_id="100"))


@pytest.mark.asyncio
async def test_normalizes_nested_envelope() -> None:
    envelope: dict[str, Any] = {
        "status": "success",
        "data": {
            "page_id": "20409006880",
            "results": [
                [
                    {
                        "ad_archive_id": "1616561949512060",
                        "page_id": "20409006880",
                        "page_name": "Shopify",
                        "snapshot": {
                            "body": {"text": "Build your store"},
                            "caption": "shopify.com",
                            "cta_type": "LEARN_MORE",
                            "display_format": "DCO",
                            "cards": [
                                {"title": "Convierte tu web", "link_url": "https://www.shopify.com/x"}
                            ],
                        },
                        "is_active": True,
                        "start_date": 1765180800,
                        "end_date": 1771574400,
                        "publisher_platform": ["FACEBOOK", "INSTAGRAM"],
                        "url": "https://facebook.com/ads/library/?id=1616561949512060&access_token=SECRET",
                    }
                ]
            ],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=envelope)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    provider = MetaThirdPartyProvider(
        api_key="k", provider_name="apify", base_url="https://api.example/ads", client=client
    )
    result = await provider.search(
        AdSearchRequest(platform="meta", country="US", page_id="20409006880")
    )
    await provider.close()

    assert result.advertiser_count == 1
    adv = result.advertisers[0]
    assert adv.advertiser_key == "20409006880"
    assert adv.advertiser_name == "Shopify"
    assert adv.website_host == "shopify.com"
    ad = adv.ads[0]
    assert ad.ad_external_id == "1616561949512060"
    assert ad.body == "Build your store"
    assert ad.cta_type == "LEARN_MORE"
    assert ad.media_type == "carousel"
    assert ad.is_active is True
    assert ad.ad_delivery_start_time is not None
    # Token-bearing snapshot URL surfaced but dropped from stored raw payload.
    assert "access_token" not in str(ad.raw)
