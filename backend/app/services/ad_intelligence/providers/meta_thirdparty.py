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

from typing import Any, ClassVar

import httpx
import structlog

from app.core.config import settings
from app.services.ad_intelligence.protocol import BaseAdIntelligenceProvider
from app.services.ad_intelligence.providers._meta_internal_shape import (
    flatten,
    group_advertisers,
)
from app.services.ad_intelligence.types import (
    AdProviderResult,
    AdSearchRequest,
    DiscoveryWarning,
)
from app.services.lead_discovery.errors import (
    LeadDiscoveryAuthError,
    LeadDiscoveryProviderError,
    LeadDiscoveryRateLimitError,
)

logger = structlog.get_logger()

PLATFORM = "meta"


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

        advertisers = group_advertisers(raw_ads, platform=self.platform, country=request.country)
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
                return flatten(results)
        if isinstance(data, list):
            return flatten(data)
        for key in ("results", "ads", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return flatten(value)
        return []
