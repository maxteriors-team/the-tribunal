"""Compliance + privacy guardrails for ad-library intelligence.

Centralizes the policy decisions the feature must honor:

* **Prefer official + licensed APIs.** The Meta Ad Library official API and
  licensed third-party APIs (Apify / ScrapeCreators / SerpApi) are always
  preferred over raw scraping. Meta ToS restricts scraping (cf. Meta v. Bright
  Data), so any raw-scrape path is hard-gated behind
  ``ad_library_allow_raw_scrape`` and disabled by default.
* **Snapshot rendering is opt-in.** Headless rendering of creative media is
  gated behind ``ad_library_snapshot_rendering_enabled`` to avoid a heavy
  browser dependency in the API process and to keep us off a scraping path.
* **PII is encrypted + suppressed.** Traced emails/phones ride the existing
  encrypted ``LeadProspect`` / ``Contact`` columns, and promotion runs through
  the global opt-out/suppression check (see ``ProspectPromotionService``).
* **Credentials are masked** in API responses (see ``integrations/credentials``)
  and tokens are never logged (snapshot URLs are stripped before persistence).

These helpers raise a typed, mappable error when a disabled capability is
requested so the API boundary returns a clear 503 instead of silently scraping.
"""

from __future__ import annotations

import structlog

from app.core.config import settings
from app.services.ad_intelligence.errors import AdLibraryProviderUnavailableError

logger = structlog.get_logger()


def ensure_raw_scrape_allowed(context: str) -> None:
    """Raise unless raw scraping is explicitly enabled by configuration.

    Args:
        context: Short label of the call site for the audit log.

    Raises:
        AdLibraryProviderUnavailableError: when raw scraping is disabled.
    """
    if settings.ad_library_allow_raw_scrape:
        logger.warning("ad_library_raw_scrape_allowed", context=context)
        return
    raise AdLibraryProviderUnavailableError(
        "Raw ad-library scraping is disabled by policy; use the official or a "
        "licensed third-party API (set ad_library_allow_raw_scrape to override)."
    )


def ensure_self_scrape_allowed() -> None:
    """Raise unless in-house self-scraping is allowed by configuration.

    A clearer audit label around :func:`ensure_raw_scrape_allowed` for the
    self-scrape provider, which targets the public Ad Library website's internal
    endpoint rather than a licensed third-party API. Honors the same
    ``ad_library_allow_raw_scrape`` master switch (default off, operator-enabled,
    auditable) cited in *Meta v. Bright Data*.
    """
    ensure_raw_scrape_allowed("meta_self_scrape")


def is_snapshot_rendering_enabled() -> bool:
    """Whether headless creative-media rendering is enabled (opt-in)."""
    return bool(settings.ad_library_snapshot_rendering_enabled)


def redact_snapshot_url(url: str | None) -> str | None:
    """Strip the embedded access token from a snapshot URL for safe logging.

    The Meta ``ad_snapshot_url`` embeds the app access token in its query
    string; we keep the path for reference but drop the token so it never
    lands in logs or audit payloads.
    """
    if not url:
        return None
    base, sep, _query = url.partition("?")
    return f"{base}{sep}[redacted]" if sep else base
