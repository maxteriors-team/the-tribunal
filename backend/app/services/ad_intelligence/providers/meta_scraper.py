"""In-house self-scrape provider for the public Meta Ad Library.

Owns the data source instead of paying a third party: it calls the **same**
internal endpoint the Ad Library *website* uses
(``POST .../ads/library/async/search_ads/``), which returns commercial US ads
the official ``/ads_archive`` API does not (that endpoint is political/issue
only for non-EU commercial searches). Page-name lookups resolve through the
sibling ``async/search_typeahead/`` endpoint.

This provider is **hard-gated** behind ``ad_library_allow_raw_scrape`` via
:func:`app.services.ad_intelligence.compliance.ensure_self_scrape_allowed` so
raw scraping stays opt-in and auditable (cf. *Meta v. Bright Data* + Meta ToS).
It is selected by the factory only when the operator also flips
``meta_self_scrape_enabled``.

Division of labour:

* :mod:`app.services.ad_intelligence.scraper_session` owns the LSD token /
  cookie / proxy / ``for (;;);`` transport lifecycle (``token_http`` or
  ``headless``).
* This module owns request shaping, cursor pagination, gentle jittered pacing,
  and hands raw ad dicts to the shared internal-shape normalizer in
  :mod:`app.services.ad_intelligence.providers._meta_internal_shape` — the same
  one the licensed third-party provider uses, so normalization never drifts.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from typing import Any, ClassVar

import httpx
import structlog

from app.core.config import settings
from app.services.ad_intelligence.compliance import ensure_self_scrape_allowed
from app.services.ad_intelligence.protocol import BaseAdIntelligenceProvider
from app.services.ad_intelligence.providers._meta_internal_shape import flatten, group_advertisers
from app.services.ad_intelligence.rate_limit import acquire_scrape_call_slot
from app.services.ad_intelligence.scraper_session import ScrapeSession, build_session
from app.services.ad_intelligence.types import (
    AdProviderResult,
    AdSearchRequest,
    DiscoveryWarning,
)
from app.services.lead_discovery.errors import LeadDiscoveryRateLimitError

logger = structlog.get_logger()

PLATFORM = "meta"
# The async endpoint returns ~30 ads per page regardless of a higher count hint.
_PAGE_SIZE = 30


class MetaScraperProvider(BaseAdIntelligenceProvider):
    """Self-scrape adapter over the Ad Library website's internal endpoints."""

    platform: ClassVar[str] = PLATFORM

    def __init__(
        self,
        *,
        session: ScrapeSession | None = None,
        strategy: str | None = None,
        proxy_url: str | None = None,
        min_delay_seconds: float | None = None,
        max_delay_seconds: float | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the self-scrape provider.

        Args:
            session: Injected :class:`ScrapeSession` (tests/DI). When omitted one
                is built from ``meta_scrape_strategy`` + ``meta_scrape_proxy_url``.
            strategy: Override the scrape strategy (``token_http`` | ``headless``).
            proxy_url: Override the residential/ISP proxy URL.
            min_delay_seconds / max_delay_seconds: Jittered inter-page delay
                bounds; fall back to settings. Pass ``0`` to disable in tests.
            client: Optional injected ``httpx.AsyncClient`` for the token_http
                session (tests/DI).
        """
        self._session = session or build_session(
            strategy=strategy, proxy_url=proxy_url, client=client
        )
        self._min_delay = (
            min_delay_seconds
            if min_delay_seconds is not None
            else settings.meta_scrape_min_delay_seconds
        )
        self._max_delay = (
            max_delay_seconds
            if max_delay_seconds is not None
            else settings.meta_scrape_max_delay_seconds
        )
        self._logger = logger.bind(component="meta_scraper_provider")

    async def close(self) -> None:
        """Close the underlying scrape session (HTTP client / browser)."""
        await self._session.close()

    async def search(self, request: AdSearchRequest) -> AdProviderResult:
        """Run one self-scrape search and return normalized advertisers + ads.

        Raises:
            AdLibraryProviderUnavailableError: when raw scraping is disabled by
                policy (``ad_library_allow_raw_scrape`` is false).
            LeadDiscoveryProviderError: hard transport / decoding failures.
            LeadDiscoveryRateLimitError: when the first page is throttled.
        """
        # Hard compliance gate — raises a mappable 503 unless explicitly enabled.
        ensure_self_scrape_allowed()

        # Gentle, scrape-specific hourly cap (far below the official tier) to
        # stay under the WAF radar, independent of the official-API budget.
        allowed, _used = await acquire_scrape_call_slot()
        if not allowed:
            raise LeadDiscoveryRateLimitError("Self-scrape hourly call cap reached")

        warnings: list[DiscoveryWarning] = []
        country = (request.country or "US").upper()

        page_id = request.page_id
        if page_id is None and request.page_name and not request.search_terms:
            page_id, resolve_warning = await self._resolve_page_id(request.page_name, country)
            if resolve_warning is not None:
                warnings.append(resolve_warning)

        raw_ads = await self._collect_ads(request, country, page_id, warnings)
        if not raw_ads:
            warnings.append(
                DiscoveryWarning(code="no_results", message="Self-scrape returned no ads.")
            )

        advertisers = group_advertisers(raw_ads, platform=self.platform, country=country)
        self._logger.info(
            "search_complete",
            country=country,
            raw_ad_count=len(raw_ads),
            advertiser_count=len(advertisers),
            has_page_filter=page_id is not None,
        )
        return AdProviderResult(
            platform=self.platform,
            advertisers=tuple(advertisers),
            requested_count=request.max_results,
            raw_ad_count=len(raw_ads),
            warnings=tuple(warnings),
        )

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    async def _collect_ads(
        self,
        request: AdSearchRequest,
        country: str,
        page_id: str | None,
        warnings: list[DiscoveryWarning],
    ) -> list[dict[str, Any]]:
        # ``session_id`` + ``collation_token`` are client-generated once and held
        # constant across all pages of one search (they group the "collation");
        # only ``forward_cursor`` advances per page.
        session_id = str(uuid.uuid4())
        collation_token = str(uuid.uuid4())
        forward_cursor: str | None = None

        raw_ads: list[dict[str, Any]] = []
        # Bound pages so a runaway cursor can't exhaust the gentle hourly budget.
        max_pages = max(1, (request.max_results // _PAGE_SIZE) + 2)
        for page_index in range(max_pages):
            form = self._build_search_form(
                request,
                country,
                page_id,
                session_id=session_id,
                collation_token=collation_token,
                forward_cursor=forward_cursor,
            )
            try:
                envelope = await self._fetch_page(form)
            except LeadDiscoveryRateLimitError:
                if not raw_ads:
                    raise
                warnings.append(
                    DiscoveryWarning(
                        code="rate_limited",
                        message="Self-scrape throttled mid-pagination; returning partial results.",
                    )
                )
                break

            payload = envelope.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            raw_ads.extend(flatten(payload.get("results") or []))
            if len(raw_ads) >= request.max_results:
                raw_ads = raw_ads[: request.max_results]
                break

            forward_cursor = _str(payload.get("forwardCursor") or payload.get("forward_cursor"))
            is_complete = payload.get("isResultComplete", payload.get("is_result_complete"))
            if not forward_cursor or is_complete:
                break
            # Gentle jittered pacing between pages to stay under the WAF radar.
            if page_index + 1 < max_pages:
                await self._sleep_jitter()
        return raw_ads

    async def _fetch_page(self, form: dict[str, Any]) -> dict[str, Any]:
        """Fetch one search page, backing off once on a transient throttle."""
        try:
            return await self._session.post("search_ads", form)
        except LeadDiscoveryRateLimitError:
            # One longer backoff, then retry; a second throttle propagates.
            await self._sleep(max(self._max_delay * 2, 1.0))
            return await self._session.post("search_ads", form)

    def _build_search_form(
        self,
        request: AdSearchRequest,
        country: str,
        page_id: str | None,
        *,
        session_id: str,
        collation_token: str,
        forward_cursor: str | None,
    ) -> dict[str, Any]:
        form: dict[str, Any] = {
            "count": _PAGE_SIZE,
            "active_status": "all",
            "ad_type": "all",
            "countries[0]": country,
            "media_type": "all",
            "session_id": session_id,
            "collation_token": collation_token,
            "sort_data[direction]": "desc",
            "sort_data[mode]": "relevancy_monthly_grouped",
            "forward_cursor": forward_cursor or "",
            "backward_cursor": "",
        }
        if page_id:
            form["search_type"] = "page"
            form["view_all_page_id"] = page_id
            form["search_page_ids[0]"] = page_id
        else:
            form["search_type"] = "keyword_unordered"
            form["q"] = request.search_terms or ""
        return form

    # ------------------------------------------------------------------
    # Page-name resolution
    # ------------------------------------------------------------------

    async def _resolve_page_id(
        self, page_name: str, country: str
    ) -> tuple[str | None, DiscoveryWarning | None]:
        """Resolve a page display name to its numeric id via ``search_typeahead``."""
        form = {
            "value": page_name,
            "session_id": str(uuid.uuid4()),
            "country_code": country,
        }
        try:
            envelope = await self._session.post("search_typeahead", form)
        except LeadDiscoveryRateLimitError:
            return None, DiscoveryWarning(
                code="page_resolve_failed",
                message=f"Could not resolve page '{page_name}' (throttled).",
            )

        payload = envelope.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        entries = payload.get("pageResults") or payload.get("page_results") or []
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            pid = _str(entry.get("page_id") or entry.get("id"))
            if pid:
                return pid, None
        return None, DiscoveryWarning(
            code="page_not_found",
            message=f"No Ad Library page found for '{page_name}'.",
        )

    # ------------------------------------------------------------------
    # Pacing
    # ------------------------------------------------------------------

    async def _sleep_jitter(self) -> None:
        low = max(0.0, self._min_delay)
        high = max(low, self._max_delay)
        await self._sleep(random.uniform(low, high))

    @staticmethod
    async def _sleep(seconds: float) -> None:
        if seconds > 0:
            await asyncio.sleep(seconds)


def _str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
