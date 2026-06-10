"""Contact tracing for ad-library advertisers.

An advertiser starts as just a Facebook Page / Google advertiser. To reach a
human we trace:

1. The **landing domain** the ads point at (from creative link captions / the
   advertiser's resolved website).
2. The advertiser's public website — scraped (via the existing
   ``WebsiteScraperService``) for social links, and mined for a public email /
   phone in the page markup.

Returns normalized identifiers (website, email, phone, social links) plus
provenance describing where each came from. Emails/phones are treated as PII by
the caller: they land on the encrypted ``LeadProspect`` columns, never on the
plaintext advertiser row.

This module performs network I/O only against the landing website (robots/ToS
respected by ``WebsiteScraperService``); it does not scrape Facebook/Google UIs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.services.ad_intelligence.types import NormalizedAd
from app.services.lead_discovery.dedupe import extract_host
from app.services.scraping.website_scraper import (
    WebsiteScraperError,
    WebsiteScraperService,
)
from app.utils.phone import normalize_phone_safe

logger = structlog.get_logger()

# Conservative public-contact extraction patterns.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_MAILTO_RE = re.compile(r"mailto:([^\"'?>\s]+)", re.IGNORECASE)
_TEL_RE = re.compile(r"tel:([+0-9().\-\s]{7,})", re.IGNORECASE)
_PHONE_RE = re.compile(r"\+?\d[\d().\-\s]{7,}\d")

# Role inboxes we keep but de-prioritize (still better than nothing).
_ROLE_PREFIXES = ("noreply", "no-reply", "donotreply", "postmaster", "abuse", "mailer")
# Junk emails embedded in tracking pixels / libraries we never want.
_JUNK_EMAIL_HOSTS = (
    "sentry.io",
    "wixpress.com",
    "example.com",
    "schema.org",
    "sentry-next.wixpress.com",
)


@dataclass(slots=True)
class TracedContact:
    """Normalized identifiers traced for an advertiser."""

    website_url: str | None = None
    website_host: str | None = None
    email: str | None = None
    phone_number: str | None = None
    linkedin_url: str | None = None
    social_links: dict[str, str] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def has_any(self) -> bool:
        return bool(self.email or self.phone_number or self.website_url or self.linkedin_url)


def landing_domain_from_ads(ads: list[NormalizedAd]) -> tuple[str | None, str | None]:
    """Pick the most common landing URL/host across an advertiser's ads."""
    counts: dict[str, int] = {}
    url_by_host: dict[str, str] = {}
    for ad in ads:
        host = ad.link_host or extract_host(ad.link_caption) or extract_host(ad.link_url)
        if not host:
            continue
        counts[host] = counts.get(host, 0) + 1
        if ad.link_url:
            url_by_host.setdefault(host, ad.link_url)
    if not counts:
        return None, None
    best = max(counts, key=lambda k: counts[k])
    return url_by_host.get(best) or f"https://{best}", best


def _best_email(candidates: list[str], website_host: str | None) -> str | None:
    """Pick the best public email: same-domain + non-role wins."""
    seen: list[str] = []
    for raw in candidates:
        email = raw.strip().strip(".").lower()
        if not email or "@" not in email:
            continue
        host = email.split("@", 1)[1]
        if any(host.endswith(j) for j in _JUNK_EMAIL_HOSTS):
            continue
        if email not in seen:
            seen.append(email)
    if not seen:
        return None

    def _rank(email: str) -> tuple[int, int]:
        host = email.split("@", 1)[1]
        local = email.split("@", 1)[0]
        same_domain = 0 if (website_host and host.endswith(website_host)) else 1
        role = 1 if local.startswith(_ROLE_PREFIXES) else 0
        return (same_domain, role)

    return sorted(seen, key=_rank)[0]


def _extract_contacts_from_html(
    html: str, website_host: str | None
) -> tuple[str | None, str | None]:
    """Extract a best-effort public email + phone from page markup."""
    emails = _MAILTO_RE.findall(html) + _EMAIL_RE.findall(html)
    email = _best_email(emails, website_host)

    phone: str | None = None
    tel_matches = _TEL_RE.findall(html)
    candidates = tel_matches or _PHONE_RE.findall(html)
    for candidate in candidates:
        normalized = normalize_phone_safe(candidate)
        if normalized:
            phone = normalized
            break
    return email, phone


class ContactTracer:
    """Trace public contact identifiers for an advertiser's landing website."""

    def __init__(self, scraper: WebsiteScraperService | None = None) -> None:
        self._scraper = scraper or WebsiteScraperService()
        self._owns_scraper = scraper is None
        self._logger = logger.bind(component="contact_tracer")

    async def close(self) -> None:
        if self._owns_scraper:
            await self._scraper.close()

    async def trace(
        self,
        *,
        website_url: str | None,
        website_host: str | None = None,
        ads: list[NormalizedAd] | None = None,
    ) -> TracedContact:
        """Resolve and enrich the best website for an advertiser.

        Args:
            website_url: Known advertiser website (preferred).
            website_host: Known host (used for same-domain email ranking).
            ads: Optional normalized ads to derive a landing domain from when no
                website is known.
        """
        url = website_url
        host = website_host or extract_host(website_url)
        if not url and ads:
            url, host = landing_domain_from_ads(ads)

        if not url:
            return TracedContact(provenance={"traced": False, "reason": "no_landing_domain"})

        traced = TracedContact(website_url=url, website_host=host or extract_host(url))
        try:
            result = await self._scraper.scrape_website(url)
        except WebsiteScraperError as exc:
            self._logger.info("trace_scrape_failed", url=url, error=str(exc))
            traced.provenance = {"traced": False, "reason": "scrape_failed", "website": url}
            return traced

        social_links: dict[str, str] = {
            k: v for k, v in (result.get("social_links") or {}).items() if v
        }
        traced.social_links = social_links
        traced.linkedin_url = social_links.get("linkedin")

        html = result.get("html_content") or ""
        email, phone = _extract_contacts_from_html(html, traced.website_host)
        traced.email = email
        traced.phone_number = phone
        traced.provenance = {
            "traced": traced.has_any,
            "website": url,
            "email_found": bool(email),
            "phone_found": bool(phone),
            "social_count": len(social_links),
        }
        self._logger.info(
            "advertiser_contact_traced",
            website=url,
            email_found=bool(email),
            phone_found=bool(phone),
            social_count=len(social_links),
        )
        return traced
