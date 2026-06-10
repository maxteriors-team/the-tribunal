"""Meta Ad Library official-API provider.

Queries ``GET https://graph.facebook.com/<version>/ads_archive`` and maps the
result into normalized advertisers + ads. This is the default provider: it is
free and the metadata it returns (``ad_delivery_start_time`` /
``ad_delivery_stop_time`` / creative bodies + links) is exactly what the signal
engine needs to detect long-running, low-iteration advertisers — we do **not**
need spend/impressions (which are political-only anyway).

Grounding (verified against facebook.com/ads/library/api and 2026 practitioner
guides):

* ``ad_reached_countries`` is mandatory (format ``["US"]``); one country set
  per call.
* Cursor pagination only (``paging.cursors.after`` / ``paging.next``);
  ``limit`` up to 500.
* Default tier ~200 calls/hour/token; throttling surfaces as HTTP 429 with
  ``Retry-After`` or HTTP 400 ``code: 613`` (internal cost estimate), plus an
  ``X-App-Usage`` header.
* ``ad_snapshot_url`` embeds the access token — it is **never logged**.
* Requesting creative fields with deep pagination intermittently 500s; we keep
  list calls to a minimal field set and request creative fields per page in a
  second projection, which sidesteps the bug.
* US/non-EU **commercial** coverage on this endpoint is incomplete vs the web
  UI; the config-gated third-party provider exists for fuller coverage.
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

# Minimal projection for list pages — avoids the creative-field pagination 500s.
LIST_FIELDS: tuple[str, ...] = (
    "id",
    "page_id",
    "page_name",
    "ad_delivery_start_time",
    "ad_delivery_stop_time",
    "publisher_platforms",
    "ad_snapshot_url",
)
# Creative content projection requested alongside the list fields.
CREATIVE_FIELDS: tuple[str, ...] = (
    "ad_creative_bodies",
    "ad_creative_link_titles",
    "ad_creative_link_captions",
    "ad_creative_link_descriptions",
    "currency",
)

# Graph API error codes we treat as throttling (vs hard auth failures).
_THROTTLE_CODES = {4, 17, 32, 613}
_AUTH_CODES = {102, 190, 200, 10, 803}


class MetaAdLibraryProvider(BaseAdIntelligenceProvider):
    """Meta Ad Library provider over the official Graph API ``/ads_archive``."""

    platform: ClassVar[str] = PLATFORM

    def __init__(
        self,
        access_token: str | None = None,
        *,
        api_version: str | None = None,
        base_url: str | None = None,
        default_country: str | None = None,
        ad_type: str = "ALL",
        include_creative_fields: bool = True,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the provider.

        Args:
            access_token: Meta app token (``ads_read``). Falls back to the
                global ``meta_ad_library_access_token`` setting.
            api_version: Graph API version (e.g. ``v22.0``).
            base_url: Graph API base (default ``https://graph.facebook.com``).
            default_country: Fallback ``ad_reached_countries`` value.
            ad_type: ``/ads_archive`` ``ad_type`` filter (default ``ALL``).
            include_creative_fields: Request creative bodies/links per page.
            client: Optional injected ``httpx.AsyncClient`` (tests/DI). When
                omitted the provider owns its client lifecycle.
        """
        self._access_token = access_token or settings.meta_ad_library_access_token
        self._api_version = api_version or settings.meta_ad_library_api_version
        self._base_url = (base_url or settings.meta_ad_library_base_url).rstrip("/")
        self._default_country = default_country or settings.meta_ad_library_default_country
        self._ad_type = ad_type
        self._include_creative_fields = include_creative_fields
        self._client = client
        self._owns_client = client is None
        self._logger = logger.bind(component="meta_ad_library_provider")

    @property
    def _endpoint(self) -> str:
        return f"{self._base_url}/{self._api_version}/ads_archive"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.meta_ad_library_request_timeout_seconds),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client when this provider owns it."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(self, request: AdSearchRequest) -> AdProviderResult:
        """Run one ad-library search and return normalized advertisers + ads.

        Raises:
            LeadDiscoveryAuthError: token/permission failures.
            LeadDiscoveryRateLimitError: throttling (429 / code 613).
            LeadDiscoveryProviderError: any other hard upstream failure.
        """
        warnings: list[DiscoveryWarning] = []

        if not self._access_token:
            raise LeadDiscoveryAuthError("Meta Ad Library access token is not configured")

        country = (request.country or self._default_country or "US").upper()
        page_id = request.page_id

        # Resolve a vanity / display name to a numeric page id when needed.
        if page_id is None and request.page_name and not request.search_terms:
            page_id, resolve_warning = await self._resolve_page_id(request.page_name, country)
            if resolve_warning is not None:
                warnings.append(resolve_warning)

        params = self._build_params(request, country, page_id)

        raw_ads: list[dict[str, Any]] = []
        after: str | None = None
        # Bound pages so a runaway cursor can't exhaust the hourly budget.
        max_pages = max(1, (request.max_results // 100) + 2)
        for _ in range(max_pages):
            if after:
                params["after"] = after
            payload = await self._request(params)
            page_ads = payload.get("data") or []
            raw_ads.extend(page_ads)
            if len(raw_ads) >= request.max_results:
                raw_ads = raw_ads[: request.max_results]
                break
            after = self._next_cursor(payload)
            if not after:
                break

        advertisers = self._group_advertisers(raw_ads, country)

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
    # HTTP
    # ------------------------------------------------------------------

    def _build_params(
        self,
        request: AdSearchRequest,
        country: str,
        page_id: str | None,
    ) -> dict[str, Any]:
        fields = list(LIST_FIELDS)
        if self._include_creative_fields:
            fields.extend(CREATIVE_FIELDS)

        params: dict[str, Any] = {
            "access_token": self._access_token,
            "ad_reached_countries": f'["{country}"]',
            "ad_type": self._ad_type,
            "ad_active_status": "ALL",
            "fields": ",".join(fields),
            "limit": min(max(request.max_results, 1), 500),
        }
        if page_id:
            params["search_page_ids"] = f'["{page_id}"]'
        elif request.search_terms:
            params["search_terms"] = request.search_terms
        if request.ad_delivery_date_min:
            params["ad_delivery_date_min"] = request.ad_delivery_date_min.isoformat()
        if request.ad_delivery_date_max:
            params["ad_delivery_date_max"] = request.ad_delivery_date_max.isoformat()
        # Server-side sort hint; unsupported values are ignored by Meta.
        if request.sort_by and request.sort_by != "default":
            params["sort_by"] = request.sort_by
        return params

    async def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        """Issue one Graph API call, mapping failures to discovery errors.

        The access token in ``params`` is never logged; only the sanitized
        status/error code is surfaced.
        """
        client = await self._get_client()
        try:
            response = await client.get(self._endpoint, params=params)
        except httpx.TimeoutException as exc:
            raise LeadDiscoveryProviderError(f"Meta Ad Library request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise LeadDiscoveryProviderError(f"Meta Ad Library request failed: {exc}") from exc

        if response.status_code == 200:
            try:
                payload: dict[str, Any] = response.json()
            except ValueError as exc:
                raise LeadDiscoveryProviderError("Meta Ad Library returned invalid JSON") from exc
            return payload

        error_code, error_message = self._extract_error(response)

        if response.status_code == 429 or error_code in _THROTTLE_CODES:
            retry_after = response.headers.get("Retry-After")
            self._logger.warning(
                "rate_limited",
                status=response.status_code,
                error_code=error_code,
                retry_after=retry_after,
                app_usage=response.headers.get("X-App-Usage"),
            )
            raise LeadDiscoveryRateLimitError(
                error_message or f"Meta Ad Library throttled (status {response.status_code})"
            )
        if response.status_code in (401, 403) or error_code in _AUTH_CODES:
            self._logger.warning("auth_error", status=response.status_code, error_code=error_code)
            raise LeadDiscoveryAuthError(
                error_message or f"Meta Ad Library auth failed (status {response.status_code})"
            )
        self._logger.warning("provider_error", status=response.status_code, error_code=error_code)
        raise LeadDiscoveryProviderError(
            error_message or f"Meta Ad Library error (status {response.status_code})"
        )

    @staticmethod
    def _extract_error(response: httpx.Response) -> tuple[int | None, str | None]:
        try:
            error = response.json().get("error", {})
        except (ValueError, AttributeError):
            return None, None
        if not isinstance(error, dict):
            return None, None
        code = error.get("code")
        return (code if isinstance(code, int) else None), error.get("message")

    @staticmethod
    def _next_cursor(payload: dict[str, Any]) -> str | None:
        paging = payload.get("paging")
        if not isinstance(paging, dict):
            return None
        cursors = paging.get("cursors")
        if isinstance(cursors, dict) and cursors.get("after"):
            # Only advance when a "next" page link is actually present.
            return cursors["after"] if paging.get("next") else None
        return None

    async def _resolve_page_id(
        self, page_name: str, country: str
    ) -> tuple[str | None, DiscoveryWarning | None]:
        """Resolve a page display name to its numeric id via a search probe.

        There is no by-id endpoint on ``/ads_archive``; the lowest-permission
        path is to run a keyword search and take the page id that appears most
        often in the results.
        """
        probe_params: dict[str, Any] = {
            "access_token": self._access_token,
            "ad_reached_countries": f'["{country}"]',
            "ad_type": self._ad_type,
            "ad_active_status": "ALL",
            "fields": "id,page_id,page_name",
            "search_terms": page_name,
            "limit": 50,
        }
        try:
            payload = await self._request(probe_params)
        except LeadDiscoveryProviderError as exc:
            return None, DiscoveryWarning(
                code="page_resolve_failed",
                message=f"Could not resolve page '{page_name}': {exc}",
            )

        counts: dict[str, int] = defaultdict(int)
        for ad in payload.get("data") or []:
            pid = ad.get("page_id")
            if pid:
                counts[str(pid)] += 1
        if not counts:
            return None, DiscoveryWarning(
                code="page_not_found",
                message=f"No ads found for page '{page_name}'.",
            )
        best = max(counts, key=lambda k: counts[k])
        return best, None

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _group_advertisers(
        self, raw_ads: list[dict[str, Any]], country: str
    ) -> list[NormalizedAdvertiser]:
        """Group raw ads by page id into normalized advertisers."""
        grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        for ad in raw_ads:
            page_id = str(ad.get("page_id") or "").strip()
            if not page_id:
                continue
            grouped.setdefault(page_id, []).append(ad)

        advertisers: list[NormalizedAdvertiser] = []
        for page_id, ads in grouped.items():
            normalized_ads = tuple(self._normalize_ad(ad) for ad in ads)
            page_name = _first_str(ads[0].get("page_name"))
            website_url, website_host = _best_landing(normalized_ads)
            advertisers.append(
                NormalizedAdvertiser(
                    platform=self.platform,
                    advertiser_key=page_id,
                    page_id=page_id,
                    advertiser_name=page_name,
                    page_url=f"https://www.facebook.com/{page_id}",
                    website_url=website_url,
                    website_host=website_host,
                    country_code=country,
                    ads=normalized_ads,
                    raw={"page_id": page_id, "page_name": page_name, "ad_count": len(ads)},
                )
            )
        return advertisers

    @classmethod
    def _normalize_ad(cls, ad: dict[str, Any]) -> NormalizedAd:
        ad_id = str(ad.get("id") or "").strip()
        body = _first_list_item(ad.get("ad_creative_bodies"))
        title = _first_list_item(ad.get("ad_creative_link_titles"))
        caption = _first_list_item(ad.get("ad_creative_link_captions"))
        link_url = _caption_to_url(caption)
        link_host = extract_host(link_url) if link_url else extract_host(caption)

        start = _parse_meta_datetime(ad.get("ad_delivery_start_time"))
        stop = _parse_meta_datetime(ad.get("ad_delivery_stop_time"))
        # The official endpoint has no explicit active flag; an ad with no stop
        # time, or a stop time in the future, is treated as active.
        now = datetime.now(UTC)
        is_active = stop is None or stop > now

        platforms_raw = ad.get("publisher_platforms") or []
        platforms = (
            tuple(str(p) for p in platforms_raw if p) if isinstance(platforms_raw, list) else ()
        )

        return NormalizedAd(
            ad_external_id=ad_id,
            body=body,
            title=title,
            link_caption=caption,
            link_url=link_url,
            link_host=link_host,
            cta_type=None,
            snapshot_url=_first_str(ad.get("ad_snapshot_url")),
            media_type=cls._infer_media_type(ad),
            platforms=platforms,
            ad_delivery_start_time=start,
            ad_delivery_stop_time=stop,
            is_active=is_active,
            # Drop the token-bearing snapshot URL from the stored raw payload.
            raw={k: v for k, v in ad.items() if k != "ad_snapshot_url"},
        )

    @staticmethod
    def _infer_media_type(ad: dict[str, Any]) -> str:
        """Best-effort media classification from the official field set.

        The official API doesn't return media blobs, so we infer: multiple link
        titles imply a carousel; a body with no link implies text; otherwise we
        leave it unknown for the third-party provider to refine.
        """
        titles = ad.get("ad_creative_link_titles")
        if isinstance(titles, list) and len(titles) > 1:
            return "carousel"
        has_link = bool(ad.get("ad_creative_link_captions"))
        has_body = bool(ad.get("ad_creative_bodies"))
        if has_body and not has_link:
            return "text"
        return "unknown"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _first_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_list_item(value: object) -> str | None:
    """Return the first non-empty entry of a Graph list field, as a string."""
    if isinstance(value, list):
        for item in value:
            text = _first_str(item)
            if text:
                return text
        return None
    return _first_str(value)


def _caption_to_url(caption: str | None) -> str | None:
    """Turn a display caption (``shopify.com``) into a fetchable URL."""
    if not caption:
        return None
    candidate = caption.strip()
    if not candidate:
        return None
    if "://" in candidate:
        return candidate
    if "." in candidate and " " not in candidate:
        return f"https://{candidate}"
    return None


def _best_landing(ads: tuple[NormalizedAd, ...]) -> tuple[str | None, str | None]:
    """Pick the most common landing URL/host across an advertiser's ads."""
    host_counts: dict[str, int] = defaultdict(int)
    url_by_host: dict[str, str] = {}
    for ad in ads:
        if ad.link_host:
            host_counts[ad.link_host] += 1
            if ad.link_url:
                url_by_host.setdefault(ad.link_host, ad.link_url)
    if not host_counts:
        return None, None
    best_host = max(host_counts, key=lambda k: host_counts[k])
    return url_by_host.get(best_host), best_host


def _parse_meta_datetime(value: object) -> datetime | None:
    """Parse a Meta delivery timestamp (``YYYY-MM-DD`` or ISO 8601) to UTC."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Graph returns either a bare date or an ISO datetime with offset.
    candidates = (text, text.replace("Z", "+00:00"))
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
        return parsed.replace(tzinfo=UTC)
    except ValueError:
        return None
