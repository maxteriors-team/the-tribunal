"""Idempotent persistence for ad-library advertisers + creatives.

Turns a provider's :class:`AdProviderResult` into ``AdAdvertiser`` /
``AdCreative`` rows. Re-runs are safe:

* Advertisers are keyed by ``(workspace_id, platform, advertiser_key)``.
* Creatives are keyed by ``(advertiser_id, ad_external_id)`` — a re-query of the
  same ad updates its delivery stop time / active flag + ``last_seen_at`` rather
  than inserting a duplicate. This is what lets the monitor prove "still running
  the same ad over time".
* ``creative_hash`` is a non-secret normalized fingerprint (body + link host +
  media) so the signal engine can collapse the same creative re-published under
  different ad ids when counting *distinct* creatives.

This module only persists + maintains provenance; the signal math lives in
:mod:`app.services.ad_intelligence.signals`.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ad_advertiser import AdAdvertiser, AdPlatform
from app.models.ad_creative import AdCreative, AdMediaType
from app.services.ad_intelligence.types import (
    AdProviderResult,
    NormalizedAd,
    NormalizedAdvertiser,
)

logger = structlog.get_logger()

_WHITESPACE_RE = re.compile(r"\s+")
_MEDIA_TYPES = {m.value for m in AdMediaType}


def normalize_creative_hash(ad: NormalizedAd) -> str:
    """Return a deterministic, non-secret fingerprint for a creative.

    Same body + landing host + media type => same hash, so the same creative
    re-published under a new ad id collapses to one *distinct* creative. This is
    intentionally NOT a keyed/secret hash — it carries no PII.
    """
    body = _WHITESPACE_RE.sub(" ", (ad.body or "").strip().lower())
    host = (ad.link_host or "").strip().lower()
    title = _WHITESPACE_RE.sub(" ", (ad.title or "").strip().lower())
    media = ad.media_type if ad.media_type in _MEDIA_TYPES else "unknown"
    basis = f"{media}\u0001{host}\u0001{title}\u0001{body}".encode()
    return hashlib.blake2b(basis, digest_size=16).hexdigest()


def _coerce_media_type(value: str | None) -> AdMediaType:
    if value and value in _MEDIA_TYPES:
        return AdMediaType(value)
    return AdMediaType.UNKNOWN


class AdStore:
    """Upsert normalized provider results into advertiser/creative rows."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._logger = logger.bind(component="ad_store")

    async def upsert_result(
        self,
        *,
        workspace_id: Any,
        result: AdProviderResult,
        discovery_job_id: Any | None = None,
        scanned_at: datetime | None = None,
    ) -> list[AdAdvertiser]:
        """Persist every advertiser in ``result``; return the ORM rows.

        The rows are flushed (not committed) so the caller can run the signal
        engine in the same transaction and commit once.
        """
        now = scanned_at or datetime.now(UTC)
        platform = AdPlatform(result.platform)
        advertisers: list[AdAdvertiser] = []
        for normalized in result.advertisers:
            advertiser = await self._upsert_advertiser(
                workspace_id=workspace_id,
                platform=platform,
                normalized=normalized,
                discovery_job_id=discovery_job_id,
                now=now,
            )
            advertisers.append(advertiser)
        await self._db.flush()
        return advertisers

    async def _upsert_advertiser(
        self,
        *,
        workspace_id: Any,
        platform: AdPlatform,
        normalized: NormalizedAdvertiser,
        discovery_job_id: Any | None,
        now: datetime,
    ) -> AdAdvertiser:
        existing = await self._db.execute(
            select(AdAdvertiser).where(
                AdAdvertiser.workspace_id == workspace_id,
                AdAdvertiser.platform == platform,
                AdAdvertiser.advertiser_key == normalized.advertiser_key,
            )
        )
        advertiser = existing.scalar_one_or_none()
        is_new = advertiser is None

        if advertiser is None:
            advertiser = AdAdvertiser(
                workspace_id=workspace_id,
                platform=platform,
                advertiser_key=normalized.advertiser_key,
                first_seen_at=now,
            )
            self._db.add(advertiser)

        # Refresh public identity (prefer newest non-empty values).
        advertiser.page_id = normalized.page_id or advertiser.page_id
        advertiser.advertiser_name = normalized.advertiser_name or advertiser.advertiser_name
        advertiser.page_url = normalized.page_url or advertiser.page_url
        advertiser.website_url = normalized.website_url or advertiser.website_url
        advertiser.website_host = normalized.website_host or advertiser.website_host
        advertiser.country_code = normalized.country_code or advertiser.country_code
        advertiser.discovery_job_id = discovery_job_id or advertiser.discovery_job_id
        advertiser.last_seen_at = now
        advertiser.last_scanned_at = now
        if advertiser.first_seen_at is None:
            advertiser.first_seen_at = now
        advertiser.raw_payload = dict(normalized.raw)

        # Flush so a brand-new advertiser gets its id before creatives attach.
        await self._db.flush()

        # Load existing creatives explicitly (avoid async lazy-load on the
        # relationship collection). A brand-new advertiser has none yet.
        existing_by_ad_id: dict[str, AdCreative] = {}
        if not is_new:
            rows = await self._db.execute(
                select(AdCreative).where(AdCreative.advertiser_id == advertiser.id)
            )
            existing_by_ad_id = {c.ad_external_id: c for c in rows.scalars().all()}
        for ad in normalized.ads:
            if not ad.ad_external_id:
                continue
            self._upsert_creative(
                workspace_id=workspace_id,
                advertiser=advertiser,
                ad=ad,
                existing=existing_by_ad_id.get(ad.ad_external_id),
                now=now,
            )
        return advertiser

    def _upsert_creative(
        self,
        *,
        workspace_id: Any,
        advertiser: AdAdvertiser,
        ad: NormalizedAd,
        existing: AdCreative | None,
        now: datetime,
    ) -> AdCreative:
        creative_hash = normalize_creative_hash(ad)
        media_type = _coerce_media_type(ad.media_type)
        platforms = list(ad.platforms)

        if existing is None:
            creative = AdCreative(
                workspace_id=workspace_id,
                advertiser_id=advertiser.id,
                ad_external_id=ad.ad_external_id,
                first_seen_at=now,
            )
            self._db.add(creative)
        else:
            creative = existing

        creative.creative_hash = creative_hash
        creative.body = ad.body
        creative.title = ad.title
        creative.link_caption = ad.link_caption
        creative.link_url = ad.link_url
        creative.link_host = ad.link_host
        creative.cta_type = ad.cta_type
        creative.snapshot_url = ad.snapshot_url
        creative.media_type = media_type
        creative.platforms = platforms
        # Preserve the earliest delivery start we've ever seen for this ad.
        if ad.ad_delivery_start_time is not None and (
            creative.ad_delivery_start_time is None
            or ad.ad_delivery_start_time < creative.ad_delivery_start_time
        ):
            creative.ad_delivery_start_time = ad.ad_delivery_start_time
        creative.ad_delivery_stop_time = ad.ad_delivery_stop_time
        creative.is_active = ad.is_active
        creative.last_seen_at = now
        if creative.first_seen_at is None:
            creative.first_seen_at = now
        # Drop token-bearing snapshot URL from the stored raw payload defensively.
        creative.raw_payload = {
            k: v for k, v in (ad.raw or {}).items() if k not in ("ad_snapshot_url", "url")
        }
        return creative
