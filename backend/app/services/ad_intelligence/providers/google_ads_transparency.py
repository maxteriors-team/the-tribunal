"""Google Ads Transparency Center provider.

Google has **no official** Ads Transparency API, so the supported path is a
SerpApi-style adapter (``engine=google_ads_transparency_center``). This provider
is **lower priority** than Meta and fully behind the
``google_ads_transparency_enabled`` feature flag.

It normalizes SerpApi's ``ad_creatives`` list (``advertiser_id``, ``advertiser``,
``format``, ``target_domain``, ``first_shown`` / ``last_shown`` epochs,
``total_days_shown``) into the same advertiser/ad shape as the Meta providers,
so persistence + signal code is provider-agnostic.

A raw-scrape fallback exists only as a documented, hard-gated path
(``ad_library_allow_raw_scrape``); it is not shipped enabled because scraping
Google's UI carries ToS/robots risk. With the flag off it raises a clear error.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import httpx
import structlog

from app.core.config import settings
from app.services.ad_intelligence.protocol import BaseAdIntelligenceProvider
from app.services.ad_intelligence.types import (
    AdProviderResult,
    AdSearchRequest,
    DiscoveryWarning,
    NormalizedAd,
    NormalizedAdvertiser,
)
from app.services.lead_discovery.dedupe import extract_host
from app.services.lead_discovery.errors import (
    LeadDiscoveryAuthError,
    LeadDiscoveryProviderError,
    LeadDiscoveryRateLimitError,
)

logger = structlog.get_logger()

PLATFORM = "google"

# SerpApi region codes (Google's geo target ids). Extend as needed.
_REGION_BY_COUNTRY = {
    "US": "2840",
    "CA": "2124",
    "GB": "2826",
    "UK": "2826",
    "AU": "2036",
    "DE": "2276",
    "FR": "2250",
}
# An advertiser whose most recent creative was shown within this window is
# treated as currently active (Google does not return an explicit active flag).
_ACTIVE_RECENCY_DAYS = 7

_FORMAT_MEDIA = {"video": "video", "image": "image", "text": "text"}


class GoogleAdsTransparencyProvider(BaseAdIntelligenceProvider):
    """Google Ads Transparency Center adapter via a SerpApi-style endpoint."""

    platform: ClassVar[str] = PLATFORM

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the provider.

        Args:
            api_key: SerpApi key. Falls back to the ``serpapi_api_key`` setting.
            base_url: SerpApi base URL (default ``https://serpapi.com``).
            client: Optional injected ``httpx.AsyncClient`` for tests/DI.
        """
        self._api_key = api_key or settings.serpapi_api_key
        self._base_url = (base_url or settings.serpapi_base_url).rstrip("/")
        self._client = client
        self._owns_client = client is None
        self._logger = logger.bind(component="google_ads_transparency_provider")

    @property
    def is_configured(self) -> bool:
        """Whether a SerpApi key is present (provider is usable)."""
        return bool(self._api_key)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.meta_ad_library_request_timeout_seconds),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def search(self, request: AdSearchRequest) -> AdProviderResult:
        """Run one Google Ads Transparency search via SerpApi.

        Raises:
            LeadDiscoveryAuthError: when no SerpApi key is configured, or the
                raw-scrape fallback is requested while disabled.
            LeadDiscoveryRateLimitError: on SerpApi throttling (429).
            LeadDiscoveryProviderError: any other hard upstream failure.
        """
        if not self.is_configured:
            if settings.ad_library_allow_raw_scrape:
                # Policy gate is satisfied; the fallback itself is a no-op stub
                # (we do not ship an unsanctioned crawler).
                return await self._raw_scrape_fallback(request)
            raise LeadDiscoveryAuthError(
                "Google Ads Transparency requires a SerpApi key (serpapi_api_key) "
                "or the raw-scrape fallback flag"
            )

        warnings: list[DiscoveryWarning] = []
        params = self._build_params(request)
        payload = await self._request(params)

        status = (payload.get("search_metadata") or {}).get("status")
        if status and status != "Success":
            warnings.append(
                DiscoveryWarning(code="serpapi_status", message=f"SerpApi status: {status}")
            )

        creatives = payload.get("ad_creatives")
        raw_ads = creatives if isinstance(creatives, list) else []
        advertisers = self._group_advertisers(raw_ads, request)

        self._logger.info(
            "search_complete",
            raw_ad_count=len(raw_ads),
            advertiser_count=len(advertisers),
        )
        return AdProviderResult(
            platform=self.platform,
            advertisers=tuple(advertisers),
            requested_count=request.max_results,
            raw_ad_count=len(raw_ads),
            warnings=tuple(warnings),
        )

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _build_params(self, request: AdSearchRequest) -> dict[str, Any]:
        region = _REGION_BY_COUNTRY.get((request.country or "").upper(), "anywhere")
        params: dict[str, Any] = {
            "engine": "google_ads_transparency_center",
            "api_key": self._api_key,
            "region": region,
        }
        # ``page_id`` carries a Google advertiser id (AR...) when targeting one
        # advertiser; otherwise we search by domain or free text.
        if request.page_id:
            params["advertiser_id"] = request.page_id
        elif request.page_name and "." in request.page_name and " " not in request.page_name:
            params["domain"] = request.page_name
        elif request.search_terms:
            params["text"] = request.search_terms
        elif request.page_name:
            params["text"] = request.page_name
        if request.ad_delivery_date_min:
            params["start_date"] = request.ad_delivery_date_min.strftime("%Y%m%d")
        if request.ad_delivery_date_max:
            params["end_date"] = request.ad_delivery_date_max.strftime("%Y%m%d")
        return params

    async def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        client = await self._get_client()
        try:
            response = await client.get(f"{self._base_url}/search", params=params)
        except httpx.TimeoutException as exc:
            raise LeadDiscoveryProviderError(f"SerpApi request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise LeadDiscoveryProviderError(f"SerpApi request failed: {exc}") from exc

        if response.status_code == 200:
            try:
                payload: dict[str, Any] = response.json()
            except ValueError as exc:
                raise LeadDiscoveryProviderError("SerpApi returned invalid JSON") from exc
            return payload
        if response.status_code == 429:
            self._logger.warning("rate_limited", status=response.status_code)
            raise LeadDiscoveryRateLimitError("SerpApi throttled (429)")
        if response.status_code in (401, 403):
            self._logger.warning("auth_error", status=response.status_code)
            raise LeadDiscoveryAuthError(
                f"SerpApi rejected credentials (status {response.status_code})"
            )
        self._logger.warning("provider_error", status=response.status_code)
        raise LeadDiscoveryProviderError(f"SerpApi error (status {response.status_code})")

    async def _raw_scrape_fallback(self, request: AdSearchRequest) -> AdProviderResult:
        """Documented raw-scrape fallback (disabled by default).

        Even when ``ad_library_allow_raw_scrape`` is on, no scraper ships here:
        scraping Google's UI carries ToS/robots risk, so we return an empty
        result with a warning rather than performing an unsanctioned crawl. A
        future, compliance-reviewed scraper can populate this.
        """
        self._logger.warning("raw_scrape_requested_but_not_implemented")
        return AdProviderResult(
            platform=self.platform,
            advertisers=(),
            requested_count=request.max_results,
            raw_ad_count=0,
            warnings=(
                DiscoveryWarning(
                    code="raw_scrape_unavailable",
                    message="Raw Google scraping is not implemented; configure a SerpApi key.",
                ),
            ),
        )

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _group_advertisers(
        self, raw_ads: list[dict[str, Any]], request: AdSearchRequest
    ) -> list[NormalizedAdvertiser]:
        grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        for ad in raw_ads:
            advertiser_id = _advertiser_id(ad)
            domain = _str(ad.get("target_domain"))
            key = advertiser_id or domain
            if not key:
                continue
            grouped.setdefault(key, []).append(ad)

        advertisers: list[NormalizedAdvertiser] = []
        for key, ads in grouped.items():
            normalized = tuple(self._normalize_ad(ad) for ad in ads)
            advertiser_name = _advertiser_name(ads[0])
            target_domain = _str(ads[0].get("target_domain"))
            website_host = extract_host(target_domain) if target_domain else None
            website_url = f"https://{target_domain}" if target_domain else None
            advertiser_id = _advertiser_id(ads[0])
            page_url = (
                f"https://adstransparency.google.com/advertiser/{advertiser_id}"
                if advertiser_id
                else None
            )
            advertisers.append(
                NormalizedAdvertiser(
                    platform=self.platform,
                    advertiser_key=key,
                    page_id=advertiser_id,
                    advertiser_name=advertiser_name,
                    page_url=page_url,
                    website_url=website_url,
                    website_host=website_host,
                    country_code=(request.country or None),
                    ads=normalized,
                    raw={"advertiser_id": advertiser_id, "target_domain": target_domain},
                )
            )
        return advertisers

    @classmethod
    def _normalize_ad(cls, ad: dict[str, Any]) -> NormalizedAd:
        ad_id = _str(ad.get("ad_creative_id") or ad.get("id")) or ""
        fmt = (_str(ad.get("format")) or "").lower()
        media_type = _FORMAT_MEDIA.get(fmt, "unknown")
        target_domain = _str(ad.get("target_domain"))
        link_url = f"https://{target_domain}" if target_domain else None

        start = _parse_shown(ad.get("first_shown"), ad.get("first_shown_datetime"))
        stop = _parse_shown(ad.get("last_shown"), ad.get("last_shown_datetime"))
        now = datetime.now(UTC)
        is_active = stop is None or stop >= now - timedelta(days=_ACTIVE_RECENCY_DAYS)

        return NormalizedAd(
            ad_external_id=ad_id,
            body=None,
            title=_str(ad.get("advertiser")),
            link_caption=target_domain,
            link_url=link_url,
            link_host=extract_host(link_url) if link_url else None,
            cta_type=None,
            snapshot_url=_str(ad.get("details_link")),
            media_type=media_type,
            platforms=("GOOGLE",),
            ad_delivery_start_time=start,
            # ``last_shown`` is the end of the observed delivery window.
            ad_delivery_stop_time=None if is_active else stop,
            is_active=is_active,
            raw={k: v for k, v in ad.items() if k != "link"},
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _advertiser_id(ad: dict[str, Any]) -> str | None:
    """SerpApi returns ``advertiser_id`` flat or ``advertiser.id`` nested."""
    flat = _str(ad.get("advertiser_id"))
    if flat:
        return flat
    advertiser = ad.get("advertiser")
    if isinstance(advertiser, dict):
        return _str(advertiser.get("id"))
    return None


def _advertiser_name(ad: dict[str, Any]) -> str | None:
    advertiser = ad.get("advertiser")
    if isinstance(advertiser, dict):
        return _str(advertiser.get("name"))
    return _str(advertiser)


def _parse_shown(epoch: object, iso: object = None) -> datetime | None:
    """Parse SerpApi ``first_shown`` epoch or ``*_datetime`` ISO string."""
    if isinstance(epoch, int | float) and epoch:
        try:
            return datetime.fromtimestamp(float(epoch), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(epoch, str) and epoch.isdigit():
        return datetime.fromtimestamp(int(epoch), tz=UTC)
    text = _str(iso)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
