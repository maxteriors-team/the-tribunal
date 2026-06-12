"""Resolve the right ad-intelligence provider for a workspace + platform.

Credentials are read per-workspace from ``WorkspaceIntegration`` (encrypted at
rest), falling back to the global ``settings`` for single-tenant/dev. The
factory hides this so workers + the API just ask for "a Meta provider for this
workspace".

Selection:
    * ``meta`` -> :class:`MetaAdLibraryProvider` (official API, default). When
      ``use_thirdparty`` is requested *and* a third-party key is configured,
      :class:`MetaThirdPartyProvider` is returned instead. When the operator
      opts into self-scraping (``meta_self_scrape_enabled`` **and** the
      ``ad_library_allow_raw_scrape`` master switch), :class:`MetaScraperProvider`
      is preferred over the official token, which stays as an automatic
      fallback so a scrape break degrades instead of hard-failing.
    * ``google`` -> :class:`GoogleAdsTransparencyProvider` (SerpApi), only when
      the ``google_ads_transparency_enabled`` flag is on.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ad_advertiser import AdPlatform
from app.models.workspace import WorkspaceIntegration
from app.services.ad_intelligence.protocol import AdIntelligenceProvider
from app.services.ad_intelligence.providers.google_ads_transparency import (
    GoogleAdsTransparencyProvider,
)
from app.services.ad_intelligence.providers.meta_ad_library import MetaAdLibraryProvider
from app.services.ad_intelligence.providers.meta_scraper import MetaScraperProvider
from app.services.ad_intelligence.providers.meta_thirdparty import MetaThirdPartyProvider
from app.services.lead_discovery.errors import LeadDiscoveryAuthError

logger = structlog.get_logger()

_META_INTEGRATION = "meta_ad_library"
_GOOGLE_INTEGRATION = "google_ads_transparency"


async def _load_credentials(
    db: AsyncSession, workspace_id: uuid.UUID, integration_type: str
) -> dict[str, Any] | None:
    """Return decrypted credentials for an active integration, or ``None``."""
    result = await db.execute(
        select(WorkspaceIntegration).where(
            WorkspaceIntegration.workspace_id == workspace_id,
            WorkspaceIntegration.integration_type == integration_type,
            WorkspaceIntegration.is_active.is_(True),
        )
    )
    integration = result.scalar_one_or_none()
    if integration is None:
        return None
    return integration.safe_credentials()


async def build_provider(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    platform: str,
    use_thirdparty: bool = False,
) -> AdIntelligenceProvider:
    """Construct a provider for ``platform`` scoped to ``workspace_id``.

    Raises:
        LeadDiscoveryAuthError: when the platform is disabled or no usable
            credentials are configured (workspace integration or settings).
        ValueError: for an unknown platform.
    """
    resolved = AdPlatform(platform)
    if resolved is AdPlatform.META:
        return await _build_meta(db, workspace_id, use_thirdparty)
    if resolved is AdPlatform.GOOGLE:
        return await _build_google(db, workspace_id)
    raise ValueError(f"Unknown ad platform: {platform}")


async def _build_meta(
    db: AsyncSession, workspace_id: uuid.UUID, use_thirdparty: bool
) -> AdIntelligenceProvider:
    if not settings.ad_library_enabled:
        raise LeadDiscoveryAuthError("Ad-library discovery is disabled")

    creds = await _load_credentials(db, workspace_id, _META_INTEGRATION) or {}

    # Third-party fallback path (config-gated): only when explicitly requested
    # and a key is present (workspace integration or settings).
    thirdparty_key = creds.get("thirdparty_api_key") or settings.meta_thirdparty_api_key
    if use_thirdparty and (settings.meta_thirdparty_enabled or thirdparty_key):
        provider = MetaThirdPartyProvider(
            api_key=thirdparty_key,
            provider_name=creds.get("thirdparty_provider") or settings.meta_thirdparty_provider,
        )
        if provider.is_configured:
            return provider
        logger.warning("meta_thirdparty_requested_but_unconfigured", workspace_id=str(workspace_id))

    # In-house self-scrape path: preferred over the official token when the
    # operator opts in (per-workspace integration or settings) AND the raw-scrape
    # master switch is on. The official token below stays as automatic fallback.
    self_scrape_opt_in = bool(creds.get("self_scrape_enabled")) or settings.meta_self_scrape_enabled
    if self_scrape_opt_in and settings.ad_library_allow_raw_scrape:
        logger.info("meta_self_scrape_selected", workspace_id=str(workspace_id))
        return MetaScraperProvider(
            strategy=creds.get("scrape_strategy") or settings.meta_scrape_strategy,
            proxy_url=creds.get("scrape_proxy_url") or settings.meta_scrape_proxy_url,
        )

    access_token = creds.get("access_token") or settings.meta_ad_library_access_token
    if not access_token:
        raise LeadDiscoveryAuthError("No Meta Ad Library credentials configured for this workspace")
    return MetaAdLibraryProvider(
        access_token=access_token,
        default_country=creds.get("default_country") or settings.meta_ad_library_default_country,
    )


async def _build_google(db: AsyncSession, workspace_id: uuid.UUID) -> AdIntelligenceProvider:
    if not settings.google_ads_transparency_enabled:
        raise LeadDiscoveryAuthError("Google Ads Transparency is disabled")
    creds = await _load_credentials(db, workspace_id, _GOOGLE_INTEGRATION) or {}
    api_key = creds.get("api_key") or settings.serpapi_api_key
    provider = GoogleAdsTransparencyProvider(api_key=api_key)
    if not provider.is_configured and not settings.ad_library_allow_raw_scrape:
        raise LeadDiscoveryAuthError("No Google Ads Transparency (SerpApi) credentials configured")
    return provider
