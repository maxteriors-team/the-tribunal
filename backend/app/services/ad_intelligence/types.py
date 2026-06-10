"""Normalized value types for ad-library intelligence providers.

Every provider (Meta official API, Meta third-party fallback, Google Ads
Transparency) maps its native payload into these shapes. Downstream code — the
advertiser upsert store, the signal engine, prospecting — depends only on these,
so adding a provider never touches the persistence or signal layers.

These mirror ``app.services.lead_discovery.types`` and deliberately reuse its
:class:`DiscoveryWarning` so the two pipelines compose: an advertiser that
qualifies becomes a ``RawLead`` -> ``LeadProspect`` downstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.services.lead_discovery.types import DiscoveryWarning

__all__ = [
    "AdSearchRequest",
    "NormalizedAd",
    "NormalizedAdvertiser",
    "AdProviderResult",
    "DiscoveryWarning",
]


@dataclass(slots=True, frozen=True)
class AdSearchRequest:
    """A single ad-library query against one provider.

    Attributes:
        platform: ``"meta"`` or ``"google"`` (matches ``AdPlatform`` values).
        country: ISO-3166-1 alpha-2 code. Mandatory for Meta
            (``ad_reached_countries``).
        search_terms: Free-text keyword search. Optional when a specific page is
            targeted via ``page_id`` / ``page_name``.
        page_id: Provider-side page/advertiser id to scope to one advertiser.
        page_name: Vanity / display name to resolve to a page id.
        ad_delivery_date_min/max: Delivery-window bounds (effectively required
            by the Meta API to get stable results).
        sort_by: Provider sort hint (``"longest_running"`` is supported by Meta
            and directly useful for the ICP).
        max_results: Soft cap on advertisers/ads to return.
        params: Provider-specific extras, kept small and documented per provider.
    """

    platform: str
    country: str = "US"
    search_terms: str | None = None
    page_id: str | None = None
    page_name: str | None = None
    ad_delivery_date_min: date | None = None
    ad_delivery_date_max: date | None = None
    sort_by: str = "longest_running"
    max_results: int = 50
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class NormalizedAd:
    """One ad/creative emitted by a provider.

    Anything provider-specific lives in ``raw`` so audit rows keep everything
    the upstream returned (the snapshot URL embeds the token — never log it).
    """

    ad_external_id: str
    body: str | None = None
    title: str | None = None
    link_caption: str | None = None
    link_url: str | None = None
    link_host: str | None = None
    cta_type: str | None = None
    snapshot_url: str | None = None
    media_type: str = "unknown"
    platforms: tuple[str, ...] = ()
    ad_delivery_start_time: datetime | None = None
    ad_delivery_stop_time: datetime | None = None
    is_active: bool = True
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class NormalizedAdvertiser:
    """One advertiser plus the ads observed for it in a single search."""

    platform: str
    advertiser_key: str
    page_id: str | None = None
    advertiser_name: str | None = None
    page_url: str | None = None
    website_url: str | None = None
    website_host: str | None = None
    country_code: str | None = None
    ads: tuple[NormalizedAd, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ad_count(self) -> int:
        return len(self.ads)


@dataclass(slots=True, frozen=True)
class AdProviderResult:
    """Outcome of a single ``AdIntelligenceProvider.search`` call.

    Attributes:
        platform: Identifier of the provider that produced this result.
        advertisers: Advertisers (each carrying its ads). Empty tuple is valid.
        requested_count: ``max_results`` from the originating request.
        raw_ad_count: Number of raw ads the upstream API returned.
        warnings: Soft, non-fatal warnings emitted during the run.
    """

    platform: str
    advertisers: tuple[NormalizedAdvertiser, ...]
    requested_count: int
    raw_ad_count: int = 0
    warnings: tuple[DiscoveryWarning, ...] = ()

    @property
    def advertiser_count(self) -> int:
        return len(self.advertisers)

    @property
    def total_ad_count(self) -> int:
        return sum(a.ad_count for a in self.advertisers)
