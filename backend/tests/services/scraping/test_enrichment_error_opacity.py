"""Enrichment failures must not reflect upstream exception text to callers.

``business_intel`` is persisted and re-served through ``ContactResponse``, and
``error`` reaches the import response's ``errors[]`` — both are exfiltration
channels for anything the scraper's exception string happens to contain.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.scraping import enrichment_service
from app.services.scraping.enrichment_service import (
    ENRICHMENT_ERROR_MESSAGE,
    enrich_contact_data,
)
from app.services.scraping.website_scraper import BlockedURLError, WebsiteScraperError

_LEAKY = "connect to 169.254.169.254:80 failed: internal-vpc-host says AWS_SECRET=abc"


class _ExplodingScraper:
    def __init__(self, error: Exception) -> None:
        self._error = error
        self.closed = False

    async def scrape_website(self, url: str) -> dict[str, Any]:
        raise self._error

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        WebsiteScraperError(_LEAKY),
        BlockedURLError(_LEAKY),
        RuntimeError(_LEAKY),  # unexpected-error branch
    ],
)
async def test_enrichment_error_is_opaque(
    error: Exception, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        enrichment_service,
        "WebsiteScraperService",
        lambda *a, **kw: _ExplodingScraper(error),
    )

    result = await enrich_contact_data(
        website_url="http://169.254.169.254/latest/meta-data/",
        company_name="Acme",
        google_places_data={"google_places": {"place_id": "abc"}},
        enable_ai=False,
    )

    assert result["enrichment_status"] == "failed"
    assert result["error"] == ENRICHMENT_ERROR_MESSAGE
    assert result["business_intel"]["enrichment_error"] == ENRICHMENT_ERROR_MESSAGE
    # Nothing from the upstream exception may survive into caller-visible data.
    serialized = repr(result)
    assert "169.254.169.254" not in serialized
    assert "internal-vpc-host" not in serialized
    assert "AWS_SECRET" not in serialized
    # The Google Places payload the caller already owns is still preserved.
    assert result["business_intel"]["google_places"]["place_id"] == "abc"
