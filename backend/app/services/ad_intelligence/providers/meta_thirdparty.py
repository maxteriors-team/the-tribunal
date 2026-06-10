"""Config-gated third-party Meta ad-library provider.

The official ``/ads_archive`` endpoint has incomplete US/non-EU **commercial**
coverage. This provider wraps a licensed third-party scraper API (Apify
"Facebook Ad Library Scraper" actor, ScrapeCreators, or a SerpApi-style
endpoint) behind the same :class:`AdIntelligenceProvider` interface to get
fuller coverage **without** Meta app review.

It is **off by default** and only activates when a third-party API key is
configured (``meta_thirdparty_api_key`` / a ``meta_ad_library`` workspace
integration's ``thirdparty_api_key``). With no key it raises a clear auth error
so the caller can fall back to the official provider.

The normalized shape it emits is identical to
:class:`app.services.ad_intelligence.providers.meta_ad_library.MetaAdLibraryProvider`
so downstream persistence + signal code is provider-agnostic. Third-party
responses are typically richer (explicit ``is_active``, ``cta_type``,
``display_format``, carousel ``cards``), which we map straight through.
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from datetime import UTC, datetime
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

PLATFORM = "meta"

_DISPLAY_FORMAT_MEDIA = {
    "image": "image",
    "img": "image",
    "video": "video",
    "dpa": "carousel",
    "dco": "carousel",
    "carousel": "carousel",
}


class MetaThirdPartyProvider(BaseAdIntelligenceProvider):
    """Third-party Meta ad-library adapter (Apify / ScrapeCreators / SerpApi)."""

    platform: ClassVar[str] = PLATFORM

    def __init__(
        self,
        api_key: str | None = None,
        *,
        provider_name: str | None = None,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the third-party provider.

        Args:
            api_key: Third-party API key. Falls back to ``meta_thirdparty_api_key``.
            provider_name: Which adapter (``apify`` | ``scrapecreators`` |
                ``serpapi``). Falls back to ``meta_thirdparty_provider``.
            base_url: Override the adapter base URL.
            client: Optional injected ``httpx.AsyncClient`` for tests/DI.
        """
        self._api_key = api_key or settings.meta_thirdparty_api_key
        self._provider_name = (provider_name or settings.meta_thirdparty_provider or "").lower()
        self._base_url = (base_url or settings.meta_thirdparty_base_url or "").rstrip("/")
        self._client = client
        self._owns_client = client is None
        self._logger = logger.bind(component="meta_thirdparty_provider")

    @property
    def is_configured(self) -> bool:
        """Whether a usable API key is present (provider is enabled)."""
        return bool(self._api_key and self._base_url)

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
        """Run one third-party ad-library search.

        Raises:
            LeadDiscoveryAuthError: when no API key / base URL is configured.
            LeadDiscoveryRateLimitError: on third-party throttling (429).
            LeadDiscoveryProviderError: any other hard upstream failure.
        """
        if not self.is_configured:
            raise LeadDiscoveryAuthError(
                "Third-party Meta provider is not configured "
                "(set meta_thirdparty_api_key + meta_thirdparty_base_url)"
            )

        warnings: list[DiscoveryWarning] = []
        params = self._build_params(request)
        payload = await self._request(params)
        raw_ads = self._extract_ads(payload)
        if not raw_ads:
            warnings.append(
                DiscoveryWarning(code="no_results", message="Third-party provider returned no ads.")
            )

        advertisers = self._group_advertisers(raw_ads, request)
        self._logger.info(
            "search_complete",
            provider=self._provider_name,
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
        params: dict[str, Any] = {
            "api_key": self._api_key,
            "country": request.country,
            "limit": request.max_results,
        }
        if request.page_id:
            params["page_id"] = request.page_id
        if request.page_name:
            params["page_name"] = request.page_name
        if request.search_terms:
            params["query"] = request.search_terms
        params.update(request.params)
        return params

    async def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        client = await self._get_client()
        try:
            response = await client.get(self._base_url, params=params)
        except httpx.TimeoutException as exc:
            raise LeadDiscoveryProviderError(f"Third-party request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise LeadDiscoveryProviderError(f"Third-party request failed: {exc}") from exc

        if response.status_code == 200:
            try:
                payload: dict[str, Any] = response.json()
            except ValueError as exc:
                raise LeadDiscoveryProviderError("Third-party returned invalid JSON") from exc
            return payload
        if response.status_code == 429:
            self._logger.warning("rate_limited", status=response.status_code)
            raise LeadDiscoveryRateLimitError("Third-party provider throttled (429)")
        if response.status_code in (401, 403):
            self._logger.warning("auth_error", status=response.status_code)
            raise LeadDiscoveryAuthError(
                f"Third-party provider rejected credentials (status {response.status_code})"
            )
        self._logger.warning("provider_error", status=response.status_code)
        raise LeadDiscoveryProviderError(
            f"Third-party provider error (status {response.status_code})"
        )

    @staticmethod
    def _extract_ads(payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Pull the ad list out of common third-party response envelopes."""
        data = payload.get("data")
        if isinstance(data, dict):
            results = data.get("results") or data.get("ads")
            if isinstance(results, list):
                return _flatten(results)
        if isinstance(data, list):
            return _flatten(data)
        for key in ("results", "ads", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return _flatten(value)
        return []

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _group_advertisers(
        self, raw_ads: list[dict[str, Any]], request: AdSearchRequest
    ) -> list[NormalizedAdvertiser]:
        grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        for ad in raw_ads:
            page_id = _str(_dig(ad, "page_id") or _dig(ad, "snapshot", "page_id"))
            if not page_id:
                continue
            grouped.setdefault(page_id, []).append(ad)

        advertisers: list[NormalizedAdvertiser] = []
        for page_id, ads in grouped.items():
            normalized = tuple(self._normalize_ad(ad) for ad in ads)
            page_name = _str(_dig(ads[0], "page_name") or _dig(ads[0], "snapshot", "page_name"))
            website_url, website_host = _best_landing(normalized)
            advertisers.append(
                NormalizedAdvertiser(
                    platform=self.platform,
                    advertiser_key=page_id,
                    page_id=page_id,
                    advertiser_name=page_name,
                    page_url=f"https://www.facebook.com/{page_id}",
                    website_url=website_url,
                    website_host=website_host,
                    country_code=request.country,
                    ads=normalized,
                    raw={"page_id": page_id, "page_name": page_name, "ad_count": len(ads)},
                )
            )
        return advertisers

    @classmethod
    def _normalize_ad(cls, ad: dict[str, Any]) -> NormalizedAd:
        raw_snapshot = ad.get("snapshot")
        snapshot: dict[str, Any] = raw_snapshot if isinstance(raw_snapshot, dict) else {}
        ad_id = _str(ad.get("ad_archive_id") or ad.get("id") or ad.get("adArchiveID")) or ""

        body = _str(
            _dig(snapshot, "body", "text") or _dig(ad, "body") or _dig(ad, "ad_creative_body")
        )
        caption = _str(snapshot.get("caption") or ad.get("caption"))
        raw_cards = snapshot.get("cards")
        cards: list[dict[str, Any]] = raw_cards if isinstance(raw_cards, list) else []
        first_card: dict[str, Any] = cards[0] if cards else {}
        title = _str(first_card.get("title") or snapshot.get("title"))
        link_url = _str(
            first_card.get("link_url") or snapshot.get("link_url") or _caption_to_url(caption)
        )
        link_host = extract_host(link_url)

        is_active = bool(ad.get("is_active", ad.get("isActive", True)))
        start = _parse_epoch(ad.get("start_date") or ad.get("startDate"))
        stop = _parse_epoch(ad.get("end_date") or ad.get("endDate"))

        platforms_raw = ad.get("publisher_platform") or ad.get("publisher_platforms") or []
        platforms = (
            tuple(str(p) for p in platforms_raw if p) if isinstance(platforms_raw, list) else ()
        )

        display_format = _str(snapshot.get("display_format") or ad.get("display_format"))
        media_type = _DISPLAY_FORMAT_MEDIA.get((display_format or "").lower(), "unknown")
        if media_type == "unknown" and len(cards) > 1:
            media_type = "carousel"

        return NormalizedAd(
            ad_external_id=ad_id,
            body=body,
            title=title,
            link_caption=caption,
            link_url=link_url,
            link_host=link_host,
            cta_type=_str(snapshot.get("cta_type") or ad.get("cta_type")),
            snapshot_url=_str(ad.get("url") or ad.get("snapshot_url")),
            media_type=media_type,
            platforms=platforms,
            ad_delivery_start_time=start,
            ad_delivery_stop_time=stop,
            is_active=is_active,
            raw={k: v for k, v in ad.items() if k not in ("url", "snapshot_url")},
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _flatten(items: list[Any]) -> list[dict[str, Any]]:
    """Flatten one level of nesting (some adapters wrap each ad in a list)."""
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, list):
            out.extend(x for x in item if isinstance(x, dict))
    return out


def _dig(obj: Any, *keys: str) -> Any:
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _caption_to_url(caption: str | None) -> str | None:
    if not caption:
        return None
    candidate = caption.strip()
    if "://" in candidate:
        return candidate
    if "." in candidate and " " not in candidate:
        return f"https://{candidate}"
    return None


def _best_landing(ads: tuple[NormalizedAd, ...]) -> tuple[str | None, str | None]:
    host_counts: dict[str, int] = defaultdict(int)
    url_by_host: dict[str, str] = {}
    for ad in ads:
        if ad.link_host:
            host_counts[ad.link_host] += 1
            if ad.link_url:
                url_by_host.setdefault(ad.link_host, ad.link_url)
    if not host_counts:
        return None, None
    best = max(host_counts, key=lambda k: host_counts[k])
    return url_by_host.get(best), best


def _parse_epoch(value: object) -> datetime | None:
    """Parse a Unix epoch (seconds) or ISO string into a UTC datetime."""
    if value in (None, "", 0):
        return None
    if isinstance(value, int | float):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=UTC)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
