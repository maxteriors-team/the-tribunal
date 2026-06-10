"""Tests for advertiser contact tracing.

A fake scraper returns canned HTML/social links so no network I/O occurs. These
pin the public email/phone extraction, same-domain email ranking, landing-domain
derivation from ads, and graceful handling of scrape failures.
"""

from __future__ import annotations

import pytest

from app.services.ad_intelligence.contact_tracing import (
    ContactTracer,
    landing_domain_from_ads,
)
from app.services.ad_intelligence.types import NormalizedAd
from app.services.scraping.website_scraper import WebsiteScraperError


class _FakeScraper:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.closed = False

    async def scrape_website(self, url: str):
        if self._error:
            raise self._error
        return self._result

    async def close(self) -> None:
        self.closed = True


def _ad(host: str) -> NormalizedAd:
    return NormalizedAd(
        ad_external_id="1",
        link_caption=host,
        link_url=f"https://{host}/lp",
        link_host=host,
    )


def test_landing_domain_from_ads_picks_most_common() -> None:
    ads = [_ad("acme.com"), _ad("acme.com"), _ad("other.com")]
    url, host = landing_domain_from_ads(ads)
    assert host == "acme.com"
    assert url == "https://acme.com/lp"


@pytest.mark.asyncio
async def test_trace_extracts_email_phone_and_socials() -> None:
    html = """
    <html><body>
      <a href="mailto:sales@acme.com">Email us</a>
      <a href="tel:+1 (512) 555-0142">Call</a>
      contact also at noreply@acme.com and junk@sentry.io
      <a href="https://linkedin.com/company/acme">LinkedIn</a>
    </body></html>
    """
    fake = _FakeScraper(
        result={
            "social_links": {"linkedin": "https://linkedin.com/company/acme", "twitter": ""},
            "website_meta": {},
            "html_content": html,
        }
    )
    tracer = ContactTracer(scraper=fake)
    traced = await tracer.trace(website_url="https://acme.com", website_host="acme.com")
    await tracer.close()

    # Same-domain, non-role email preferred over the noreply@ and junk hosts.
    assert traced.email == "sales@acme.com"
    assert traced.phone_number is not None and traced.phone_number.startswith("+1")
    assert traced.linkedin_url == "https://linkedin.com/company/acme"
    assert traced.has_any is True
    assert traced.provenance["traced"] is True


@pytest.mark.asyncio
async def test_trace_derives_domain_from_ads_when_no_website() -> None:
    fake = _FakeScraper(
        result={"social_links": {}, "website_meta": {}, "html_content": "<html></html>"}
    )
    tracer = ContactTracer(scraper=fake)
    traced = await tracer.trace(website_url=None, ads=[_ad("derived.com")])
    await tracer.close()
    assert traced.website_host == "derived.com"


@pytest.mark.asyncio
async def test_trace_handles_scrape_failure_gracefully() -> None:
    fake = _FakeScraper(error=WebsiteScraperError("boom"))
    tracer = ContactTracer(scraper=fake)
    traced = await tracer.trace(website_url="https://acme.com")
    await tracer.close()
    assert traced.email is None
    assert traced.provenance["traced"] is False
    assert traced.provenance["reason"] == "scrape_failed"


@pytest.mark.asyncio
async def test_trace_without_domain_is_safe() -> None:
    fake = _FakeScraper()
    tracer = ContactTracer(scraper=fake)
    traced = await tracer.trace(website_url=None, ads=[])
    await tracer.close()
    assert traced.has_any is False
    assert traced.provenance["reason"] == "no_landing_domain"
